"""Read-only duration pools shared by the two practice preview utilities."""

import configparser
from dataclasses import dataclass
import json
import math
import ntpath
import os
import stat
import sys

import playlist_rules
from song_cache import current_entry


@dataclass
class Song:
    path: str
    duration: float


def usable_duration(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def normalized_path(path):
    return str(path).replace("\\", "/")


def library_root(path):
    """Expand native paths, preserving absolute Windows roots in transferred caches."""
    path = os.path.expanduser(str(path))
    if ntpath.splitdrive(path)[0]:
        return normalized_path(ntpath.normpath(path))
    return normalized_path(os.path.abspath(path))


def _dances_from_path(path, dances):
    """All requested dance names resolving to the first matching folder component."""
    components = normalized_path(path).split("/")[:-1]
    if any(part.casefold() in ("announce", "cues") for part in components):
        return []
    wanted = {}
    for dance in dict.fromkeys(dances):
        wanted.setdefault(dance.casefold(), []).append(dance)
    return next((wanted[part.casefold()] for part in components if part.casefold() in wanted), [])


def load_definitions(path, warn=lambda message: print(message, file=sys.stderr)):
    """The practice types in one JSON file, without comments.

    As in the player, a missing file is empty and an unreadable one is skipped
    with a warning, so a broken custom file still leaves the built-ins.
    """
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, ValueError) as error:
        warn(f"Note: cannot read {path}: {error}; ignoring it, as the player does.")
        return {}
    if not isinstance(raw, dict):
        warn(f"Note: {path} must contain a JSON object, not {type(raw).__name__}; "
             "ignoring it, as the player does.")
        return {}
    return {name: data for name, data in raw.items() if not name.startswith("__COMMENT__")}


def read_player_settings(config_path, *, default_cap=playlist_rules.DEFAULT_GLOBAL_CAP):
    """The song cap and music folder from music.ini, without creating or repairing it.

    Raises FileNotFoundError when the file is absent and configparser.Error for
    a malformed file. An invalid cap uses default_cap, preserving the
    independently configured music folder.
    """
    if not os.path.isfile(config_path):
        raise FileNotFoundError(f"Settings file does not exist: {config_path}")
    config = configparser.ConfigParser(interpolation=None)
    with open(config_path, encoding="utf-8") as handle:
        config.read_file(handle)
    try:
        raw_cap = config.get("user", "song_max_playtime", fallback=None)
        cap = default_cap if raw_cap is None else int(raw_cap)
    except ValueError:
        cap = default_cap
        print(f"Note: invalid song_max_playtime in {config_path}; using {cap:g}s "
              "and retaining music_dir.", file=sys.stderr)
    return cap, config.get("user", "music_dir", fallback="") or None


def local_duration(path, metadata, file_stat=None):
    """Trust a current cache entry, otherwise read local tags without writing the cache.

    A current entry with no duration and an unreadable file both return None,
    just as the player skips them. ImportError allows callers to distinguish a
    missing TinyTag dependency from an unreadable audio file.
    """
    if file_stat is None:
        try:
            file_stat = os.stat(path)
        except OSError:
            return None
    if current_entry(path, metadata, file_stat):
        return usable_duration(metadata["duration"])
    from tinytag import TinyTag, TinyTagException
    try:
        return usable_duration(TinyTag.get(path).duration)
    except (TinyTagException, OSError, ValueError):
        return None


def load_cache(path):
    with open(path, encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict) or not isinstance(raw.get("songs"), dict):
        raise ValueError("Cache must contain a top-level 'songs' object.")
    return raw["songs"]


def _chosen_folders(root, dances, cached_folders, on_disk):
    """The one folder per dance the player reads: the exact name, else the first ignoring case."""
    chosen = {}
    for dance in dances:
        if on_disk:
            found = playlist_rules.entry_ignoring_case(root, dance, want_dir=True)
            chosen[dance] = os.path.basename(found) if found else None
        else:
            matches = sorted(name for name in cached_folders if name.casefold() == dance.casefold())
            chosen[dance] = dance if dance in matches else (matches[0] if matches else None)
    return chosen


