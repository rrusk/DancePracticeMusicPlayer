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
from tests.support import filesystem_is_case_sensitive


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
        self.assertIn("ffprobe (part of FFmpeg) was not found", messages)
        self.assertIn("winget install", messages)   # says what to install, not just what is missing
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

    def test_verify_survives_a_malformed_cached_duration(self):
        """--verify does arithmetic on the same field the audit reads."""
        self.run_script()
        with open(self.cache_path, encoding="utf-8") as handle:
            data = json.load(handle)
        for entry in data["songs"].values():
            entry["duration"] = "long"
        with open(self.cache_path, "w", encoding="utf-8") as handle:
            json.dump(data, handle)

        with patch.object(script, "ffprobe_available", return_value=True), \
             patch.object(script, "ffprobe_duration", return_value=150.0), \
             patch("builtins.print") as printed:
            script.verify(SongCache(self.cache_path), self.songs)   # must not raise

        messages = " ".join(str(call) for call in printed.call_args_list)
        self.assertIn("no readable duration", messages)

    def test_ffprobe_availability_survives_a_missing_binary(self):
        with patch.object(script.subprocess, "run", side_effect=OSError("not found")):
            self.assertFalse(script.ffprobe_available())

    def test_ffprobe_duration_survives_a_failure(self):
        with patch.object(script.subprocess, "run", side_effect=OSError("not found")):
            self.assertIsNone(script.ffprobe_duration("/any/file.mp3"))


