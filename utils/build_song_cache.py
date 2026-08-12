#!/usr/bin/env python3
"""Builds and maintains the player's song metadata cache.

The player maintains this cache on its own -- a song it has not seen is read and
cached the first time a playlist considers it. Running this script simply moves
that cost off the practice laptop and into a moment when nobody is waiting, which
is worth doing after adding a batch of new music.

Usage, from the repository root or anywhere:

    python utils/build_song_cache.py              # add and refresh entries
    python utils/build_song_cache.py --prune      # also drop deleted files
    python utils/build_song_cache.py --rebuild    # re-read everything
    python utils/build_song_cache.py --verify     # cross-check with ffprobe
    python utils/build_song_cache.py --check-library   # after rebuilding the library
    python utils/build_song_cache.py --music-dir /path/to/music

Without --music-dir the music directory is read from music.ini, so normally no
arguments are needed.
"""
import argparse
import configparser
import json
import math
import os
import statistics
import subprocess
import sys
import time

# Import the player's modules regardless of where this is run from.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, REPO_DIR)

# pylint: disable=wrong-import-position
import app_paths
import practice_type_rules
from tinytag import TinyTag, TinyTagException
from song_cache import SongCache, DEFAULT_CACHE_FILE, CACHED_FIELDS

MUSIC_EXTENSIONS = (".mp3", ".ogg", ".m4a", ".flac", ".wav")


def read_music_dir_from_config() -> str:
    """Returns music_dir from music.ini, or an empty string if unavailable."""
    config_path = app_paths.user_path("music.ini", seed_from_app_dir=False)
    if not os.path.isfile(config_path):
        return ""
    parser = configparser.ConfigParser()
    try:
        parser.read(config_path)
        return parser.get("user", "music_dir", fallback="")
    except configparser.Error:
        return ""


def collect_music_files(music_dir: str) -> list:
    """Returns every music file under `music_dir`."""
    paths = []
    for root, _, files in os.walk(music_dir):
        paths.extend(
            os.path.join(root, name) for name in files
            if name.lower().endswith(MUSIC_EXTENSIONS))
    return sorted(paths)


def read_tags(path: str) -> dict | None:
    """Reads the cached fields from a file, or None if it cannot be read."""
    try:
        tag = TinyTag.get(path)
    except (TinyTagException, OSError) as error:
        print(f"  unreadable: {path} ({error})")
        return None
    return {field: getattr(tag, field, None) for field in CACHED_FIELDS}


