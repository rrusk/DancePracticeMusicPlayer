# song_cache.py
"""A small on-disk cache of song metadata for the Dance Practice Music Player.

Reading tags with TinyTag is cheap on a fast machine and not cheap at all on the
older laptops used at practices, where every "New Playlist" re-reads the header of
every song it considers. This caches what `TinyTag.get` returns, keyed by absolute
path, so the cost is paid once per file rather than once per playlist.

The cache is always safe to delete: a miss simply means the file is read and the
entry rebuilt. It is also self-maintaining -- adding songs needs no action, since
the first playlist that considers them populates their entries.

Entries are validated against the file's size and modification time, so re-tagged
files (`utils/update_metadata.py`, `utils/batch_update_albums.sh`) are picked up
automatically. Entries for deleted files are harmless and are only removed by
`utils/build_song_cache.py --prune`, which is the only caller that sees the whole
library and can tell a deleted file from one it simply did not visit.
"""
import json
import os
import threading

CACHE_VERSION = 1
DEFAULT_CACHE_FILE = "song_metadata_cache.json"

# Tag fields worth caching. These are exactly what _create_song_info needs, so a
# hit avoids opening the file at all rather than saving only part of the work.
CACHED_FIELDS = ("duration", "title", "artist", "album", "genre")


class SongCache:
    """A path-keyed cache of song metadata, persisted as JSON.

    Attributes:
        hits (int): Entries served from the cache.
        misses (int): Files not in the cache at all.
        stale (int): Entries rejected because the file changed on disk.
    """

    def __init__(self, path: str):
        """Loads the cache from `path`, tolerating a missing or corrupt file."""
        self.path = path
        self._songs: dict = {}
        self._dirty = False
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0
        self.stale = 0
        self._load()

    def _load(self) -> None:
        """Reads the cache file. A corrupt cache is treated as an empty one."""
        if not os.path.isfile(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError) as error:
            # Worst case is one slow playlist while the cache is rebuilt.
            print(f"Song cache unreadable ({error}); starting a fresh one.")
            return

        if not isinstance(data, dict) or data.get("version") != CACHE_VERSION:
            print("Song cache is from a different version; starting a fresh one.")
            return

        songs = data.get("songs")
        if not isinstance(songs, dict):
            return

        # Each entry is checked too, not just the outer shape. An entry of the
        # wrong type would raise on every lookup, and because the cache survives
        # restarts that would break playlist generation until it was deleted --
        # which contradicts the cache being safe to keep around.
        self._songs = {path: entry for path, entry in songs.items()
                       if self._entry_is_usable(path, entry)}
        if len(self._songs) != len(songs):
            print(f"Discarded {len(songs) - len(self._songs)} malformed song cache "
                  "entries; they will be re-read.")
            self._dirty = True

    @staticmethod
    def _entry_is_usable(path, entry) -> bool:
        """Returns True if a cache entry has the shape lookups depend on."""
        return (
            isinstance(path, str)
            and isinstance(entry, dict)
            and isinstance(entry.get("size"), int)
            and isinstance(entry.get("mtime"), (int, float))
            and not isinstance(entry.get("mtime"), bool)
        )

    def get(self, path: str) -> dict | None:
        """Returns cached metadata for `path`, or None if it must be read.

        A `stat` is one syscall against opening and parsing a tag header, so
        validating on every hit stays far cheaper than not caching at all.
        """
        try:
            stat = os.stat(path)
        except OSError:
            return None

        with self._lock:
            entry = self._songs.get(path)
            if entry is None:
                self.misses += 1
                return None
            if not self._entry_is_usable(path, entry):
                # Belt and braces: _load filters these out, but an entry could
                # also arrive from a cache written by a future version.
                del self._songs[path]
                self.misses += 1
                return None
            if (entry.get("size") != stat.st_size
                    or abs(entry.get("mtime", -1.0) - stat.st_mtime) > 0.001):
                self.stale += 1
                return None
            self.hits += 1
            return entry

    def put(self, path: str, fields: dict) -> None:
        """Stores metadata for `path` along with its current size and mtime."""
        try:
            stat = os.stat(path)
        except OSError:
            return

        entry = {"size": stat.st_size, "mtime": stat.st_mtime}
        entry.update({key: fields.get(key) for key in CACHED_FIELDS})
        with self._lock:
            self._songs[path] = entry
            self._dirty = True

    def prune(self, keep_paths) -> int:
        """Drops entries for files that no longer exist.

        Only safe for a caller that has walked the whole library; playlist
        generation sees a few folders and would delete entries it never visited.

        Args:
            keep_paths: Every path that should remain in the cache.

        Returns:
            How many entries were removed.
        """
        keep = set(keep_paths)
        with self._lock:
            removed = [path for path in self._songs if path not in keep]
            for path in removed:
                del self._songs[path]
            if removed:
                self._dirty = True
        return len(removed)

    def clear(self) -> None:
        """Empties the cache, for a full rebuild."""
        with self._lock:
            self._songs = {}
            self._dirty = True

    def save(self) -> bool:
        """Writes the cache if anything changed.

        Written to a temporary file and renamed, so a laptop closed mid-write
        cannot leave a truncated cache behind.

        Returns:
            True if a write happened.
        """
        with self._lock:
            if not self._dirty:
                return False
            payload = {"version": CACHE_VERSION, "songs": self._songs}
            temporary = f"{self.path}.tmp"
            try:
                with open(temporary, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle)
                os.replace(temporary, self.path)
            except OSError as error:
                print(f"Could not save song cache: {error}")
                return False
            self._dirty = False
            return True

    def stats(self) -> str:
        """A one-line summary of how the cache performed."""
        return (f"{self.hits} hits, {self.misses} misses, "
                f"{self.stale} stale, {len(self._songs)} entries")

    def __len__(self) -> int:
        return len(self._songs)