class TestCheckLibrary(ScriptTestCase):
    """The library audit, which is the thing to run after a library rebuild.

    Every problem it looks for makes a dance quietly smaller or absent rather
    than failing loudly, so none of it is noticeable at a practice.
    """

    PRACTICE_TYPES = {
        "Test Practice": {"dances": ["Waltz", "Tango"], "num_selections": 2},
        "Test Rounds": {
            "dances": ["Waltz"],
            "segments": [{"round": ["Waltz"], "count": 2, "clip_seconds": 90}],
        },
    }

    def setUp(self):
        super().setUp()
        os.rename(self.music, os.path.join(self.tmp, "music", "Waltz"))
        self.music = os.path.join(self.tmp, "music", "Waltz")

    def _check(self, practice_types=None, duration=150.0):
        """Builds the cache then runs the audit, returning (problems, output)."""
        with patch.object(script, "load_practice_types",
                          return_value=practice_types or self.PRACTICE_TYPES):
            self.run_script(duration=duration)
            cache = SongCache(self.cache_path)
            paths = script.collect_music_files(os.path.join(self.tmp, "music"))
            with patch("builtins.print") as printed:
                problems = script.check_library(
                    os.path.join(self.tmp, "music"), cache, paths)
        return problems, " ".join(str(call) for call in printed.call_args_list)

    def _check_through_main(self, *args):
        """Runs the whole script, so unreadable files reach the audit as they do
        in real use. Returns (exit code, output)."""
        argv = ["build_song_cache.py",
                "--music-dir", os.path.join(self.tmp, "music"),
                "--cache", self.cache_path, "--check-library", *args]
        with patch.object(sys, "argv", argv), \
             patch.object(script, "REPO_DIR", self.tmp), \
             patch.object(script, "load_practice_types",
                          return_value=self.PRACTICE_TYPES), \
             patch("builtins.print") as printed:
            code = script.main()
        return code, " ".join(str(call) for call in printed.call_args_list)

    def _add_dance(self, name, songs=3):
        folder = os.path.join(self.tmp, "music", name)
        os.makedirs(folder, exist_ok=True)
        for index in range(songs):
            with open(os.path.join(folder, f"{index}.mp3"), "wb") as handle:
                handle.write(b"x" * 100)
        return folder

    def test_a_wrongly_cased_folder_is_not_also_called_unused(self):
        self._add_dance("tango")
        _, output = self._check()
        self.assertNotIn("no practice type uses", output)

    def test_a_differently_cased_folder_is_only_a_note(self):
        """The player matches either way, so this is untidy rather than broken."""
        self._add_dance("tango")
        problems, output = self._check()
        self.assertIn("note: practice types use 'Tango'", output)
        self.assertEqual(problems, 0)

    def test_two_folders_differing_only_in_case_are_a_problem(self):
        """On Linux both exist and the player can only read one of them."""
        if not filesystem_is_case_sensitive(self.tmp):
            self.skipTest("this filesystem cannot hold two names differing only in case")
        self._add_dance("Tango")
        self._add_dance("tango")
        problems, output = self._check()
        self.assertIn("AMBIGUOUS", output)
        self.assertGreater(problems, 0)

    def test_the_ambiguous_message_names_the_folder_the_player_picks(self):
        """An exact match wins, so the message must not just say the first by name."""
        if not filesystem_is_case_sensitive(self.tmp):
            self.skipTest("this filesystem cannot hold two names differing only in case")
        self._add_dance("Tango")
        self._add_dance("tango")
        lower = {"P": {"dances": ["tango"], "num_selections": 1}}
        _, output = self._check(practice_types=lower)
        self.assertIn("The player uses 'tango'", output)
        self.assertNotIn("The player uses 'Tango'", output)

    def test_songs_are_counted_from_the_folder_the_player_would_read(self):
        """Not merged across case variants, which would overstate the count."""
        if not filesystem_is_case_sensitive(self.tmp):
            self.skipTest("this filesystem cannot hold two names differing only in case")
        self._add_dance("Tango", songs=1)
        self._add_dance("tango", songs=9)
        thin = {"P": {"dances": ["Tango"], "num_selections": 5}}
        _, output = self._check(practice_types=thin)
        self.assertIn("but the folder has 1", output)

    def test_a_missing_dance_is_reported(self):
        problems, output = self._check()          # no Tango folder at all
        self.assertIn("MISSING", output)
        self.assertGreater(problems, 0)

    def test_a_complete_library_reports_no_problems(self):
        self._add_dance("Tango")
        problems, output = self._check()
        self.assertEqual(problems, 0)
        self.assertNotIn("MISSING", output)
        self.assertNotIn("AMBIGUOUS", output)

    def test_an_unused_folder_is_noted_but_not_a_problem(self):
        self._add_dance("Tango")
        self._add_dance("Polka")
        problems, output = self._check()
        self.assertEqual(problems, 0)
        self.assertIn("no practice type uses", output)

    def test_a_file_with_no_duration_is_reported(self):
        self._add_dance("Tango")
        problems, output = self._check(duration=None)
        self.assertIn("UNREADABLE", output)
        self.assertGreater(problems, 0)

    def test_a_short_song_is_noted_but_not_a_problem(self):
        self._add_dance("Tango")
        problems, output = self._check(duration=60.0)
        self.assertIn("under", output)
        self.assertEqual(problems, 0)

    def test_a_thin_folder_is_reported(self):
        """Two songs cannot fill a round that wants two of each, twice over."""
        self._add_dance("Tango")
        thin = {"Big Practice": {"dances": ["Waltz"], "num_selections": 99}}
        problems, output = self._check(practice_types=thin)
        self.assertIn("TOO FEW", output)
        self.assertGreater(problems, 0)

    def test_a_song_in_an_album_folder_counts_towards_its_dance(self):
        """The player collects recursively, so the audit must too."""
        album = os.path.join(self.music, "Album A")
        os.makedirs(album)
        for index in range(4):
            with open(os.path.join(album, f"{index}.mp3"), "wb") as handle:
                handle.write(b"x" * 100)
        self._add_dance("Tango")

        problems, output = self._check()
        self.assertEqual(problems, 0)
        self.assertNotIn("TOO FEW", output)

    def test_nested_albums_do_not_look_like_dances(self):
        album = os.path.join(self.music, "Album A")
        os.makedirs(album)
        with open(os.path.join(album, "1.mp3"), "wb") as handle:
            handle.write(b"x" * 100)
        self._add_dance("Tango")

        _, output = self._check()
        self.assertNotIn("Album A", output)

    def test_a_file_that_cannot_be_read_at_all_is_a_problem(self):
        """read_tags raising leaves no cache entry, so the audit used to skip it."""
        self._add_dance("Tango")

        def fail_on_one(path):
            if path.endswith("a.mp3"):
                raise script.TinyTagException("bad header")
            return MagicMock(duration=150.0, title="T", artist="A", album="B", genre="G")

        with patch.object(script.TinyTag, "get", side_effect=fail_on_one):
            code, output = self._check_through_main()

        self.assertIn("UNREADABLE", output)
        self.assertEqual(code, 2, "an unplayable file must fail the audit")

    def test_an_implausibly_short_duration_counts_as_damaged(self):
        """TinyTag reads a fraction of a second out of files that are not audio."""
        self._add_dance("Tango")
        problems, output = self._check(duration=0.4)
        self.assertIn("SUSPECT", output)
        self.assertGreater(problems, 0)

    def test_the_two_kinds_of_bad_file_are_described_differently(self):
        """The player skips one and would try to play the other."""
        self._add_dance("Tango")
        _, no_duration = self._check(duration=None)
        # The files have not changed, so the cache would keep the first reading.
        os.remove(self.cache_path)
        _, too_short = self._check(duration=0.4)
        self.assertIn("the player skips them", no_duration)
        self.assertIn("would still try to play them", too_short)

    def test_a_malformed_cached_duration_does_not_crash_the_audit(self):
        """A hand-edited or corrupted cache can hold anything at all."""
        self._add_dance("Tango")
        for bad in ("long", {}, [], True, False, float("nan"), float("inf"), -5, 0,
                    10 ** 400, 10 ** 20):
            with self.subTest(duration=bad):
                self.run_script()
                with open(self.cache_path, encoding="utf-8") as handle:
                    data = json.load(handle)
                for entry in data["songs"].values():
                    entry["duration"] = bad
                with open(self.cache_path, "w", encoding="utf-8") as handle:
                    json.dump(data, handle)

                cache = SongCache(self.cache_path)
                paths = script.collect_music_files(os.path.join(self.tmp, "music"))
                with patch.object(script, "load_practice_types",
                                  return_value=self.PRACTICE_TYPES), \
                     patch("builtins.print") as printed:
                    problems = script.check_library(
                        os.path.join(self.tmp, "music"), cache, paths)

                output = " ".join(str(call) for call in printed.call_args_list)
                self.assertIn("UNREADABLE", output)
                self.assertGreater(problems, 0)

    def test_a_short_but_plausible_song_is_only_a_note(self):
        self._add_dance("Tango")
        problems, output = self._check(duration=60.0)
        self.assertIn("under", output)
        self.assertNotIn("UNREADABLE", output)
        self.assertEqual(problems, 0)

    def test_a_timed_block_estimates_how_many_songs_it_needs(self):
        """13 minutes of 2:30 songs is about six of them."""
        wanted = script.songs_wanted(
            {"dances": ["Waltz"], "dance_minutes": {"Waltz": 13}},
            "Waltz", [150.0] * 10)
        self.assertEqual(wanted, 6)

    def test_a_round_counts_every_appearance(self):
        wanted = script.songs_wanted(
            {"segments": [{"round": ["Waltz", "Tango"], "count": 2},
                          {"round": ["Waltz"], "count": 1}]},
            "Waltz", [150.0])
        self.assertEqual(wanted, 3)

    def test_a_dance_a_practice_type_does_not_use_needs_nothing(self):
        self.assertEqual(
            script.songs_wanted({"dances": ["Tango"], "num_selections": 4},
                                "Waltz", [150.0]), 0)


