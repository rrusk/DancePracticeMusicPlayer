"""Tests for utils/build_song_cache.py.

The script only prewarms a cache the player maintains anyway, so a bug here
costs speed rather than correctness -- except for --prune, which deletes cache
entries, and --verify, which is the safety net for a rebuilt music library and
must not report a clean bill of health when it has checked nothing.

To run these tests:
    python -m pytest tests/test_build_song_cache.py
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "utils"))

# pylint: disable=wrong-import-position
import build_song_cache as script
from song_cache import SongCache


class ScriptTestCase(unittest.TestCase):
    """A temporary music library and cache."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.music = os.path.join(self.tmp, "music", "Waltz")
        os.makedirs(self.music)
        self.cache_path = os.path.join(self.tmp, "cache.json")
        self.songs = []
        for name in ("a.mp3", "b.ogg", "c.flac"):
            path = os.path.join(self.music, name)
            with open(path, "wb") as handle:
                handle.write(b"x" * 100)
            self.songs.append(path)
        with open(os.path.join(self.music, "notes.txt"), "w", encoding="utf-8") as handle:
            handle.write("not music")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_script(self, *args, duration=150.0):
        """Runs main() against the temporary library, with tags mocked."""
        tag = MagicMock(duration=duration, title="T", artist="A", album="B", genre="G")
        argv = ["build_song_cache.py", "--music-dir", os.path.join(self.tmp, "music"),
                "--cache", self.cache_path, *args]
        with patch.object(sys, "argv", argv), \
             patch.object(script, "REPO_DIR", self.tmp), \
             patch.object(script.TinyTag, "get", return_value=tag):
            return script.main()

    def cached(self):
        with open(self.cache_path, encoding="utf-8") as handle:
            return json.load(handle)["songs"]


class TestCollectingFiles(ScriptTestCase):
    """Which files are considered."""

    def test_only_music_extensions_are_collected(self):
        found = script.collect_music_files(os.path.join(self.tmp, "music"))
        self.assertEqual(len(found), 3)
        self.assertFalse([p for p in found if p.endswith(".txt")])

    def test_subfolders_are_searched(self):
        nested = os.path.join(self.music, "more")
        os.makedirs(nested)
        with open(os.path.join(nested, "d.mp3"), "wb") as handle:
            handle.write(b"x")
        self.assertEqual(len(script.collect_music_files(os.path.join(self.tmp, "music"))), 4)

    def test_an_empty_directory_yields_nothing(self):
        self.assertEqual(script.collect_music_files(os.path.join(self.tmp, "nothing")), [])


class TestConfigurationDiscovery(ScriptTestCase):
    """Finding the music directory without arguments."""

    def test_the_music_directory_is_read_from_the_ini(self):
        ini = os.path.join(self.tmp, "music.ini")
        with open(ini, "w", encoding="utf-8") as handle:
            handle.write("[user]\nmusic_dir = /somewhere/music\n")
        with patch.object(script.app_paths, "user_path", lambda name, **k: ini):
            self.assertEqual(script.read_music_dir_from_config(), "/somewhere/music")

    def test_a_missing_ini_yields_nothing(self):
        with patch.object(script.app_paths, "user_path",
                          lambda name, **k: os.path.join(self.tmp, "absent.ini")):
            self.assertEqual(script.read_music_dir_from_config(), "")

    def test_an_ini_without_the_setting_yields_nothing(self):
        ini = os.path.join(self.tmp, "music.ini")
        with open(ini, "w", encoding="utf-8") as handle:
            handle.write("[user]\nvolume = 0.7\n")
        with patch.object(script.app_paths, "user_path", lambda name, **k: ini):
            self.assertEqual(script.read_music_dir_from_config(), "")

    def test_a_corrupt_ini_yields_nothing(self):
        ini = os.path.join(self.tmp, "music.ini")
        with open(ini, "w", encoding="utf-8") as handle:
            handle.write("this is not an ini file\n[[[")
        with patch.object(script.app_paths, "user_path", lambda name, **k: ini):
            self.assertEqual(script.read_music_dir_from_config(), "")

    def test_a_missing_music_directory_is_reported_not_crashed(self):
        with patch.object(sys, "argv",
                          ["build_song_cache.py", "--music-dir", "/no/such/place"]):
            self.assertEqual(script.main(), 1)


