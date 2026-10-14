"""Regression checks for the local and copied libraries used by both previews."""

import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave

import practice_cache
from song_cache import CACHE_VERSION, SongCache
from tests.support import filesystem_is_case_sensitive
from utils import simulate_practice, simulate_timed_practice


class TestLocalDurations(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.library = Path(self.tmp.name) / "library"
        self.song = self.library / "Waltz" / "song.wav"
        self.song.parent.mkdir(parents=True)
        self.write_wav(90)
        file_stat = self.song.stat()
        self.cache = {str(self.song): {
            "size": file_stat.st_size, "mtime": file_stat.st_mtime, "duration": 90,
            "title": None, "artist": None, "album": None, "genre": None}}
        self.cache_path = Path(self.tmp.name) / "cache.json"
        self.cache_path.write_text(json.dumps({"version": CACHE_VERSION, "songs": self.cache}))

    def write_wav(self, seconds):
        with wave.open(str(self.song), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(1)
            handle.setframerate(8000)
            handle.writeframes(b"\x80" * (8000 * seconds))

    def test_both_previews_refresh_changed_tracks_without_writing_the_cache(self):
        self.write_wav(180)
        before = self.cache_path.read_bytes()
        # The actual player invalidates this entry before reading the new tags.
        self.assertIsNone(SongCache(str(self.cache_path)).get(str(self.song)))
        with contextlib.redirect_stderr(io.StringIO()) as warnings:
            general = simulate_practice.load_pools(self.cache, ["Waltz"], self.library)
            timed = simulate_timed_practice.load_pools(self.cache_path, ["Waltz"], str(self.library))
        self.assertEqual(general, timed)
        self.assertEqual(general["Waltz"][0].duration, 180)
        self.assertIn("re-read 1", warnings.getvalue())
        self.assertEqual(self.cache_path.read_bytes(), before)
        self.assertEqual(self.cache[str(self.song)]["duration"], 90)

    def test_a_changed_unreadable_file_does_not_keep_its_old_duration(self):
        self.song.write_bytes(b"no longer audio")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(practice_cache.load_pools(self.cache, ["Waltz"], self.library), {"Waltz": []})

    def test_current_entries_do_not_need_tinytag(self):
        with patch.dict(sys.modules, {"tinytag": None}):
            pool = practice_cache.load_pools(self.cache, ["Waltz"], self.library)["Waltz"]
        self.assertEqual(pool[0].duration, 90)

    def test_both_previews_find_uncached_songs_in_the_players_folder(self):
        from music_player import MusicPlayer
        uncached = self.song.parent / "album" / "new.WAV"
        uncached.parent.mkdir()
        uncached.write_bytes(self.song.read_bytes())
        # The shared extension filter must ignore non-audio files even if their
        # contents happen to be valid audio.
        (uncached.parent / "notes.txt").write_bytes(self.song.read_bytes())
        before = self.cache_path.read_bytes()
        with contextlib.redirect_stderr(io.StringIO()) as warnings:
            general = simulate_practice.load_pools(self.cache, ["Waltz"], self.library)
            timed = simulate_timed_practice.load_pools(self.cache_path, ["Waltz"], str(self.library))
        player = MusicPlayer.__new__(MusicPlayer)
        player._dance_pools = {}
        scanned = player._collect_music_files(str(self.library), "Waltz")
        self.assertEqual(general, timed)
        self.assertEqual([song.path for song in general["Waltz"]], sorted(scanned))
        self.assertEqual(len(general["Waltz"]), 2)
        self.assertIn("read 1 uncached songs", warnings.getvalue())
        self.assertEqual(self.cache_path.read_bytes(), before)
        self.assertNotIn(str(uncached), self.cache)

    def test_uncached_song_without_tinytag_fails_with_an_actionable_message(self):
        uncached = self.song.parent / "new.wav"
        uncached.write_bytes(self.song.read_bytes())
        with patch.dict(sys.modules, {"tinytag": None}):
            with self.assertRaisesRegex(ValueError, "uncached.*TinyTag is unavailable.*kivy_venv"):
                practice_cache.load_pools(self.cache, ["Waltz"], self.library)

    def test_aliases_read_an_uncached_song_once(self):
        from tinytag import TinyTag
        uncached = self.song.parent / "new.wav"
        uncached.write_bytes(self.song.read_bytes())
        with patch("tinytag.TinyTag.get", wraps=TinyTag.get) as reader, \
                contextlib.redirect_stderr(io.StringIO()) as warnings:
            pools = practice_cache.load_pools(self.cache, ["Waltz", "waltz"], self.library)
        self.assertEqual([len(pool) for pool in pools.values()], [2, 2])
        reader.assert_called_once_with(str(uncached))
        self.assertIn("read 1 uncached songs", warnings.getvalue())

    def test_deleted_files_are_skipped_without_a_library_setting(self):
        self.song.unlink()
        with contextlib.redirect_stderr(io.StringIO()) as warnings:
            self.assertEqual(practice_cache.load_pools(self.cache, ["Waltz"]), {"Waltz": []})
        self.assertIn("ignored 1 cache entries for files no longer", warnings.getvalue())

    def test_current_entries_with_no_duration_are_skipped_without_tinytag(self):
        self.cache[str(self.song)]["duration"] = None
        with patch.dict(sys.modules, {"tinytag": None}), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(practice_cache.load_pools(self.cache, ["Waltz"], self.library), {"Waltz": []})

    def test_stale_entries_without_tinytag_fail_with_an_actionable_message(self):
        self.write_wav(180)
        with patch.dict(sys.modules, {"tinytag": None}):
            with self.assertRaisesRegex(ValueError, "TinyTag is unavailable.*kivy_venv"):
                practice_cache.load_pools(self.cache, ["Waltz"], self.library)

    def test_stale_local_tracks_are_also_refreshed_without_a_library_setting(self):
        self.write_wav(180)
        with contextlib.redirect_stderr(io.StringIO()):
            pool = practice_cache.load_pools(self.cache, ["Waltz"])["Waltz"]
        self.assertEqual(pool[0].duration, 180)

    def test_each_dance_alias_keeps_its_own_pool_and_block(self):
        dances = ["Waltz", "waltz"]
        pools = practice_cache.load_pools(self.cache, dances, self.library)
        self.assertEqual([len(pools[dance]) for dance in dances], [1, 1])
        definition = simulate_practice.load_practice("Aliases", {"Aliases": {
            "dances": dances, "num_selections": 1, "randomize_playlist": False,
            "dance_intros": {"default": "none"}}})
        blocks = simulate_practice.generate(definition, pools, {dance: 0 for dance in dances}, {}, 210, 1)
        self.assertEqual([len(block.songs) for block in blocks], [1, 1])
        self.assertEqual(sum(block.seconds for block in blocks), 180)
        # Root-free previews retain both names too.
        self.assertEqual([len(pool) for pool in practice_cache.load_pools(self.cache, dances).values()], [1, 1])

    def test_distinct_case_sensitive_folders_keep_their_own_tracks(self):
        if not filesystem_is_case_sensitive(self.library):
            self.skipTest("The filesystem cannot hold both case variants")
        other = self.library / "waltz" / "other.wav"
        other.parent.mkdir()
        other.write_bytes(self.song.read_bytes())
        file_stat = other.stat()
        self.cache[str(other)] = dict(self.cache[str(self.song)], size=file_stat.st_size, mtime=file_stat.st_mtime)
        pools = practice_cache.load_pools(self.cache, ["Waltz", "waltz"], self.library)
        self.assertEqual([song.path for song in pools["Waltz"]], [str(self.song)])
        self.assertEqual([song.path for song in pools["waltz"]], [str(other)])

    def test_copied_caches_preserve_aliases_without_requiring_local_metadata(self):
        unavailable_library = Path(self.tmp.name) / "unavailable"
        path = str(unavailable_library / "Waltz" / "song.mp3")
        with patch.dict(sys.modules, {"tinytag": None}):
            pools = practice_cache.load_pools({path: {"duration": 100}}, ["Waltz", "waltz"],
                                             unavailable_library)
        self.assertEqual([pool[0].duration for pool in pools.values()], [100, 100])


class TestSettings(unittest.TestCase):
    def test_an_invalid_cap_keeps_the_music_folder_without_repairing_the_file(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "music.ini"
            config.write_text("[user]\nsong_max_playtime = broken\nmusic_dir = /chosen/library\n")
            before = config.read_bytes()
            with contextlib.redirect_stderr(io.StringIO()) as warnings:
                self.assertEqual(practice_cache.read_player_settings(config), (210, "/chosen/library"))
            self.assertIn("retaining music_dir", warnings.getvalue())
            self.assertEqual(config.read_bytes(), before)

    def test_timed_preview_bad_cap_note_uses_the_explicit_cli_cap(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "music.ini"
            config.write_text("[user]\nsong_max_playtime = broken\nmusic_dir = /chosen/library\n")
            practice = simulate_timed_practice.PracticeType("Timed", {"Waltz": 5}, {}, 90)
            for cap in (180, 180.5):
                with self.subTest(cap=cap), \
                        patch.object(sys, "argv", ["simulate_timed_practice.py", "cache.json", "--compare",
                                                  "--default-cap", str(cap), "--runs", "1"]), \
                        patch.object(simulate_timed_practice.app_paths, "user_path", return_value=str(config)), \
                        patch.object(simulate_timed_practice, "load_practice_type", return_value=practice), \
                        patch.object(simulate_timed_practice, "load_pools", return_value={"Waltz": []}) as pools, \
                        patch.object(simulate_timed_practice, "print_comparison") as comparison, \
                        contextlib.redirect_stderr(io.StringIO()) as warnings:
                    self.assertEqual(simulate_timed_practice.main(), 0)
                    self.assertIn(f"using {cap:g}s", warnings.getvalue())
                    self.assertNotIn("using 210s", warnings.getvalue())
                    pools.assert_called_once_with("cache.json", {"Waltz": 5}, "/chosen/library")
                    self.assertEqual(comparison.call_args.args[2].default_cap, cap)


if __name__ == "__main__":
    unittest.main()