class TestUsableDuration(unittest.TestCase):
    """Only a positive finite number is a duration."""

    def test_real_durations_are_accepted(self):
        self.assertEqual(script.usable_duration(150), 150.0)
        self.assertEqual(script.usable_duration(150.5), 150.5)
        self.assertEqual(script.usable_duration(0.4), 0.4)

    def test_wrong_types_are_rejected(self):
        for value in ("long", "150", {}, [], None, object()):
            self.assertIsNone(script.usable_duration(value), value)

    def test_booleans_are_rejected(self):
        """bool is an int subclass, so True would otherwise be 1 second."""
        self.assertIsNone(script.usable_duration(True))
        self.assertIsNone(script.usable_duration(False))

    def test_non_finite_and_non_positive_are_rejected(self):
        for value in (float("nan"), float("inf"), float("-inf"), 0, 0.0, -1):
            self.assertIsNone(script.usable_duration(value), value)

    def test_an_integer_too_large_for_a_float_is_rejected(self):
        """float(10**400) raises before math.isfinite ever sees it."""
        self.assertIsNone(script.usable_duration(10 ** 400))
        self.assertIsNone(script.usable_duration(-(10 ** 400)))

    def test_an_implausibly_long_duration_is_rejected(self):
        """Longer than a day means the cache is corrupt, not the song long."""
        self.assertIsNone(script.usable_duration(script.MAX_PLAUSIBLE_SECONDS + 1))
        self.assertIsNone(script.usable_duration(10 ** 20))
        self.assertEqual(script.usable_duration(script.MAX_PLAUSIBLE_SECONDS),
                         float(script.MAX_PLAUSIBLE_SECONDS))

    def test_a_long_but_real_track_is_accepted(self):
        """The longest thing in a real library is a mixer or a bad VBR header."""
        self.assertEqual(script.usable_duration(2365.2), 2365.2)


class TestMojibakeDetection(unittest.TestCase):
    """Tags holding UTF-8 bytes declared as Latin-1 show up in the playlist."""

    def test_a_double_encoded_title_is_detected_and_repaired(self):
        self.assertEqual(script.repaired_text("Mi BombÃ³n"), "Mi Bombón")
        self.assertEqual(script.repaired_text("Young & NaÃ¯ve"), "Young & Naïve")

    def test_correct_text_is_left_alone(self):
        self.assertIsNone(script.repaired_text("Mi Bombón"))
        self.assertIsNone(script.repaired_text("Naïve"))

    def test_plain_ascii_is_left_alone(self):
        self.assertIsNone(script.repaired_text("Candle On The Water"))

    def test_text_that_cannot_be_latin1_is_left_alone(self):
        self.assertIsNone(script.repaired_text("日本語"))


class TestSharedConstants(unittest.TestCase):
    """The script repeats a couple of the player's values to avoid importing Kivy."""

    def test_the_minimum_song_length_matches_the_player(self):
        from music_player import PlayerConstants
        self.assertEqual(script.MIN_SONG_LENGTH_SECONDS,
                         PlayerConstants.MIN_SONG_LENGTH_SECONDS)
        self.assertEqual(script.FADE_SECONDS, PlayerConstants.FADE_TIME)

    def test_the_default_max_playtime_matches_the_player(self):
        from music_player import MusicPlayer
        self.assertEqual(script.DEFAULT_MAX_PLAYTIME,
                         MusicPlayer.song_max_playtime.defaultvalue)


if __name__ == "__main__":
    unittest.main()