class TestBuildingTheCache(ScriptTestCase):
    """Adding, refreshing and leaving entries alone."""

    def test_a_first_run_caches_every_song(self):
        self.assertEqual(self.run_script(), 0)
        self.assertEqual(len(self.cached()), 3)

    def test_a_second_run_changes_nothing(self):
        self.run_script()
        before = self.cached()
        self.run_script()
        self.assertEqual(self.cached(), before)

    def test_a_changed_file_is_re_read(self):
        self.run_script(duration=100.0)
        with open(self.songs[0], "wb") as handle:
            handle.write(b"y" * 500)                # different size
        self.run_script(duration=222.0)
        self.assertEqual(self.cached()[self.songs[0]]["duration"], 222.0)

    def test_rebuild_re_reads_everything(self):
        self.run_script(duration=100.0)
        self.run_script("--rebuild", duration=333.0)
        self.assertTrue(all(entry["duration"] == 333.0 for entry in self.cached().values()))

    def test_an_unreadable_file_is_skipped_without_stopping_the_run(self):
        tag = MagicMock(duration=150.0, title="T", artist="A", album="B", genre="G")
        calls = {"n": 0}

        def sometimes_fails(_path):
            calls["n"] += 1
            if calls["n"] == 1:
                raise script.TinyTagException("bad header")
            return tag

        argv = ["build_song_cache.py", "--music-dir", os.path.join(self.tmp, "music"),
                "--cache", self.cache_path]
        with patch.object(sys, "argv", argv), \
             patch.object(script, "REPO_DIR", self.tmp), \
             patch.object(script.TinyTag, "get", side_effect=sometimes_fails):
            self.assertEqual(script.main(), 0)
        self.assertEqual(len(self.cached()), 2)

    def test_announce_and_cue_folders_are_included(self):
        for extra in ("announce", "cues"):
            os.makedirs(os.path.join(self.tmp, extra))
            with open(os.path.join(self.tmp, extra, "x.ogg"), "wb") as handle:
                handle.write(b"x")
        self.run_script()
        self.assertEqual(len(self.cached()), 5)


class TestPruning(ScriptTestCase):
    """--prune deletes entries, so it must delete only the right ones."""

    def test_a_deleted_file_is_pruned(self):
        self.run_script()
        os.remove(self.songs[0])
        self.run_script("--prune")
        self.assertEqual(len(self.cached()), 2)
        self.assertNotIn(self.songs[0], self.cached())

    def test_without_prune_the_entry_survives(self):
        self.run_script()
        os.remove(self.songs[0])
        self.run_script()
        self.assertIn(self.songs[0], self.cached())

    def test_pruning_keeps_files_that_still_exist(self):
        self.run_script()
        self.run_script("--prune")
        self.assertEqual(len(self.cached()), 3)


class TestVerification(ScriptTestCase):
    """--verify is the safety net for a rebuilt library."""

    def test_nothing_to_verify_is_not_a_crash(self):
        with patch("builtins.print") as printed:
            script.verify(SongCache(self.cache_path), [])
        self.assertIn("Nothing to verify", " ".join(str(c) for c in printed.call_args_list))

    def test_a_missing_ffprobe_is_reported_rather_than_reporting_no_problems(self):
        with patch.object(script, "ffprobe_available", return_value=False), \
             patch("builtins.print") as printed:
            script.verify(SongCache(self.cache_path), self.songs)
        messages = " ".join(str(c) for c in printed.call_args_list)
        self.assertIn("ffprobe not found", messages)
        self.assertNotIn("disagree", messages)

    def test_a_duration_mismatch_is_reported(self):
        self.run_script(duration=2400.0)            # tag says 40 minutes
        with patch.object(script, "ffprobe_available", return_value=True), \
             patch.object(script, "ffprobe_duration", return_value=373.0), \
             patch("builtins.print") as printed:
            script.verify(SongCache(self.cache_path), self.songs)
        messages = " ".join(str(c) for c in printed.call_args_list)
        self.assertIn("too long", messages)
        self.assertIn("3 checked, 3 disagree", messages)

    def test_matching_durations_report_no_disagreement(self):
        self.run_script(duration=150.0)
        with patch.object(script, "ffprobe_available", return_value=True), \
             patch.object(script, "ffprobe_duration", return_value=150.4), \
             patch("builtins.print") as printed:
            script.verify(SongCache(self.cache_path), self.songs)
        self.assertIn("3 checked, 0 disagree",
                      " ".join(str(c) for c in printed.call_args_list))

    def test_files_with_no_duration_are_listed_as_unreadable(self):
        """These are the ones that would crash the player, so they must show up."""
        self.run_script(duration=None)
        with patch.object(script, "ffprobe_available", return_value=True), \
             patch.object(script, "ffprobe_duration", return_value=150.0), \
             patch("builtins.print") as printed:
            script.verify(SongCache(self.cache_path), self.songs)
        messages = " ".join(str(c) for c in printed.call_args_list)
        self.assertIn("no readable duration", messages)

    def test_an_unprobeable_file_is_skipped_not_counted(self):
        self.run_script(duration=150.0)
        with patch.object(script, "ffprobe_available", return_value=True), \
             patch.object(script, "ffprobe_duration", return_value=None), \
             patch("builtins.print") as printed:
            script.verify(SongCache(self.cache_path), self.songs)
        self.assertIn("0 checked", " ".join(str(c) for c in printed.call_args_list))

    def test_ffprobe_availability_survives_a_missing_binary(self):
        with patch.object(script.subprocess, "run", side_effect=OSError("not found")):
            self.assertFalse(script.ffprobe_available())

    def test_ffprobe_duration_survives_a_failure(self):
        with patch.object(script.subprocess, "run", side_effect=OSError("not found")):
            self.assertIsNone(script.ffprobe_duration("/any/file.mp3"))


if __name__ == "__main__":
    unittest.main()