def ffprobe_duration(path: str) -> float | None:
    """Returns the duration ffprobe reports, or None if it is unavailable."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=30, check=False)
        return float(result.stdout.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def ffprobe_available() -> bool:
    """Returns True if FFmpeg's ffprobe can be run at all.

    Checked once up front: without it every probe returns None and the run would
    otherwise report "0 disagree", which reads as a clean bill of health.

    Note that the `ffprobe` package on PyPI is not this: it is a Python wrapper
    that shells out to the same binary, and installing it changes nothing here.
    """
    try:
        subprocess.run(["ffprobe", "-version"], capture_output=True, timeout=10, check=False)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def verify(cache: SongCache, paths: list) -> None:
    """Cross-checks cached durations against ffprobe.

    TinyTag falls back to estimating duration from file size and bitrate when a
    VBR header is missing or unparsable, which can be badly wrong. Under-reported
    durations matter most: they make timed blocks over-run and cause competition
    rounds to pass over songs that were in fact long enough.
    """
    if not paths:
        print("\nNothing to verify.")
        return

    if not ffprobe_available():
        print("\nffprobe (part of FFmpeg) was not found on PATH; skipping verification.")
        print("  Install it with:  winget install Gyan.FFmpeg    (Windows)")
        print("                    sudo apt install ffmpeg       (Debian/Ubuntu)")
        print("  The cache itself does not need it; only --verify does.")
        return

    print("\nVerifying cached durations against ffprobe...")
    checked = wrong = 0
    unreadable = []
    for path in paths:
        entry = cache.get(path)
        if entry is None:
            continue
        cached = usable_duration(entry.get("duration"))
        if cached is None:
            # No usable duration usually means the file is not decodable audio.
            # The player skips these, but they are worth knowing about after a
            # library rebuild, since they are silently missing from practices.
            unreadable.append(path)
            continue
        real = ffprobe_duration(path)
        if real is None:
            continue
        checked += 1
        if abs(cached - real) > max(2.0, 0.02 * real):
            wrong += 1
            direction = "long" if cached > real else "SHORT"
            print(f"  too {direction}: cached {cached / 60:6.2f}m  real {real / 60:6.2f}m  "
                  f"{os.path.relpath(path)}")
    print(f"  {checked} checked, {wrong} disagree")
    if unreadable:
        print(f"\n  {len(unreadable)} file(s) have no readable duration and will be "
              "skipped by the player:")
        for path in unreadable[:10]:
            print(f"    {os.path.relpath(path)}")
        if len(unreadable) > 10:
            print(f"    ...and {len(unreadable) - 10} more")
    if wrong:
        print("  A lossless remux usually fixes these: "
              "ffmpeg -i in.mp3 -c copy out.mp3")


# The player's own values, repeated here so this script does not have to import
# music_player and with it the whole of Kivy. A test asserts they still agree.
MIN_SONG_LENGTH_SECONDS = 90
DEFAULT_MAX_PLAYTIME = 210
FADE_SECONDS = 10

# Shorter than any real dance track, including the announcements and cues. A
# file reporting less than this is damaged rather than short: TinyTag will
# sometimes read a fraction of a second out of a file that is not audio at all.
MIN_PLAUSIBLE_SECONDS = 5

# Longer than any conceivable dance track, mixer or announcement. A cached value
# above this says the cache is corrupt, not that the song is long.
MAX_PLAUSIBLE_SECONDS = 24 * 60 * 60


def load_practice_types() -> dict:
    """Returns the validated practice types the player would offer."""
    types = {}
    for path in (app_paths.app_path("builtin_practice_types.json"),
                 app_paths.user_path("custom_practice_types.json",
                                     seed_from_app_dir=False)):
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as handle:
                raw = json.load(handle)
        except (OSError, json.JSONDecodeError) as error:
            print(f"  could not read {os.path.basename(path)}: {error}")
            continue
        if not isinstance(raw, dict):
            continue
        for name, definition in raw.items():
            if name.startswith("__COMMENT__"):
                continue
            clean = practice_type_rules.normalize_practice_type(
                name, definition, warn=lambda _message: None)
            if clean is not None:
                types[name] = clean
    return types


def songs_wanted(practice_type: dict, dance: str, lengths: list) -> int:
    """How many songs of `dance` one practice type asks for.

    Args:
        practice_type: A validated definition.
        dance: The dance in question.
        lengths: Known playing times for that dance, used to estimate how many
            songs a timed block needs.

    Returns:
        The number of songs needed, 0 if the practice type does not use it.
    """
    if segments := practice_type.get("segments"):
        return sum(segment.get("count", 1) for segment in segments
                   if dance in segment.get("round", []))

    if dance not in practice_type.get("dances", []):
        return 0

    if minutes := practice_type.get("dance_minutes", {}).get(dance):
        cap = practice_type.get("dance_max_playtimes", {}).get(
            dance, DEFAULT_MAX_PLAYTIME)
        typical = statistics.median(
            min(length, cap + FADE_SECONDS) for length in lengths) if lengths else 0
        return math.ceil(minutes * 60 / typical) if typical else 0

    # Count-based. dance_adjustments only ever reduces the count, so the
    # unadjusted figure is the safe upper bound.
    return practice_type.get("num_selections", 0)


def usable_duration(value):
    """Returns `value` as a positive finite float, or None if it is not one.

    Cache entries are validated for shape but not for the type of each field, so
    a hand-edited or corrupted cache can hold "duration": "long". Comparing that
    to a number raises, which would take the audit down.

    Rejects anything that is not a plausible length: the wrong type, a boolean,
    a non-finite value, an integer too large to be a float, and anything longer
    than a day.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        duration = float(value)
    except OverflowError:
        # A JSON integer too large to be a float. math.isfinite would raise on
        # it just as readily, so the conversion has to be guarded rather than
        # the check.
        return None
    if not math.isfinite(duration) or duration <= 0:
        return None
    if duration > MAX_PLAUSIBLE_SECONDS:
        return None
    return duration


