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
    python utils/build_song_cache.py --music-dir /path/to/music

Without --music-dir the music directory is read from music.ini, so normally no
arguments are needed.
"""
import argparse
import configparser
import os
import subprocess
import sys
import time

# Import the player's modules regardless of where this is run from.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, REPO_DIR)

# pylint: disable=wrong-import-position
import app_paths
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
    """Returns True if ffprobe can be run at all.

    Checked once up front: without it every probe returns None and the run would
    otherwise report "0 disagree", which reads as a clean bill of health.
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
        print("\nffprobe not found; skipping verification.")
        return

    print("\nVerifying cached durations against ffprobe...")
    checked = wrong = 0
    unreadable = []
    for path in paths:
        entry = cache.get(path)
        if entry is None:
            continue
        if not entry.get("duration"):
            # No duration usually means the file is not decodable audio. The
            # player skips these, but they are worth knowing about after a
            # library rebuild, since they are silently missing from practices.
            unreadable.append(path)
            continue
        real = ffprobe_duration(path)
        if real is None:
            continue
        checked += 1
        cached = entry["duration"]
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

    paths = collect_music_files(music_dir)
    # The announcements and round cues are read on every playlist too, so they are
    # worth caching even though they do not live in the music directory.
    for extra in ("announce", "cues"):
        extra_dir = os.path.join(REPO_DIR, extra)
        if os.path.isdir(extra_dir):
            paths.extend(collect_music_files(extra_dir))
    print(f"Found {len(paths)} music files.\n")

    added = refreshed = unchanged = failed = 0
    for path in paths:
        before_stale = cache.stale
        if cache.get(path) is not None:
            unchanged += 1
            continue
        was_stale = cache.stale > before_stale
        if (fields := read_tags(path)) is None:
            failed += 1
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
    if failed:
        print(f"  unreadable:{failed}")
    if args.prune:
        print(f"  pruned:    {pruned}   (file no longer exists)")
    elif len(cache) > len(paths):
        print(f"  {len(cache) - len(paths)} entries are for files outside this "
              "directory or no longer present; --prune removes the stale ones.")
    print(f"\n{len(cache)} entries in {elapsed:.1f}s")

    if args.verify:
        verify(cache, paths)

    return 0


if __name__ == "__main__":
    sys.exit(main())