def load_pools(cache, dances, music_dir=None):
    """Current durations for the songs the player would find for each dance.

    With a library root, each dance reads the one folder directly below it that
    the player would choose. When that root exists on this computer, folders are
    chosen from disk, new songs are discovered, deleted files are left out, and
    uncached or changed durations are read without writing the cache; a root from
    another computer is judged from the cache's own paths, and a Windows root
    ignores case as Windows does. Without a root, any path component naming a
    dance counts, ignoring case, but missing local files are excluded. A copied
    cache for an unavailable library must name that root explicitly.
    """
    pools = {dance: [] for dance in dances}
    root = library_root(music_dir).rstrip("/") + "/" if music_dir else None
    windows_root = bool(root and ntpath.splitdrive(root)[0])
    root_case = ntpath.normcase if windows_root else os.path.normcase
    on_disk = bool(root) and os.path.isdir(root)
    skipped = missing = refreshed = uncached = 0
    entries = []
    for path, metadata in cache.items():
        if not isinstance(path, str) or not isinstance(metadata, dict):
            skipped += 1
            continue
        folder = None
        if root:
            normalized = normalized_path(path)
            if not root_case(normalized).startswith(root_case(root)):
                continue
            parts = normalized[len(root):].split("/")
            if len(parts) < 2:
                continue
            folder = parts[0]
        entries.append((path, folder, metadata))

    if root:
        chosen = _chosen_folders(root, pools, {folder for _, folder, _ in entries}, on_disk)
        compare = str.casefold if windows_root else str
        by_folder = {}
        for dance, folder in chosen.items():
            if folder:
                by_folder.setdefault(compare(folder), []).append(dance)
        if on_disk:
            # Scan each chosen folder once, including album subdirectories. The
            # same scan and extension filter are used by the player and builder.
            seen_paths = {os.path.normcase(os.path.normpath(path)) for path, _, _ in entries}
            folders = {compare(folder): folder for folder in chosen.values() if folder}
            for folder in folders.values():
                native_folder = os.path.normpath(os.path.join(root, folder))
                for path in playlist_rules.collect_music_files(native_folder):
                    normalized = os.path.normcase(os.path.normpath(path))
                    if normalized not in seen_paths:
                        entries.append((path, folder, cache.get(path, {})))
                        seen_paths.add(normalized)

    for path, folder, metadata in entries:
        if root:
            matching_dances = by_folder.get(compare(folder), [])
        else:
            matching_dances = _dances_from_path(path, pools)
        if not matching_dances:
            continue
        if on_disk or not root:
            try:
                file_stat = os.stat(path)
            except OSError:
                missing += 1
                continue
            if not stat.S_ISREG(file_stat.st_mode):
                missing += 1
                continue
            needs_refresh = not current_entry(path, metadata, file_stat)
            try:
                duration = local_duration(path, metadata, file_stat)
            except ImportError as error:
                raise ValueError(
                    f"Cannot read an uncached or stale duration for {path}: TinyTag is unavailable. "
                    "Run with the project's kivy_venv Python or rebuild the song cache first."
                ) from error
            if needs_refresh and duration is not None:
                if path not in cache:
                    uncached += 1
                else:
                    refreshed += 1
        else:
            duration = usable_duration(metadata.get("duration"))
        if duration is None:
            skipped += 1
            continue
        for dance in matching_dances:
            pools[dance].append(Song(path, duration))
    for pool in pools.values():
        pool.sort(key=lambda song: song.path)
    if skipped:
        print(f"Note: ignored {skipped} malformed/unusable cache entries.", file=sys.stderr)
    if missing:
        print(f"Note: ignored {missing} cache entries for files no longer in the library.",
              file=sys.stderr)
    if refreshed:
        print(f"Note: re-read {refreshed} stale/unusable cached durations without writing the cache.",
              file=sys.stderr)
    if uncached:
        print(f"Note: read {uncached} uncached songs without writing the cache.", file=sys.stderr)
    return pools