def check_library(music_dir: str, cache: SongCache, paths: list,
                  unreadable_paths: list = None) -> int:
    """Reports anything about the music library the player would stumble over.

    Worth running after the library has been rebuilt or reorganised: every
    problem here makes a dance quietly smaller or absent rather than failing
    loudly, so none of it is obvious at a practice.

    Args:
        music_dir: The root music directory.
        cache: A cache already populated for `paths`.
        paths: Every music file found.
        unreadable_paths: Files whose tags could not be read at all. They have no
            cache entry, so without this the audit would skip exactly the files
            the player cannot play.

    Returns:
        The number of problems found, warnings excluded.
    """
    print("\nChecking the music library...")
    problems = 0

    practice_types = load_practice_types()
    referenced = {dance for definition in practice_types.values()
                  for dance in definition.get("dances", [])}
    for definition in practice_types.values():
        for segment in definition.get("segments", []):
            referenced.update(segment.get("round", []))

    folders = {name for name in os.listdir(music_dir)
               if os.path.isdir(os.path.join(music_dir, name))}
    by_lower = {}
    for name in folders:
        by_lower.setdefault(name.casefold(), []).append(name)

    # 1. Dances a practice type uses but the library does not have. The player
    # matches folder names without regard to case, so a different spelling is
    # only untidy -- but two folders differing only in case are a real problem:
    # on Linux both exist and the player can only pick one.
    # The folder the player would actually read for each dance: an exact match
    # if there is one, otherwise the first by name, which is what the player's
    # _entry_ignoring_case settles on. Worked out once so that the diagnostics
    # and the song counts below cannot disagree about it.
    chosen_folder = {}
    missing, miscased, ambiguous = [], [], []
    for dance in sorted(referenced):
        matches = sorted(by_lower.get(dance.casefold(), []))
        if not matches:
            missing.append(dance)
            continue
        chosen_folder[dance] = dance if dance in matches else matches[0]
        if len(matches) > 1:
            ambiguous.append((dance, matches))
        elif matches[0] != dance:
            miscased.append((dance, matches[0]))

    for dance, matches in ambiguous:
        problems += 1
        others = [name for name in matches if name != chosen_folder[dance]]
        print(f"  AMBIGUOUS: {len(matches)} folders named '{dance}' differing only "
              f"in case ({', '.join(matches)}). The player uses "
              f"'{chosen_folder[dance]}'; the music in {', '.join(others)} is "
              "invisible.")

    if missing:
        problems += len(missing)
        shown = ", ".join(missing[:8]) + ("..." if len(missing) > 8 else "")
        print(f"  MISSING: {len(missing)} dance(s) have no folder and are silently "
              f"left out of any practice type using them: {shown}")

    for dance, actual in miscased:
        print(f"  note: practice types use '{dance}' but the folder is '{actual}'. "
              "The player matches either way; renaming one to match the other "
              "just keeps things tidy.")

    # 2. Folders nothing uses. Not a problem, but easy to lose track of.
    referenced_lower = {dance.casefold() for dance in referenced}
    accounted = {name for name in folders if name.casefold() in referenced_lower}
    if unused := sorted(folders - accounted):
        print(f"  note: {len(unused)} folder(s) no practice type uses: "
              f"{', '.join(unused[:8])}{'...' if len(unused) > 8 else ''}")

    # 3. Files the player will refuse to play, and files it will pass over.
    unreadable, damaged, too_short, mojibake = [], [], [], []
    lengths_by_dance = {}
    known_unreadable = set(unreadable_paths or ())
    for path in paths:
        # The dance is the first folder below the music directory, not the
        # folder the file happens to sit in: a song may be filed under an album,
        # and the player collects those recursively.
        relative = os.path.relpath(path, music_dir).split(os.sep)
        # Keyed by the folder as it exists, so that two folders differing only
        # in case are counted separately -- the player only ever reads one.
        dance = relative[0] if len(relative) > 1 else None

        entry = cache.get(path)
        duration = usable_duration(entry.get("duration")) if entry else None

        if path in known_unreadable or duration is None:
            # No entry means read_tags raised; no usable duration means the tag
            # was read but says nothing useful. The player skips both.
            unreadable.append(path)
            continue
        if duration < MIN_PLAUSIBLE_SECONDS:
            # Read successfully, but no real track is this short. The player
            # would still try to play it, which is why it is worth reporting.
            damaged.append((path, duration))
            continue
        if dance is None:
            continue
        lengths_by_dance.setdefault(dance, []).append(duration)
        if duration < MIN_SONG_LENGTH_SECONDS:
            too_short.append((path, duration))
        if (title := entry.get("title")) and (fixed := repaired_text(title)):
            mojibake.append((title, fixed))

    if unreadable:
        problems += len(unreadable)
        print(f"  UNREADABLE: {len(unreadable)} file(s) have no usable duration, "
              "so the player skips them:")
        for path in unreadable[:10]:
            print(f"      {os.path.relpath(path, music_dir)}")

    if damaged:
        problems += len(damaged)
        print(f"  SUSPECT: {len(damaged)} file(s) report under "
              f"{MIN_PLAUSIBLE_SECONDS}s, which no real track does. The audit "
              "treats them as damaged; the player would still try to play them:")
        for path, duration in sorted(damaged, key=lambda item: item[1])[:10]:
            print(f"      {duration:5.1f}s  {os.path.relpath(path, music_dir)}")

    if too_short:
        print(f"  note: {len(too_short)} file(s) under "
              f"{MIN_SONG_LENGTH_SECONDS}s, which practice types that use a fixed "
              "song count will pass over:")
        for path, duration in sorted(too_short, key=lambda item: item[1])[:10]:
            print(f"      {duration:5.0f}s  {os.path.relpath(path, music_dir)}")

    if mojibake:
        print(f"  note: {len(mojibake)} title(s) look double-encoded, and appear "
              "that way in the playlist:")
        for title, fixed in mojibake[:10]:
            print(f"      {title}   ->   {fixed}")

    # 4. Dances with too few songs for the practice types that use them.
    for dance in sorted(chosen_folder):
        lengths = lengths_by_dance.get(chosen_folder[dance], [])
        available = len(lengths)
        for name, definition in practice_types.items():
            wanted = songs_wanted(definition, dance, lengths)
            if wanted > available:
                problems += 1
                print(f"  TOO FEW: '{name}' needs about {wanted} {dance} songs but "
                      f"the folder has {available}; the same songs will repeat.")
                break

    print(f"\n  {len(paths)} files, {len(folders)} dance folders, "
          f"{len(practice_types)} practice types, {problems} problem(s).")
    return problems


def repaired_text(text: str):
    """Returns `text` decoded properly if it looks double-encoded, else None.

    UTF-8 bytes stored in a tag declared as Latin-1 come back as "Chá"
    rather than "Chá". Such a string survives a round trip back through
    Latin-1, which is what identifies it.
    """
    if text.isascii():
        return None
    try:
        fixed = text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return None
    return fixed if fixed != text else None

def main() -> int:

    """Entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--music-dir", help="Music directory (default: from music.ini)")
    parser.add_argument("--cache", default=app_paths.user_path(DEFAULT_CACHE_FILE),
                        help="Cache file to maintain")
    parser.add_argument("--prune", action="store_true",
                        help="Remove entries for files that no longer exist")
    parser.add_argument("--rebuild", action="store_true",
                        help="Re-read every file instead of trusting the cache")
    parser.add_argument("--verify", action="store_true",
                        help="Cross-check cached durations against ffprobe")
    parser.add_argument("--check-library", action="store_true",
                        help="Report problems the player would stumble over: "
                             "missing or wrongly-cased dance folders, unplayable "
                             "files, and folders with too few songs")
    args = parser.parse_args()

    music_dir = args.music_dir or read_music_dir_from_config()
    if not music_dir or not os.path.isdir(music_dir):
        print(f"Music directory not found: {music_dir or '(not set in music.ini)'}")
        print("Pass one with --music-dir.")
        return 1

    print(f"Music directory: {music_dir}")
    print(f"Cache file:      {args.cache}")

    started = time.perf_counter()
    cache = SongCache(args.cache)
    if args.rebuild:
        print(f"Rebuilding: discarding {len(cache)} existing entries.")
        cache.clear()

    library_paths = collect_music_files(music_dir)
    paths = list(library_paths)
    # The announcements and round cues are read on every playlist too, so they are
    # worth caching even though they do not live in the music directory. They are
    # kept separate from library_paths: they are not dance music and must not be
    # audited as if they were.
    for extra in ("announce", "cues"):
        extra_dir = os.path.join(REPO_DIR, extra)
        if os.path.isdir(extra_dir):
            paths.extend(collect_music_files(extra_dir))
    print(f"Found {len(paths)} music files.\n")

    added = refreshed = unchanged = 0
    unreadable_paths = []
    for path in paths:
        before_stale = cache.stale
        if cache.get(path) is not None:
            unchanged += 1
            continue
        was_stale = cache.stale > before_stale
        if (fields := read_tags(path)) is None:
            unreadable_paths.append(path)
            continue
        cache.put(path, fields)
        if was_stale:
            refreshed += 1
        else:
            added += 1

    pruned = cache.prune(paths) if args.prune else 0

    cache.save()
    elapsed = time.perf_counter() - started

    print(f"  added:     {added}")
    print(f"  refreshed: {refreshed}   (file changed since it was cached)")
    print(f"  unchanged: {unchanged}")
    if unreadable_paths:
        print(f"  unreadable:{len(unreadable_paths)}")
    if args.prune:
        print(f"  pruned:    {pruned}   (file no longer exists)")
    elif len(cache) > len(paths):
        print(f"  {len(cache) - len(paths)} entries are for files outside this "
              "directory or no longer present; --prune removes the stale ones.")
    print(f"\n{len(cache)} entries in {elapsed:.1f}s")

    if args.verify:
        verify(cache, paths)

    if args.check_library:
        return 2 if check_library(
            music_dir, cache, library_paths, unreadable_paths) else 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
