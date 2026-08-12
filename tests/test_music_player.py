import unittest
import json
import time
import os
import shutil
import tempfile
from unittest.mock import patch, MagicMock

# Stop Kivy from consuming the test runner's arguments. Note that Kivy does
# still open a window: the editor tests build real widgets and fail without a
# window provider, so these tests need a display.
os.environ["KIVY_NO_ARGS"] = "1"

# Now we can safely import the application components
# pylint: disable=wrong-import-position
from music_player import MusicPlayer, MusicApp, PlayerConstants
from kivy.config import ConfigParser
from song_cache import SongCache
from tests.support import filesystem_is_case_sensitive
import app_paths
import practice_type_rules

FADE = PlayerConstants.FADE_TIME
MAX_TRIM = PlayerConstants.MAX_TRIM_SECONDS
MIN_PLAY = PlayerConstants.MIN_SONG_PLAY_SECONDS


class TestMusicPlayerLogic(unittest.TestCase):
    """
    Unit tests for the business logic of the MusicPlayer class.

    These tests do not require a running Kivy App and focus on pure logic.

    To run these tests:
    1. Make sure you have the necessary Kivy dependencies for testing:
       pip install "kivy[base]"

    2. From the repository root, run the whole suite with ./run_tests.sh or
       run_unit_tests.bat, or just this file with:
       python -m pytest tests/test_music_player.py
    """

    def setUp(self):
        """
        Set up a fresh MusicPlayer instance for each test.
        This method runs before every single test function, ensuring test isolation.
        """
        # Bypassing the full __init__ to avoid widget setup, which would require a full Kivy context.
        self.player = MusicPlayer.__new__(MusicPlayer)

        # Manually initializing properties needed for the logic tests.
        self.player.practice_dances = {
            "default": [
                "Waltz", "Tango", "VWSlow", "VienneseWaltz", "Foxtrot",
                "QuickStep", "WCS", "Samba", "ChaCha", "Rumba", "PasoDoble",
                "JSlow", "Jive"
            ],
            "newcomer": [
                "Waltz", "JSlow", "Jive", "Rumba", "Foxtrot", "ChaCha",
                "Tango", "Samba", "QuickStep", "VWSlow", "VienneseWaltz", "WCS"
            ],
        }
        # Mock methods that interact with the file system or Kivy UI to isolate the logic.
        self.player.update_playlist = MagicMock()
        self.player.load_custom_practice_types = MagicMock(return_value={})
        self.player.custom_practice_mapping = {}
        # Manually call merge_custom_practice_types as it's part of the setup logic.
        self.player.merge_custom_practice_types()


    def test_secs_to_time_str(self):
        """Tests the conversion of seconds to a formatted time string (e.g., MM:SS)."""
        self.assertEqual(self.player._secs_to_time_str(59), "00:59")
        self.assertEqual(self.player._secs_to_time_str(60), "01:00")
        self.assertEqual(self.player._secs_to_time_str(150), "02:30")
        self.assertEqual(self.player._secs_to_time_str(3600), "01:00:00")
        self.assertEqual(self.player._secs_to_time_str(3661), "01:01:01")

    def test_get_song_label(self):
        """Tests the generation of song labels from metadata dictionaries."""
        # Test a standard song with complete information.
        song_info = {
            'title': 'Blue Suede Shoes',
            'artist': 'Elvis Presley',
            'album': 'Elvis Presley',
            'genre': 'Rock and Roll'
        }
        expected_label = "Blue Suede Shoes / Rock and Roll / Elvis Presley / Elvis Presley"
        self.assertEqual(self.player._get_song_label(song_info), expected_label)

        # Test a song with missing information to ensure it uses default values.
        song_info_missing = {'title': 'Hound Dog'}
        expected_label_missing = "Hound Dog / Genre Unspecified / Artist Unspecified / Album Unspecified"
        self.assertEqual(self.player._get_song_label(song_info_missing), expected_label_missing)

        # Test an announcement file, which should only display its title.
        announce_info = {'dance': 'announce', 'title': 'Waltz'}
        self.assertEqual(self.player._get_song_label(announce_info), "Waltz")

    def test_get_adjusted_song_count(self):
        """Tests the logic for adjusting song counts based on practice type rules."""
        self.player.adjust_song_counts_for_playlist = True
        self.player.current_dance_adjustments = {
            "Jive": "n-1",
            "VWSlow": "cap_at_1",
            "WCS": "cap_at_2",
            "PasoDoble": {"1": 0, "2": 1, "default": 2}
        }

        # Test each type of rule to ensure it's interpreted correctly.
        self.assertEqual(self.player._get_adjusted_song_count("Jive", 3), 2, "Failed 'n-1' rule")
        self.assertEqual(self.player._get_adjusted_song_count("Jive", 1), 1, "Failed 'n-1' rule at minimum")
        self.assertEqual(self.player._get_adjusted_song_count("VWSlow", 5), 1, "Failed 'cap_at_1' rule")
        self.assertEqual(self.player._get_adjusted_song_count("WCS", 5), 2, "Failed 'cap_at_2' rule")
        self.assertEqual(self.player._get_adjusted_song_count("PasoDoble", 1), 0, "Failed dictionary mapping rule for 1")
        self.assertEqual(self.player._get_adjusted_song_count("PasoDoble", 2), 1, "Failed dictionary mapping rule for 2")
        self.assertEqual(self.player._get_adjusted_song_count("PasoDoble", 3), 2, "Failed dictionary default rule")
        self.assertEqual(self.player._get_adjusted_song_count("Tango", 3), 3, "Failed for a dance with no rules")

    def test_set_practice_type_60min(self):
        """Tests that properties are set correctly for the '60min' practice type."""
        self.player.set_practice_type(None, "60min")

        self.assertEqual(self.player.num_selections, 2)
        self.assertEqual(self.player.randomize_playlist, True)
        self.assertEqual(self.player.adjust_song_counts_for_playlist, True)
        self.assertFalse(self.player.play_all_songs)
        self.assertIn("PasoDoble", self.player.current_dance_adjustments)
        self.assertEqual(self.player.dances, self.player.practice_dances["default"])

    def test_set_practice_type_nc_60min(self):
        """Tests that properties are set correctly for the 'NC 60min' practice type."""
        self.player.set_practice_type(None, "NC 60min")

        self.assertEqual(self.player.num_selections, 2)
        self.assertEqual(self.player.dances, self.player.practice_dances["newcomer"])


    @patch('os.path.isdir')
    @patch('os.walk')
    def test_collect_music_files(self, mock_walk, mock_isdir):
        """
        Tests the file collection logic by mocking the file system.
        This allows us to test the file filtering logic without needing real files or folders.
        """
        mock_isdir.return_value = True
        fake_music_dir = '/fake/music'
        fake_waltz_dir = os.path.join(fake_music_dir, 'Waltz')

        # Define the fake file system structure that os.walk will "find".
        mock_walk.return_value = [
            (fake_waltz_dir, ['subdir'], ['song1.mp3', 'song2.wav', 'info.txt']),
            (os.path.join(fake_waltz_dir, 'subdir'), [], ['song3.m4a', 'album_art.jpg'])
        ]

        result = self.player._collect_music_files(fake_music_dir, 'Waltz')

        # Verify that the function attempted to walk the correct directory.
        mock_walk.assert_called_with(fake_waltz_dir)

        # Check that only valid music file extensions were collected from the fake structure.
        self.assertEqual(len(result), 3)
        self.assertIn(os.path.join(fake_waltz_dir, 'song1.mp3'), result)
        self.assertIn(os.path.join(fake_waltz_dir, 'song2.wav'), result)
        self.assertIn(os.path.join(fake_waltz_dir, 'subdir', 'song3.m4a'), result)
        self.assertNotIn(os.path.join(fake_waltz_dir, 'info.txt'), result)

    @patch('music_player.MusicPlayer._collect_music_files')
    @patch('music_player.MusicPlayer._create_song_info')
    @patch('music_player.MusicPlayer._get_announce_path', return_value=None)
    def test_get_songs_for_dance_with_play_all(self, mock_get_announce, mock_create_info, mock_collect_files):
        """Tests that 'play_all_songs' overrides num_selections and gets all files."""
        # --- Setup ---
        # Set player state to simulate a practice type where all songs should be played.
        self.player.play_all_songs = True
        self.player.randomize_playlist = False # Use non-random for a predictable output order.

        # Mock the list of files that would be found on the file system.
        fake_paths = ['/music/c.mp3', '/music/a.mp3', '/music/b.mp3']
        mock_collect_files.return_value = fake_paths

        # Mock the metadata reader to just return the path for easy verification.
        mock_create_info.side_effect = lambda path, dance: {'path': path, 'dance': dance}

        # --- Action ---
        # Call the method. Note that num_selections is 1, but should be ignored.
        result_playlist = self.player._get_songs_for_dance('/fake/dir', 'TestDance', 1, False)

        # --- Assertions ---
        # 1. Verify that all 3 mocked files were selected, not just 1.
        self.assertEqual(len(result_playlist), 3)

        # 2. Verify the file collection was called as expected.
        mock_collect_files.assert_called_with('/fake/dir', 'TestDance')

        # 3. Since randomize_playlist was False, verify the output is sorted alphabetically.
        self.assertEqual(result_playlist[0]['path'], '/music/a.mp3')
        self.assertEqual(result_playlist[1]['path'], '/music/b.mp3')
        self.assertEqual(result_playlist[2]['path'], '/music/c.mp3')


class TestTimedBlockPlanning(unittest.TestCase):
    """Tests for the pure block-planning helpers. No Kivy context needed."""

    def test_effective_length_uses_natural_length_below_cap(self):
        """A song shorter than the cap occupies exactly its own duration."""
        self.assertEqual(MusicPlayer._effective_length(155, 210), 155)

    def test_effective_length_caps_long_song(self):
        """A long song is accounted for at cap + fade, not its real length."""
        self.assertEqual(MusicPlayer._effective_length(360, 210), 220)

    def test_exact_fit_is_left_alone(self):
        """When songs already total the budget, nothing is trimmed."""
        planned = MusicPlayer._plan_timed_block([200, 200, 200], 600, MAX_TRIM, MIN_PLAY)
        self.assertEqual(planned, [200, 200, 200])

    def test_uniform_trim_spreads_overshoot_and_keeps_lengths_distinct(self):
        """Each song gives up the same seconds, so relative lengths survive."""
        lengths = [155, 170, 185, 140, 190]  # 840
        planned = MusicPlayer._plan_timed_block(lengths, 774, MAX_TRIM, MIN_PLAY)

        self.assertEqual(len(planned), 5)
        self.assertAlmostEqual(sum(planned), 774, places=3)
        # Every song trimmed by the same 13.2s.
        trims = [full - play for full, play in zip(lengths, planned)]
        for trim in trims:
            self.assertAlmostEqual(trim, trims[0], places=6)
        # And they are still different lengths from each other.
        self.assertEqual(len(set(round(p, 3) for p in planned)), 5)

    def test_block_runs_short_when_songs_run_out(self):
        """A thin folder yields a short block rather than a padded one."""
        planned = MusicPlayer._plan_timed_block([200, 200], 774, MAX_TRIM, MIN_PLAY)
        self.assertEqual(planned, [200, 200])
        self.assertLess(sum(planned), 774)

    def test_last_song_dropped_when_trim_would_be_too_deep(self):
        """Rather than chop every song hard, drop the last one and run short."""
        # Two songs of 220 against a 240 budget: trimming both costs 100s each.
        planned = MusicPlayer._plan_timed_block([220, 220], 240, MAX_TRIM, MIN_PLAY)
        self.assertEqual(planned, [220])

    def test_single_song_longer_than_budget_is_trimmed_anyway(self):
        """With nothing to drop back to, the one song is trimmed to fit."""
        planned = MusicPlayer._plan_timed_block([220], 150, MAX_TRIM, MIN_PLAY)
        self.assertAlmostEqual(sum(planned), 150, places=3)

    def test_short_songs_are_not_trimmed_below_the_floor(self):
        """A short song keeps its floor; the longer ones absorb its share."""
        lengths = [MIN_PLAY + 5, 220, 220]
        planned = MusicPlayer._plan_timed_block(lengths, sum(lengths) - 60, MAX_TRIM, MIN_PLAY)

        self.assertAlmostEqual(sum(planned), sum(lengths) - 60, places=3)
        self.assertGreaterEqual(planned[0], MIN_PLAY)
        # The two long songs gave up more than the short one did.
        self.assertGreater(lengths[1] - planned[1], lengths[0] - planned[0])

    def test_trim_that_cannot_be_absorbed_leaves_block_over_budget(self):
        """The floor wins over the budget; the caller reports the overrun."""
        planned = MusicPlayer._apply_uniform_trim([MIN_PLAY, MIN_PLAY], 60, MIN_PLAY)
        self.assertEqual(planned, [MIN_PLAY, MIN_PLAY])

    def test_empty_block(self):
        """No candidates means no songs, not a crash."""
        self.assertEqual(MusicPlayer._plan_timed_block([], 600, MAX_TRIM, MIN_PLAY), [])


class TestDanceMinutesValidation(unittest.TestCase):
    """Bad dance_minutes config should degrade, not raise."""

    DANCES = ["Waltz", "Tango"]

    def test_valid_entries_pass_through(self):
        self.assertEqual(
            MusicPlayer._validate_dance_minutes({"Waltz": 13, "Tango": 8.5}, self.DANCES),
            {"Waltz": 13.0, "Tango": 8.5},
        )

    def test_unknown_dance_is_dropped(self):
        self.assertEqual(
            MusicPlayer._validate_dance_minutes({"Jive": 10}, self.DANCES), {})

    def test_non_numeric_and_non_positive_are_dropped(self):
        self.assertEqual(
            MusicPlayer._validate_dance_minutes(
                {"Waltz": "thirteen", "Tango": 0}, self.DANCES),
            {},
        )

    def test_non_dict_is_ignored(self):
        self.assertEqual(MusicPlayer._validate_dance_minutes([13, 8], self.DANCES), {})
        self.assertEqual(MusicPlayer._validate_dance_minutes(None, self.DANCES), {})


class TestCandidateDrawing(unittest.TestCase):
    """Drawing must not touch history until the block is settled."""

    def setUp(self):
        self.player = MusicPlayer.__new__(MusicPlayer)

    def test_draw_prefers_unplayed_and_mutates_nothing(self):
        history = {"Waltz": ["a", "b"]}
        candidates = self.player._draw_candidates(["a", "b", "c", "d"], "Waltz", history)

        self.assertEqual(set(candidates[:2]), {"c", "d"})
        self.assertEqual(set(candidates[2:]), {"a", "b"})
        self.assertEqual(history, {"Waltz": ["a", "b"]})

    def test_commit_appends_when_pool_not_exhausted(self):
        history = {"Waltz": ["a"]}
        MusicPlayer._commit_history(history, "Waltz", ["b", "c"])
        self.assertEqual(history["Waltz"], ["a", "b", "c"])

    def test_commit_restarts_cycle_when_pool_wraps(self):
        history = {"Waltz": ["a", "b"]}
        MusicPlayer._commit_history(history, "Waltz", ["c", "a"])
        self.assertEqual(history["Waltz"], ["c", "a"])

    def test_commit_of_nothing_is_a_no_op(self):
        history = {"Waltz": ["a"]}
        MusicPlayer._commit_history(history, "Waltz", [])
        self.assertEqual(history["Waltz"], ["a"])


class TestTimedBlockAssembly(unittest.TestCase):
    """End-to-end block building with the filesystem mocked out."""

    DURATIONS = {
        "/m/Waltz/1.mp3": 155,
        "/m/Waltz/2.mp3": 170,
        "/m/Waltz/3.mp3": 185,
        "/m/Waltz/4.mp3": 140,
        "/m/Waltz/5.mp3": 190,
        "/m/Waltz/6.mp3": 200,
    }

    def setUp(self):
        self.player = MusicPlayer.__new__(MusicPlayer)
        self.player.song_max_playtime = 210
        self.player.current_dance_max_playtimes = {}
        self.player.current_dance_minutes = {"Waltz": 13}
        self.player.play_all_songs = False
        self.player.play_single_song = False
        self.player._load_play_history = MagicMock(return_value={})
        self.player._save_play_history = MagicMock()
        self.player._get_announce_path = MagicMock(return_value="/announce/Waltz.ogg")

        def fake_song_info(path, dance):
            if dance == 'announce':
                return {'path': path, 'dance': 'announce', 'title': 'Waltz',
                        'duration': 6, 'max_playtime': 6}
            return {'path': path, 'dance': dance, 'title': path,
                    'duration': self.DURATIONS[path],
                    'max_playtime': self.player._cap_for_dance(dance)}

        self.player._create_song_info = MagicMock(side_effect=fake_song_info)

    def _playing_length(self, song):
        """How long the player will actually play this item."""
        return min(song['duration'], song['max_playtime'] + FADE)

    def test_block_lands_on_budget_including_announcement(self):
        block = self.player._get_timed_songs_for_dance(
            "Waltz", list(self.DURATIONS), 13, randomize=False)

        self.assertEqual(block[0]['dance'], 'announce')
        total = sum(self._playing_length(song) for song in block)
        self.assertAlmostEqual(total, 13 * 60, delta=1)

    def test_songs_keep_distinct_lengths(self):
        block = self.player._get_timed_songs_for_dance(
            "Waltz", list(self.DURATIONS), 13, randomize=False)

        lengths = [round(self._playing_length(s), 3) for s in block[1:]]
        self.assertEqual(len(lengths), len(set(lengths)))

    def test_only_songs_actually_used_are_recorded_in_history(self):
        history = {}
        self.player._load_play_history = MagicMock(return_value=history)

        block = self.player._get_timed_songs_for_dance(
            "Waltz", list(self.DURATIONS), 13, randomize=True)

        used = [song['path'] for song in block if song['dance'] != 'announce']
        self.assertEqual(history.get("Waltz"), used)
        # Metadata was read for at most one song beyond those kept.
        self.assertLessEqual(len(used), len(self.DURATIONS))

    def test_per_dance_cap_limits_a_long_song(self):
        """A long track is capped, and the cap is what the budget counts."""
        self.player.current_dance_max_playtimes = {"Waltz": 150}
        paths = ["/m/Waltz/long.mp3"]
        self.DURATIONS["/m/Waltz/long.mp3"] = 600

        block = self.player._get_timed_songs_for_dance(
            "Waltz", paths, 8, randomize=False)

        song = block[1]
        self.assertLessEqual(song['max_playtime'], 150)

    def test_untrimmed_song_keeps_the_normal_cap(self):
        """A block that runs short must not fade its songs early."""
        block = self.player._get_timed_songs_for_dance(
            "Waltz", ["/m/Waltz/1.mp3"], 13, randomize=False)
        self.assertEqual(block[1]['max_playtime'], 210)

    def test_budget_smaller_than_announcement(self):
        block = self.player._get_timed_songs_for_dance(
            "Waltz", list(self.DURATIONS), 0.05, randomize=False)
        self.assertEqual(len(block), 1)
        self.assertEqual(block[0]['dance'], 'announce')


class TestTimedRouting(unittest.TestCase):
    """_get_songs_for_dance must only take the timed path when it should."""

    def setUp(self):
        self.player = MusicPlayer.__new__(MusicPlayer)
        self.player.current_dance_minutes = {"Waltz": 13}
        self.player.play_all_songs = False
        self.player.play_single_song = False
        self.player._collect_music_files = MagicMock(return_value=["/m/Waltz/1.mp3"])
        self.player._get_timed_songs_for_dance = MagicMock(return_value=["timed"])
        self.player._get_announce_path = MagicMock(return_value=None)
        self.player._create_song_info = MagicMock(return_value=None)
        self.player._load_play_history = MagicMock(return_value={})
        self.player._save_play_history = MagicMock()
        self.player.adjust_song_counts_for_playlist = False
        self.player.current_dance_adjustments = {}

    def test_budgeted_dance_uses_timed_path(self):
        result = self.player._get_songs_for_dance("/m", "Waltz", 4, True)
        self.assertEqual(result, ["timed"])
        self.player._get_timed_songs_for_dance.assert_called_once()

    def test_unbudgeted_dance_uses_count_path(self):
        self.player._get_songs_for_dance("/m", "Tango", 4, True)
        self.player._get_timed_songs_for_dance.assert_not_called()

    def test_play_all_songs_overrides_budget(self):
        self.player.play_all_songs = True
        self.player._get_songs_for_dance("/m", "Waltz", 4, True)
        self.player._get_timed_songs_for_dance.assert_not_called()


class TestSegmentValidation(unittest.TestCase):
    """Bad segment config should degrade, not raise."""

    def test_cue_segment(self):
        result = MusicPlayer._validate_segments([{"cue": "round_gap", "label": "break"}])
        self.assertEqual(result, [{"cue": "round_gap", "label": "break"}])

    def test_round_segment_defaults(self):
        result = MusicPlayer._validate_segments([{"round": ["Waltz"], "clip_seconds": 90}])
        self.assertEqual(result[0]["count"], 1)
        self.assertEqual(result[0]["gap_seconds"], 0)
        self.assertFalse(result[0]["announce"])

    def test_segment_without_cue_or_round_is_dropped(self):
        self.assertEqual(MusicPlayer._validate_segments([{"clip_seconds": 90}]), [])

    def test_empty_round_is_dropped(self):
        self.assertEqual(MusicPlayer._validate_segments([{"round": []}]), [])

    def test_non_numeric_clip_is_dropped(self):
        self.assertEqual(
            MusicPlayer._validate_segments([{"round": ["Waltz"], "clip_seconds": "long"}]), [])

    def test_zero_count_is_dropped(self):
        self.assertEqual(
            MusicPlayer._validate_segments([{"round": ["Waltz"], "count": 0}]), [])

    def test_non_list_is_ignored(self):
        self.assertEqual(MusicPlayer._validate_segments({"round": ["Waltz"]}), [])
        self.assertEqual(MusicPlayer._validate_segments(None), [])

    def test_one_bad_segment_does_not_lose_the_others(self):
        result = MusicPlayer._validate_segments([
            {"cue": "round_gap"}, "nonsense", {"round": ["Waltz"], "clip_seconds": 90},
        ])
        self.assertEqual(len(result), 2)


class TestCueLabels(unittest.TestCase):
    """Cues need readable playlist buttons even without an explicit label."""

    def test_gap_label_from_duration(self):
        self.assertEqual(MusicPlayer._default_cue_label("gap_20", 20.0),
                         "--- 20 second gap ---")

    def test_round_gap_label(self):
        self.assertIn("warning", MusicPlayer._default_cue_label("round_gap", 120.0))

    def test_song_label_prefixes_round_songs(self):
        player = MusicPlayer.__new__(MusicPlayer)
        label = player._get_song_label({
            'dance': 'Waltz', 'title': 'T', 'genre': 'G', 'artist': 'A', 'album': 'B',
            'label_prefix': 'Waltz 01:30',
        })
        self.assertTrue(label.startswith("Waltz 01:30"))
        self.assertIn("T / G / A / B", label)

    def test_cue_label_used_for_cue_items(self):
        player = MusicPlayer.__new__(MusicPlayer)
        self.assertEqual(
            player._get_song_label({'dance': 'cue', 'cue_label': '--- 20 second gap ---'}),
            "--- 20 second gap ---")


class TestHardCutPlayback(unittest.TestCase):
    """A round clip must stop dead at its length, not fade past it."""

    def setUp(self):
        self.player = MusicPlayer.__new__(MusicPlayer)
        self.player.sound = MagicMock()
        self.player.sound.volume = 1.0
        self.player._schedule_interval = 0.1
        self.player.progress_max = 200
        self.player._advance_playlist = MagicMock()

    def test_no_fade_applied_when_fade_is_zero(self):
        self.player._playing_position = 95
        self.player._handle_fade_out(90, fade=0)
        self.assertEqual(self.player.sound.volume, 1.0)

    def test_fade_applied_when_fade_is_set(self):
        self.player._playing_position = 95
        self.player._handle_fade_out(90, fade=FADE)
        self.assertLess(self.player.sound.volume, 1.0)

    def test_advances_exactly_at_clip_length_with_hard_cut(self):
        self.player._playing_position = 89.9
        self.player._check_and_advance_song(90, fade=0, margin=PlayerConstants.END_MARGIN)
        self.player._advance_playlist.assert_not_called()

        self.player._playing_position = 90.0
        self.player._check_and_advance_song(90, fade=0, margin=PlayerConstants.END_MARGIN)
        self.player._advance_playlist.assert_called_once()

    def test_faded_song_plays_past_max_playtime(self):
        self.player._playing_position = 95
        self.player._check_and_advance_song(90, fade=FADE, margin=PlayerConstants.END_MARGIN)
        self.player._advance_playlist.assert_not_called()

    def test_cue_uses_tighter_end_margin(self):
        """A 20s gap should not be cut a whole second short."""
        self.player.progress_max = 20
        self.player._playing_position = 19.5
        self.player._check_and_advance_song(20, fade=0, margin=PlayerConstants.CUE_END_MARGIN)
        self.player._advance_playlist.assert_not_called()

        self.player._playing_position = 19.85
        self.player._check_and_advance_song(20, fade=0, margin=PlayerConstants.CUE_END_MARGIN)
        self.player._advance_playlist.assert_called_once()


class TestRoundAssembly(unittest.TestCase):
    """Building a round, with the filesystem mocked out."""

    DANCES = ["Waltz", "Tango", "VienneseWaltz", "Foxtrot", "QuickStep"]

    def setUp(self):
        self.player = MusicPlayer.__new__(MusicPlayer)
        self.player.song_max_playtime = 210
        self.player.current_dance_max_playtimes = {}
        self.player.practice_type = "Comp Rounds"
        self.player._load_play_history = MagicMock(return_value={})
        self.player._save_play_history = MagicMock()
        self.player._get_announce_path = MagicMock(return_value="/announce/X.ogg")
        self.player._collect_music_files = MagicMock(
            side_effect=lambda d, dance: [f"/m/{dance}/{i}.mp3" for i in range(6)])

        def fake_song_info(path, dance):
            if dance in ('announce', 'cue'):
                duration = 120.0 if 'round_gap' in path else 20.0
                return {'path': path, 'dance': dance, 'title': os.path.basename(path),
                        'duration': duration, 'max_playtime': duration, 'fade_seconds': 0}
            return {'path': path, 'dance': dance, 'title': path, 'genre': '', 'artist': '',
                    'album': '', 'duration': 180.0, 'max_playtime': 210, 'fade_seconds': FADE}

        self.player._create_song_info = MagicMock(side_effect=fake_song_info)
        self.player._get_cue_path = MagicMock(side_effect=lambda name: f"/cues/{name}.ogg")

    def _final(self, **overrides):
        segment = {"round": self.DANCES, "count": 1, "clip_seconds": 90,
                   "gap_seconds": 20, "announce": False, "label": "FINAL"}
        segment.update(overrides)
        return segment

    def test_final_structure_and_length(self):
        """Five dances, four gaps between them, 8:50 total."""
        items = self.player._get_round_songs("/m", self._final(), randomize=False)

        dances = [i for i in items if i['dance'] not in ('cue', 'announce')]
        gaps = [i for i in items if i['dance'] == 'cue']
        self.assertEqual(len(dances), 5)
        self.assertEqual(len(gaps), 4)
        self.assertEqual(MusicPlayer._playlist_length(items), 5 * 90 + 4 * 20)

    def test_clips_are_hard_cut(self):
        items = self.player._get_round_songs("/m", self._final(), randomize=False)
        for item in items:
            if item['dance'] not in ('cue', 'announce'):
                self.assertEqual(item['max_playtime'], 90)
                self.assertEqual(item['fade_seconds'], 0)

    def test_no_announcements_by_default(self):
        items = self.player._get_round_songs("/m", self._final(), randomize=False)
        self.assertFalse([i for i in items if i['dance'] == 'announce'])

    def test_announcements_when_requested(self):
        items = self.player._get_round_songs("/m", self._final(announce=True), randomize=False)
        self.assertEqual(len([i for i in items if i['dance'] == 'announce']), 5)

    def test_no_trailing_gap_after_the_last_dance(self):
        items = self.player._get_round_songs("/m", self._final(), randomize=False)
        self.assertNotEqual(items[-1]['dance'], 'cue')

    def test_semi_final_pairs_each_dance(self):
        """Two of each dance, consecutively, 19:40 total."""
        items = self.player._get_round_songs(
            "/m", self._final(count=2, clip_seconds=100), randomize=False)

        dances = [i['dance'] for i in items if i['dance'] not in ('cue', 'announce')]
        self.assertEqual(len(dances), 10)
        self.assertEqual(dances[:2], ["Waltz", "Waltz"])
        self.assertEqual(dances[2:4], ["Tango", "Tango"])
        self.assertEqual(MusicPlayer._playlist_length(items), 10 * 100 + 9 * 20)

    def test_missing_dance_folder_is_skipped(self):
        self.player._collect_music_files = MagicMock(
            side_effect=lambda d, dance: [] if dance == "Tango"
            else [f"/m/{dance}/{i}.mp3" for i in range(6)])
        items = self.player._get_round_songs("/m", self._final(), randomize=False)
        dances = [i for i in items if i['dance'] not in ('cue', 'announce')]
        self.assertEqual(len(dances), 4)

    def test_song_shorter_than_the_clip_is_not_padded(self):
        self.player._create_song_info = MagicMock(
            side_effect=lambda path, dance: {
                'path': path, 'dance': dance, 'title': path, 'duration': 60.0,
                'max_playtime': 210, 'fade_seconds': FADE})
        items = self.player._get_round_songs(
            "/m", self._final(gap_seconds=0), randomize=False)
        self.assertEqual(MusicPlayer._playlist_length(items), 5 * 60)

    def test_songs_shorter_than_the_clip_are_avoided(self):
        """A round must not pick a 1:30 track for a 1:40 heat if longer ones exist."""
        durations = {f"/m/Waltz/{i}.mp3": (90.0 if i < 3 else 180.0) for i in range(6)}
        self.player._collect_music_files = MagicMock(
            side_effect=lambda d, dance: list(durations))
        self.player._create_song_info = MagicMock(
            side_effect=lambda path, dance: {
                'path': path, 'dance': dance, 'title': path,
                'duration': durations[path], 'max_playtime': 210, 'fade_seconds': FADE})

        chosen = self.player._pick_songs(
            "Waltz", list(durations), 2, 100, randomize=False)
        self.assertTrue(all(info['duration'] >= 100 for info in chosen))

    def test_falls_back_to_longest_when_nothing_is_long_enough(self):
        durations = {"/m/Waltz/a.mp3": 80.0, "/m/Waltz/b.mp3": 95.0}
        self.player._create_song_info = MagicMock(
            side_effect=lambda path, dance: {
                'path': path, 'dance': dance, 'title': path,
                'duration': durations[path], 'max_playtime': 210, 'fade_seconds': FADE})

        chosen = self.player._pick_songs(
            "Waltz", list(durations), 1, 100, randomize=False)
        self.assertEqual(len(chosen), 1)
        self.assertEqual(chosen[0]['duration'], 95.0)


class TestFullRoundsPlaylist(unittest.TestCase):
    """The whole Comp Rounds sequence from its real JSON definition."""

    def setUp(self):
        practice_types_path = os.path.join(app_paths.APP_DIR, "builtin_practice_types.json")
        with open(practice_types_path, encoding="utf-8") as handle:
            practice_types = json.load(handle)
        self.segments = MusicPlayer._validate_segments(
            practice_types["Comp Rounds"]["segments"])

        self.player = MusicPlayer.__new__(MusicPlayer)
        self.player.song_max_playtime = 210
        self.player.current_dance_max_playtimes = {}
        self.player.practice_type = "Comp Rounds"
        self.player._load_play_history = MagicMock(return_value={})
        self.player._save_play_history = MagicMock()
        self.player._collect_music_files = MagicMock(
            side_effect=lambda d, dance: [f"/m/{dance}/{i}.mp3" for i in range(20)])
        self.player._get_cue_path = MagicMock(side_effect=lambda name: f"/cues/{name}.ogg")

        def fake_song_info(path, dance):
            if dance == 'cue':
                duration = 120.0 if 'round_gap' in path else 20.0
                return {'path': path, 'dance': dance, 'title': os.path.basename(path),
                        'duration': duration, 'max_playtime': duration, 'fade_seconds': 0}
            return {'path': path, 'dance': dance, 'title': path, 'genre': '', 'artist': '',
                    'album': '', 'duration': 180.0, 'max_playtime': 210, 'fade_seconds': FADE}

        self.player._create_song_info = MagicMock(side_effect=fake_song_info)

    def test_matches_the_documented_running_time(self):
        """4 breaks + 3 finals + 1 semi = 54:10."""
        playlist = self.player._build_segment_playlist("/m", self.segments, randomize=False)
        expected = 4 * 120 + 3 * (5 * 90 + 4 * 20) + (10 * 100 + 9 * 20)
        self.assertEqual(MusicPlayer._playlist_length(playlist), expected)
        self.assertEqual(expected, 3250)  # 54:10

    def test_no_dance_repeats_across_the_whole_sequence(self):
        history = {}
        self.player._load_play_history = MagicMock(return_value=history)
        playlist = self.player._build_segment_playlist("/m", self.segments, randomize=True)

        songs = [i['path'] for i in playlist if i['dance'] not in ('cue', 'announce')]
        self.assertEqual(len(songs), 25)  # 5 + 5 + 10 + 5
        self.assertEqual(len(set(songs)), 25)

    def test_every_break_is_present(self):
        playlist = self.player._build_segment_playlist("/m", self.segments, randomize=False)
        breaks = [i for i in playlist if i['dance'] == 'cue' and i['duration'] == 120]
        self.assertEqual(len(breaks), 4)

    def test_missing_cue_audio_is_skipped_not_fatal(self):
        self.player._get_cue_path = MagicMock(return_value=None)
        playlist = self.player._build_segment_playlist("/m", self.segments, randomize=False)
        self.assertFalse([i for i in playlist if i['dance'] == 'cue'])
        self.assertEqual(len([i for i in playlist if i['dance'] not in ('cue',)]), 25)


class TestRoundsRouting(unittest.TestCase):
    """Segments must take over generation only when they are present."""

    def setUp(self):
        self.player = MusicPlayer.__new__(MusicPlayer)
        self.player.current_dance_minutes = {}
        self.player.current_segments = []
        self.player.practice_type = "test"
        self.player.song_max_playtime = 210
        self.player._build_segment_playlist = MagicMock(return_value=["segmented"])
        self.player._get_songs_for_dance = MagicMock(return_value=["counted"])

    def test_segments_take_over(self):
        self.player.current_segments = [{"cue": "round_gap", "label": None}]
        captured = {}
        from kivy.clock import Clock
        Clock.schedule_once = lambda cb, *a: captured.setdefault("scheduled", True)

        self.player._generate_playlist_in_background("/m", ["Waltz"], 2, True, False)
        self.player._build_segment_playlist.assert_called_once()
        self.player._get_songs_for_dance.assert_not_called()

    def test_without_segments_the_normal_path_runs(self):
        from kivy.clock import Clock
        Clock.schedule_once = lambda cb, *a: None

        self.player._generate_playlist_in_background("/m", ["Waltz"], 2, True, False)
        self.player._build_segment_playlist.assert_not_called()
        self.player._get_songs_for_dance.assert_called_once()

class TestMinimumSongLength(unittest.TestCase):
    """Count-based practice types should pass over very short tracks."""

    DURATIONS = {
        "/m/Waltz/short.mp3": 66.0,     # the 1:06 kind of track
        "/m/Waltz/a.mp3": 150.0,
        "/m/Waltz/b.mp3": 160.0,
        "/m/Waltz/c.mp3": 170.0,
    }

    def setUp(self):
        self.player = MusicPlayer.__new__(MusicPlayer)
        self.player.song_max_playtime = 210
        self.player.current_dance_max_playtimes = {}
        self.player.current_dance_minutes = {}
        self.player.current_dance_adjustments = {}
        self.player.adjust_song_counts_for_playlist = False
        self.player.play_all_songs = False
        self.player.play_single_song = False
        self.player._load_play_history = MagicMock(return_value={})
        self.player._save_play_history = MagicMock()
        self.player._get_announce_path = MagicMock(return_value=None)
        self.player._collect_music_files = MagicMock(return_value=list(self.DURATIONS))
        self.player._create_song_info = MagicMock(
            side_effect=lambda path, dance: None if dance == 'announce' else {
                'path': path, 'dance': dance, 'title': path,
                'duration': self.DURATIONS[path], 'max_playtime': 210,
                'fade_seconds': FADE})

    def test_short_song_is_not_selected(self):
        playlist = self.player._get_songs_for_dance("/m", "Waltz", 3, randomize=False)
        self.assertEqual(len(playlist), 3)
        self.assertNotIn("/m/Waltz/short.mp3", [s['path'] for s in playlist])

    def test_short_song_used_only_when_nothing_else_is_left(self):
        playlist = self.player._get_songs_for_dance("/m", "Waltz", 4, randomize=False)
        self.assertEqual(len(playlist), 4)
        self.assertIn("/m/Waltz/short.mp3", [s['path'] for s in playlist])

    def test_play_all_songs_ignores_the_minimum(self):
        self.player.play_all_songs = True
        playlist = self.player._get_songs_for_dance("/m", "Waltz", 1, randomize=False)
        self.assertEqual(len(playlist), 4)

    def test_timed_blocks_ignore_the_minimum(self):
        """A short song in a timed block just means one more song."""
        # A budget big enough to need every song in the folder.
        self.player.current_dance_minutes = {"Waltz": 10}
        playlist = self.player._get_songs_for_dance("/m", "Waltz", 1, randomize=False)
        self.assertIn("/m/Waltz/short.mp3", [s['path'] for s in playlist])

    def test_minimum_is_ninety_seconds(self):
        self.assertEqual(PlayerConstants.MIN_SONG_LENGTH_SECONDS, 90)


class TestHistoryCyclePreservation(unittest.TestCase):
    """A replay forced by song length must not discard the whole cycle."""

    ALL = ["a", "b", "c", "d", "e"]

    def test_cycle_kept_when_unplayed_songs_remain(self):
        history = {"Waltz": ["a", "b", "c"]}
        MusicPlayer._commit_history(history, "Waltz", ["a"], self.ALL)
        self.assertEqual(history["Waltz"], ["a", "b", "c"])

    def test_cycle_restarts_only_when_the_pool_is_exhausted(self):
        history = {"Waltz": ["a", "b", "c", "d"]}
        MusicPlayer._commit_history(history, "Waltz", ["a", "e"], self.ALL)
        self.assertEqual(history["Waltz"], ["a", "e"])

    def test_new_songs_are_appended_without_duplicates(self):
        history = {"Waltz": ["a", "b"]}
        MusicPlayer._commit_history(history, "Waltz", ["b", "c"], self.ALL)
        self.assertEqual(history["Waltz"], ["a", "b", "c"])

    def test_without_all_paths_a_replay_still_restarts_the_cycle(self):
        history = {"Waltz": ["a", "b"]}
        MusicPlayer._commit_history(history, "Waltz", ["a"])
        self.assertEqual(history["Waltz"], ["a"])


class TestSongCache(unittest.TestCase):
    """The metadata cache must be correct, self-healing and crash-tolerant."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cache_path = os.path.join(self.tmp, "cache.json")
        self.song = os.path.join(self.tmp, "song.mp3")
        with open(self.song, "wb") as handle:
            handle.write(b"x" * 100)
        self.fields = {"duration": 150.0, "title": "T", "artist": "A",
                       "album": "B", "genre": "G"}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_miss_then_hit(self):
        cache = SongCache(self.cache_path)
        self.assertIsNone(cache.get(self.song))
        cache.put(self.song, self.fields)
        entry = cache.get(self.song)
        self.assertEqual(entry["duration"], 150.0)
        self.assertEqual((cache.hits, cache.misses), (1, 1))

    def test_survives_a_restart(self):
        cache = SongCache(self.cache_path)
        cache.put(self.song, self.fields)
        self.assertTrue(cache.save())

        reloaded = SongCache(self.cache_path)
        self.assertEqual(reloaded.get(self.song)["title"], "T")

    def test_entry_is_rejected_when_the_file_changes(self):
        cache = SongCache(self.cache_path)
        cache.put(self.song, self.fields)
        with open(self.song, "wb") as handle:      # re-tagged: different size
            handle.write(b"x" * 200)
        self.assertIsNone(cache.get(self.song))
        self.assertEqual(cache.stale, 1)

    def test_missing_file_is_not_a_hit(self):
        cache = SongCache(self.cache_path)
        cache.put(self.song, self.fields)
        os.remove(self.song)
        self.assertIsNone(cache.get(self.song))

    def test_save_is_skipped_when_nothing_changed(self):
        cache = SongCache(self.cache_path)
        cache.put(self.song, self.fields)
        self.assertTrue(cache.save())
        self.assertFalse(cache.save())

    def test_corrupt_cache_is_treated_as_empty(self):
        with open(self.cache_path, "w", encoding="utf-8") as handle:
            handle.write("{ this is not json")
        cache = SongCache(self.cache_path)
        self.assertEqual(len(cache), 0)
        self.assertIsNone(cache.get(self.song))

    def test_cache_from_another_version_is_discarded(self):
        with open(self.cache_path, "w", encoding="utf-8") as handle:
            json.dump({"version": 999, "songs": {self.song: {"size": 100}}}, handle)
        self.assertEqual(len(SongCache(self.cache_path)), 0)

    def test_prune_removes_only_unlisted_paths(self):
        cache = SongCache(self.cache_path)
        cache.put(self.song, self.fields)
        cache._songs["/gone/old.mp3"] = {"size": 1, "mtime": 1.0}
        self.assertEqual(cache.prune([self.song]), 1)
        self.assertEqual(len(cache), 1)

    def test_reader_uses_the_cache_instead_of_reading_twice(self):
        """The second read of a file must not touch TinyTag."""
        player = MusicPlayer.__new__(MusicPlayer)
        MusicPlayer._song_cache = SongCache(self.cache_path)
        try:
            fake_tag = MagicMock(duration=150.0, title="T", artist="A", album="B", genre="G")
            with patch("music_player.TinyTag.get", return_value=fake_tag) as tinytag:
                player._read_tags(self.song)
                player._read_tags(self.song)
            self.assertEqual(tinytag.call_count, 1)
        finally:
            MusicPlayer._song_cache = None


class TestGenerationSnapshot(unittest.TestCase):
    """Settings must be frozen while a playlist is being built."""

    def setUp(self):
        self.player = MusicPlayer.__new__(MusicPlayer)
        self.player.practice_type = "60min"
        self.player.play_all_songs = False
        self.player.play_single_song = False
        self.player.adjust_song_counts_for_playlist = False
        self.player.current_dance_adjustments = {}
        self.player.current_dance_max_playtimes = {}
        self.player.current_dance_minutes = {}
        self.player.current_segments = []
        self.player.song_max_playtime = 210
        self.player._generation_config = None

    def tearDown(self):
        self.player._generation_config = None

    def test_live_values_are_used_when_nothing_is_generating(self):
        self.assertEqual(self.player._setting('song_max_playtime'), 210)
        self.player.song_max_playtime = 150
        self.assertEqual(self.player._setting('song_max_playtime'), 150)

    def test_snapshot_survives_a_practice_type_change(self):
        self.player._generation_config = self.player._snapshot_generation_settings()

        # A practice type change part way through generation.
        self.player.song_max_playtime = 90
        self.player.current_segments = [{"cue": "round_gap", "label": None}]
        self.player.current_dance_minutes = {"Waltz": 13}
        self.player.play_all_songs = True

        self.assertEqual(self.player._setting('song_max_playtime'), 210)
        self.assertEqual(self.player._setting('current_segments'), [])
        self.assertEqual(self.player._setting('current_dance_minutes'), {})
        self.assertFalse(self.player._setting('play_all_songs'))

    def test_cap_uses_the_snapshot(self):
        """The per-song cap must not change halfway through a block."""
        self.player.current_dance_max_playtimes = {"VienneseWaltz": 150}
        self.player._generation_config = self.player._snapshot_generation_settings()
        self.player.current_dance_max_playtimes = {}
        self.player.song_max_playtime = 999
        self.assertEqual(self.player._cap_for_dance("VienneseWaltz"), 150)
        self.assertEqual(self.player._cap_for_dance("Waltz"), 210)

    def test_every_setting_the_worker_reads_is_snapshotted(self):
        snapshot = self.player._snapshot_generation_settings()
        self.assertEqual(set(snapshot), set(MusicPlayer.GENERATION_SETTINGS))


class TestQueuedRegeneration(unittest.TestCase):
    """A request during generation is queued, not dropped."""

    def setUp(self):
        self.player = MusicPlayer.__new__(MusicPlayer)
        self.player._playlist_generation_in_progress = False
        self.player._regeneration_pending = False
        self.player._regeneration_start_playback = False
        self.player._generation_config = None
        self.player.stop_sound = MagicMock()
        self.player.music_dir = "/m"
        self.player.dances = ["Waltz"]
        self.player.num_selections = 2
        self.player.randomize_playlist = True
        for name in MusicPlayer.GENERATION_SETTINGS:
            if not hasattr(self.player, name):
                setattr(self.player, name, {} if name.startswith("current") else False)
        self.player.song_max_playtime = 210
        self.player.practice_type = "60min"

    def test_request_during_generation_is_queued(self):
        self.player._playlist_generation_in_progress = True
        self.player._generation_config = self.player._snapshot_generation_settings()
        self.player.dances = ["Tango"]          # a real settings change
        with patch("music_player.threading.Thread") as thread:
            self.player.update_playlist()
            thread.assert_not_called()
        self.assertTrue(self.player._regeneration_pending)

    def test_identical_request_during_generation_is_dropped(self):
        """Startup applies the practice type twice; that must not double the work."""
        self.player._playlist_generation_in_progress = True
        self.player._generation_config = self.player._snapshot_generation_settings()
        self.player.update_playlist()
        self.assertFalse(self.player._regeneration_pending)

    def test_queued_request_runs_when_generation_finishes(self):
        self.player._playlist_generation_in_progress = True
        self.player._generation_config = self.player._snapshot_generation_settings()
        self.player.dances = ["Tango"]
        self.player.update_playlist()          # queued

        self.player._display_playlist_buttons = MagicMock()
        self.player.restart_playlist = MagicMock()
        self.player.update_playlist = MagicMock()
        self.player._finish_playlist_generation([], False, 0)

        self.player.update_playlist.assert_called_once_with(start_playback=False)
        self.assertFalse(self.player._regeneration_pending)

    def test_snapshot_is_released_after_generation(self):
        self.player._generation_config = {"song_max_playtime": 1}
        self.player._display_playlist_buttons = MagicMock()
        self.player.restart_playlist = MagicMock()
        self.player.play_sound = MagicMock()
        self.player._is_first_load = False
        self.player.playlist = []
        self.player._finish_playlist_generation([], False, 0)
        self.assertIsNone(self.player._generation_config)


class TestAppPaths(unittest.TestCase):
    """Writable state stays beside the app when it can, and moves when it cannot.

    Nothing here needs real permissions, because the player no longer decides by
    trying to write: an install location is recognised from its path, and the
    permission check creates nothing. That is what lets these tests run
    identically on Windows, where chmod cannot make a directory read-only and
    probing Program Files stalls on Defender.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.app_dir = os.path.join(self.tmp, "app")
        self.user_dir = os.path.join(self.tmp, "user")
        os.makedirs(self.app_dir)
        app_paths.reset()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        app_paths.reset()

    def _app_dir_is_not_writable(self):
        """Makes the permission check report the application directory read-only."""
        return patch.object(
            app_paths, "directory_is_writable",
            side_effect=lambda directory: os.path.abspath(directory) != os.path.abspath(
                self.app_dir))

    def _app_dir_is_an_install_location(self):
        """Makes the application directory look like Program Files."""
        return patch.object(
            app_paths, "is_install_location",
            side_effect=lambda directory: os.path.abspath(directory) == os.path.abspath(
                self.app_dir))

    def test_writable_app_dir_is_used(self):
        """A git checkout or portable extract keeps everything where it is."""
        self.assertEqual(app_paths.state_dir(self.app_dir, self.user_dir), self.app_dir)

    def test_an_install_location_falls_back_without_being_touched(self):
        """Program Files must not even be probed, let alone written to."""
        before = os.listdir(self.app_dir)
        with self._app_dir_is_an_install_location():
            self.assertEqual(app_paths.state_dir(self.app_dir, self.user_dir), self.user_dir)
        self.assertEqual(os.listdir(self.app_dir), before,
                         "deciding where to write must not create anything")

    def test_read_only_app_dir_falls_back(self):
        with self._app_dir_is_not_writable():
            self.assertEqual(app_paths.state_dir(self.app_dir, self.user_dir), self.user_dir)
        self.assertTrue(os.path.isdir(self.user_dir))

    def test_deciding_writes_nothing_in_the_normal_case_either(self):
        """The old probe created and deleted a file on every single launch."""
        before = os.listdir(self.app_dir)
        app_paths.state_dir(self.app_dir, self.user_dir)
        self.assertEqual(os.listdir(self.app_dir), before)

    def test_windows_install_roots_come_from_the_environment(self):
        """Paths are built with os.path so this runs on either platform.

        Windows path syntax cannot be exercised from POSIX, where os.path is
        posixpath; what matters is that the Windows branch reads its roots from
        ProgramFiles and friends.
        """
        program_files = os.path.join(self.tmp, "Program Files")
        program_files_x86 = os.path.join(self.tmp, "Program Files (x86)")
        system_root = os.path.join(self.tmp, "Windows")

        with patch.object(app_paths.sys, "platform", "win32"), \
             patch.dict(os.environ, {"ProgramFiles": program_files,
                                     "ProgramFiles(x86)": program_files_x86,
                                     "SystemRoot": system_root}, clear=True):
            self.assertTrue(app_paths.is_install_location(program_files))
            self.assertTrue(app_paths.is_install_location(
                os.path.join(program_files, "DancePracticeMusicPlayer")))
            self.assertTrue(app_paths.is_install_location(
                os.path.join(program_files_x86, "Player")))
            self.assertTrue(app_paths.is_install_location(
                os.path.join(system_root, "System32", "thing")))

            # A checkout, a portable copy, and a sibling that merely shares the
            # prefix must all be treated as ordinary directories.
            self.assertFalse(app_paths.is_install_location(
                os.path.join(self.tmp, "Users", "rrusk", "git", "Player")))
            self.assertFalse(app_paths.is_install_location(self.app_dir))
            self.assertFalse(app_paths.is_install_location(program_files + " Extra"))

    def test_missing_environment_variables_are_skipped(self):
        with patch.object(app_paths.sys, "platform", "win32"), \
             patch.dict(os.environ, {}, clear=True):
            self.assertFalse(app_paths.is_install_location(self.app_dir))

    def test_posix_install_locations_are_recognised(self):
        with patch.object(app_paths.sys, "platform", "linux"):
            self.assertTrue(app_paths.is_install_location("/usr/share/player"))
            self.assertTrue(app_paths.is_install_location("/opt/player"))
            self.assertFalse(app_paths.is_install_location("/home/someone/git/player"))

    def test_the_permission_check_creates_nothing(self):
        before = os.listdir(self.app_dir)
        self.assertTrue(app_paths.directory_is_writable(self.app_dir))
        self.assertFalse(app_paths.directory_is_writable(os.path.join(self.tmp, "nope")))
        self.assertEqual(os.listdir(self.app_dir), before)

    def test_the_permission_check_respects_posix_permissions(self):
        """os.access is honest on POSIX; on Windows it is only a first filter."""
        if os.name == "nt":
            return
        os.chmod(self.app_dir, 0o555)
        try:
            if os.access(self.app_dir, os.W_OK):
                return                      # running as root
            self.assertFalse(app_paths.directory_is_writable(self.app_dir))
        finally:
            os.chmod(self.app_dir, 0o755)

    def test_shipped_file_is_copied_on_first_fallback_use(self):
        """A packaged build starts from the practice types it shipped with."""
        shipped = os.path.join(self.app_dir, "custom_practice_types.json")
        with open(shipped, "w", encoding="utf-8") as handle:
            handle.write('{"Shipped": {}}')

        with self._app_dir_is_an_install_location(), \
             patch.object(app_paths, "APP_DIR", self.app_dir), \
             patch.object(app_paths, "default_user_data_dir", lambda: self.user_dir):
            path = app_paths.user_path("custom_practice_types.json")

        self.assertEqual(os.path.dirname(path), self.user_dir)
        with open(path, encoding="utf-8") as handle:
            self.assertIn("Shipped", handle.read())
        # The shipped file is read-only in an installed build; the copy must not be.
        self.assertTrue(os.access(path, os.W_OK))

    def test_seeding_does_not_overwrite_existing_user_file(self):
        shipped = os.path.join(self.app_dir, "play_history.json")
        with open(shipped, "w", encoding="utf-8") as handle:
            handle.write('{"from": "app"}')
        os.makedirs(self.user_dir)
        existing = os.path.join(self.user_dir, "play_history.json")
        with open(existing, "w", encoding="utf-8") as handle:
            handle.write('{"from": "user"}')

        with self._app_dir_is_an_install_location(), \
             patch.object(app_paths, "APP_DIR", self.app_dir), \
             patch.object(app_paths, "default_user_data_dir", lambda: self.user_dir):
            path = app_paths.user_path("play_history.json")

        with open(path, encoding="utf-8") as handle:
            self.assertIn("user", handle.read())

    def test_read_only_assets_stay_with_the_application(self):
        self.assertEqual(os.path.dirname(app_paths.app_path("builtin_practice_types.json")),
                         app_paths.APP_DIR)
        self.assertTrue(app_paths.app_path("cues", "round_gap.ogg").endswith(
            os.path.join("cues", "round_gap.ogg")))

class TestDelayedWindowsPlay(unittest.TestCase):
    """A play scheduled 100ms ago must not start the wrong thing."""

    def setUp(self):
        self.player = MusicPlayer.__new__(MusicPlayer)
        self.player.sound = MagicMock()
        self.player.playlist_idx = 0
        self.player._playing_position = 0
        self.player._pending_play_event = None
        self.player._start_sound = MagicMock(return_value=True)
        self.scheduled = []

    def _schedule_on_windows(self):
        with patch("music_player.platform.system", return_value="Windows"), \
             patch("music_player.Clock.schedule_once",
                   side_effect=lambda cb, t: self.scheduled.append(cb) or MagicMock()):
            self.player._apply_platform_specific_play()
        return self.scheduled[-1]

    def test_delayed_play_starts_the_captured_sound(self):
        sound = self.player.sound
        self._schedule_on_windows()(0)
        self.player._start_sound.assert_called_once_with(sound, 0)

    def test_stop_during_the_delay_does_not_start_an_unloaded_sound(self):
        callback = self._schedule_on_windows()
        self.player.sound = None               # stop_sound ran meanwhile
        callback(0)
        self.player._start_sound.assert_not_called()

    def test_choosing_another_song_during_the_delay_does_not_start_the_old_one(self):
        callback = self._schedule_on_windows()
        self.player.sound = MagicMock()        # a different song was selected
        self.player.playlist_idx = 3
        callback(0)
        self.player._start_sound.assert_not_called()

    def test_a_second_schedule_cancels_the_first(self):
        events = [MagicMock(), MagicMock()]
        with patch("music_player.platform.system", return_value="Windows"), \
             patch("music_player.Clock.schedule_once", side_effect=events):
            self.player._apply_platform_specific_play()
            self.player._apply_platform_specific_play()
        events[0].cancel.assert_called_once()

    def test_stopping_cancels_a_pending_play(self):
        event = MagicMock()
        self.player._pending_play_event = event
        self.player._cancel_pending_play()
        event.cancel.assert_called_once()
        self.assertIsNone(self.player._pending_play_event)

    def test_backend_failure_is_contained_and_reported_by_the_caller(self):
        """_start_sound logs; the caller decides whether to report it."""
        player = MusicPlayer.__new__(MusicPlayer)
        player.show_error_popup = MagicMock()
        sound = MagicMock()
        sound.play.side_effect = RuntimeError("gstreamer exploded")
        self.assertFalse(player._start_sound(sound, 0))
        player.show_error_popup.assert_not_called()


class TestWorkerFailureRecovery(unittest.TestCase):
    """A failed generation must not leave the player permanently disabled."""

    def setUp(self):
        self.player = MusicPlayer.__new__(MusicPlayer)
        self.player._playlist_generation_in_progress = True
        self.player._generation_config = {"song_max_playtime": 210}
        self.player._regeneration_pending = True
        self.player._regeneration_start_playback = True
        self.player.playlist = [{"path": "/m/keep.mp3", "dance": "Waltz"}]
        self.player._display_playlist_buttons = MagicMock()
        self.player.show_error_popup = MagicMock()

    def test_exception_in_the_worker_is_caught_and_reported(self):
        self.player._build_playlist_in_background = MagicMock(
            side_effect=AttributeError("'list' object has no attribute 'get'"))
        with patch("music_player.Clock.schedule_once") as schedule:
            self.player._generate_playlist_in_background("/m", ["Waltz"], 2, True, False)
            schedule.assert_called_once()
            schedule.call_args[0][0](0)        # run the scheduled recovery

        self.assertFalse(self.player._playlist_generation_in_progress)
        self.assertIsNone(self.player._generation_config)
        self.assertFalse(self.player._regeneration_pending)
        self.player.show_error_popup.assert_called_once()

    def test_the_previous_playlist_is_kept(self):
        self.player._abort_playlist_generation(RuntimeError("boom"), 0)
        self.assertEqual(self.player.playlist, [{"path": "/m/keep.mp3", "dance": "Waltz"}])
        self.player._display_playlist_buttons.assert_called_once()

    def test_the_ui_is_re_enabled_so_the_player_is_usable(self):
        """The flag gates play/pause, song selection and New Playlist."""
        self.player._abort_playlist_generation(RuntimeError("boom"), 0)
        self.assertFalse(self.player._playlist_generation_in_progress)


class TestMalformedConfig(unittest.TestCase):
    """A bad music.ini must not create a startup loop restarting cannot fix."""

    def setUp(self):
        self.app = MusicApp.__new__(MusicApp)
        self.app.config = ConfigParser()
        self.app.config.add_section("user")

    def test_valid_values_are_read(self):
        self.app.config.set("user", "song_max_playtime", "150")
        self.assertEqual(self.app._config_number("user", "song_max_playtime", int, 210), 150)

    def test_malformed_value_falls_back_instead_of_raising(self):
        self.app.config.set("user", "song_max_playtime", "abc")
        self.app.config.write = MagicMock()
        self.assertEqual(self.app._config_number("user", "song_max_playtime", int, 210), 210)

    def test_malformed_value_is_repaired_in_the_file(self):
        self.app.config.set("user", "volume", "loud")
        self.app.config.write = MagicMock()
        self.app._config_number("user", "volume", float, 0.7)
        self.app.config.write.assert_called_once()
        self.assertEqual(self.app.config.get("user", "volume"), "0.7")

    def test_missing_value_uses_the_default(self):
        self.assertEqual(self.app._config_number("user", "volume", float, 0.7), 0.7)


class TestUnplayableSongs(unittest.TestCase):
    """A broken codec must not stack one popup per song."""

    def setUp(self):
        self.player = MusicPlayer.__new__(MusicPlayer)
        self.player.playlist = [{"path": f"/m/{i}.mp3", "dance": "Waltz"} for i in range(8)]
        self.player.playlist_idx = 0
        self.player.sound = None
        self.player._playing_position = 0
        self.player.show_error_popup = MagicMock()
        self.player._is_first_load = False

    def test_all_unplayable_are_skipped_in_one_pass(self):
        with patch("music_player.os.path.exists", return_value=True), \
             patch.object(self.player, "_load_sound", return_value=None):
            skipped = self.player._skip_unplayable_songs()
        self.assertEqual(len(skipped), 8)
        self.assertEqual(self.player.playlist_idx, 8)

    def test_stops_on_the_first_playable_song(self):
        good = MagicMock()
        loads = [None, None, good]
        with patch("music_player.os.path.exists", return_value=True), \
             patch.object(self.player, "_load_sound", side_effect=loads):
            skipped = self.player._skip_unplayable_songs()
        self.assertEqual(len(skipped), 2)
        self.assertEqual(self.player.playlist_idx, 2)
        self.assertIs(self.player.sound, good)

    def test_missing_files_are_reported_as_missing(self):
        with patch("music_player.os.path.exists", return_value=False):
            skipped = self.player._skip_unplayable_songs()
        self.assertTrue(all(reason == "not found" for _, reason in skipped))

    def test_one_consolidated_popup_not_one_per_song(self):
        self.player._report_skipped_songs([(f"/m/{i}.mp3", "not found") for i in range(8)])
        self.player.show_error_popup.assert_called_once()
        message = self.player.show_error_popup.call_args[0][0]
        self.assertIn("Skipped 8", message)
        self.assertIn("and 3 more", message)      # only the first five are listed

    def test_a_backend_exception_during_load_is_contained(self):
        with patch("music_player.SoundLoader.load", side_effect=RuntimeError("no codec")):
            self.assertIsNone(self.player._load_sound("/m/0.mp3"))


class TestUnexpectedStop(unittest.TestCase):
    """A stream ending early must not leave the player sitting there."""

    def setUp(self):
        self.player = MusicPlayer.__new__(MusicPlayer)
        self.player.sound = MagicMock()
        self.player.playlist = [{"path": "/m/a.mp3", "dance": "Waltz",
                                 "duration": 180, "max_playtime": 210, "fade_seconds": 10}]
        self.player.playlist_idx = 0
        self.player.play_single_song = False
        self.player.play_pause_button = MagicMock()
        self.player.progress_max = 180
        self.player._playing_position = 0
        self.player._schedule_interval = 0.1
        self.player._total_time = "03:00"
        self.player._playback_observed = False
        self.player._advance_playlist = MagicMock()
        self.player.stop_sound = MagicMock()
        self.player._get_icon_path = MagicMock(return_value="play.png")

    def test_stop_before_playback_started_is_not_treated_as_an_ending(self):
        """The Windows delayed start leaves the sound stopped for 100ms."""
        self.player.sound.state = "stop"
        self.player.update_progress(0.1)
        self.player._advance_playlist.assert_not_called()

    def test_backend_stopping_mid_playlist_advances(self):
        self.player.sound.state = "play"
        self.player.sound.get_pos.return_value = 120.0
        self.player.update_progress(0.1)          # observes playback
        self.assertTrue(self.player._playback_observed)

        self.player.sound.state = "stop"          # ended 60s before the tag said
        self.player.update_progress(0.1)
        self.player._advance_playlist.assert_called_once()

    def test_a_user_pause_does_not_advance(self):
        self.player.sound.state = "play"
        self.player.sound.get_pos.return_value = 60.0
        self.player.update_progress(0.1)
        self.player._cancel_pending_play = MagicMock()
        self.player.pause_sound()                 # clears the observed flag

        self.player.sound.state = "stop"
        self.player.update_progress(0.1)
        self.player._advance_playlist.assert_not_called()

    def test_play_single_song_stops_instead_of_advancing(self):
        self.player.play_single_song = True
        self.player._playback_observed = True
        self.player.sound.state = "stop"
        self.player.update_progress(0.1)
        self.player.stop_sound.assert_called_once()
        self.player._advance_playlist.assert_not_called()


class TestHistoryRobustness(unittest.TestCase):
    """Corrupt history must be discarded, and writes must be atomic."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "play_history.json")
        self.player = MusicPlayer.__new__(MusicPlayer)
        self.player._get_history_path = lambda: self.path

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, text):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def test_valid_history_is_loaded(self):
        self._write('{"Waltz": ["a.mp3"]}')
        self.assertEqual(self.player._load_play_history(), {"Waltz": ["a.mp3"]})

    def test_json_that_is_not_an_object_is_discarded(self):
        """Previously this reached the worker and raised AttributeError there."""
        for text in ('["Waltz"]', '"Waltz"', 'null', '42'):
            self._write(text)
            self.assertEqual(self.player._load_play_history(), {})

    def test_entries_that_are_not_lists_are_dropped(self):
        self._write('{"Waltz": ["a.mp3"], "Tango": "b.mp3", "Jive": null}')
        self.assertEqual(self.player._load_play_history(), {"Waltz": ["a.mp3"]})

    def test_truncated_json_is_discarded(self):
        self._write('{"Waltz": ["a.mp3"')
        self.assertEqual(self.player._load_play_history(), {})

    def test_save_is_atomic_and_leaves_no_temp_file(self):
        self.player._save_play_history({"Waltz": ["a.mp3"]})
        self.assertEqual(os.listdir(self.tmp), ["play_history.json"])
        self.assertEqual(self.player._load_play_history(), {"Waltz": ["a.mp3"]})

    def test_a_failed_save_leaves_the_previous_file_intact(self):
        self.player._save_play_history({"Waltz": ["good.mp3"]})
        with patch("music_player.json.dump", side_effect=OSError("disk full")):
            self.player._save_play_history({"Waltz": ["bad.mp3"]})
        self.assertEqual(self.player._load_play_history(), {"Waltz": ["good.mp3"]})


class TestUndecodableFilesAreExcluded(unittest.TestCase):
    """A file with no readable duration must never reach a playlist.

    The audio backend loads such a file and then segfaults on play(), which
    Python cannot catch, so the only defence is not selecting it.
    """

    def setUp(self):
        self.player = MusicPlayer.__new__(MusicPlayer)
        self.player.current_dance_max_playtimes = {}
        self.player.song_max_playtime = 210
        self.player._generation_config = None

    def _with_duration(self, duration):
        tags = {"duration": duration, "title": "T", "artist": "A",
                "album": "B", "genre": "G"}
        with patch.object(MusicPlayer, "_read_tags", return_value=tags):
            return self.player._create_song_info("/m/Waltz/x.mp3", "Waltz")

    def test_none_duration_is_rejected(self):
        self.assertIsNone(self._with_duration(None))

    def test_zero_duration_is_rejected(self):
        self.assertIsNone(self._with_duration(0))

    def test_a_readable_duration_is_accepted(self):
        info = self._with_duration(150.0)
        self.assertEqual(info['duration'], 150.0)

    def test_no_nominal_duration_is_invented(self):
        """The old behaviour substituted 300s for an unparsable file."""
        self.assertIsNone(self._with_duration(None))

    def test_an_unreadable_announcement_is_skipped_not_played(self):
        self.assertIsNone(self._with_duration(None))
        with patch.object(MusicPlayer, "_read_tags",
                          return_value={"duration": None, "title": None, "artist": None,
                                        "album": None, "genre": None}):
            self.assertIsNone(self.player._create_song_info("/a/Waltz.ogg", "announce"))

    def test_such_files_do_not_enter_a_generated_block(self):
        self.player.play_all_songs = False
        self.player.play_single_song = False
        self.player.current_dance_minutes = {}
        self.player.current_dance_adjustments = {}
        self.player.adjust_song_counts_for_playlist = False
        self.player._collect_music_files = MagicMock(
            return_value=["/m/Waltz/good.mp3", "/m/Waltz/bad.mp3"])
        self.player._load_play_history = MagicMock(return_value={})
        self.player._save_play_history = MagicMock()
        self.player._get_announce_path = MagicMock(return_value=None)

        def tags(path):
            return ({"duration": None} if "bad" in path
                    else {"duration": 150.0, "title": "T", "artist": "A",
                          "album": "B", "genre": "G"})
        with patch.object(MusicPlayer, "_read_tags", side_effect=tags):
            playlist = self.player._get_songs_for_dance("/m", "Waltz", 2, randomize=False)

        self.assertEqual([song['path'] for song in playlist], ["/m/Waltz/good.mp3"])


class TestFailedStartRecovery(unittest.TestCase):
    """A song that never starts must not leave the player showing Pause."""

    def setUp(self):
        self.player = MusicPlayer.__new__(MusicPlayer)
        self.player.sound = MagicMock()
        self.player.playlist = [{"path": f"/m/{i}.mp3", "dance": "Waltz",
                                 "duration": 180, "max_playtime": 210,
                                 "fade_seconds": 10} for i in range(6)]
        self.player.playlist_idx = 0
        self.player.play_single_song = False
        self.player.play_pause_button = MagicMock()
        self.player.progress_max = 180
        self.player._playing_position = 0
        self.player._schedule_interval = 0.1
        self.player._total_time = "03:00"
        self.player._playback_observed = False
        self.player._playback_requested_at = None
        self.player._consecutive_start_failures = 0
        self.player._pending_play_event = None
        self.player._get_icon_path = MagicMock(side_effect=lambda name: name)
        self.player._advance_playlist = MagicMock()
        self.player._unschedule_progress_update = MagicMock()
        self.player.show_error_popup = MagicMock()

    def test_failed_start_resets_the_button_and_moves_on(self):
        self.player._handle_failed_start()
        self.assertEqual(self.player.play_pause_button.background_normal,
                         PlayerConstants.ICON_PLAY)
        self.assertIsNone(self.player.sound)
        self.player._advance_playlist.assert_called_once()

    def test_repeated_failures_stop_rather_than_walk_the_playlist(self):
        for _ in range(PlayerConstants.MAX_CONSECUTIVE_START_FAILURES):
            self.player.sound = MagicMock()
            self.player._handle_failed_start()
        # The last one stops instead of advancing again.
        self.assertEqual(self.player._advance_playlist.call_count,
                         PlayerConstants.MAX_CONSECUTIVE_START_FAILURES - 1)
        self.player.show_error_popup.assert_called_once()

    def test_a_start_that_never_plays_is_detected_after_the_grace_period(self):
        """A decoder that gives up inside the first tick never sets _playback_observed."""
        self.player.sound.state = "stop"
        self.player._playback_requested_at = time.perf_counter()
        self.player.update_progress(0.1)          # still within the grace period
        self.player._advance_playlist.assert_not_called()

        self.player._playback_requested_at = (
            time.perf_counter() - PlayerConstants.PLAYBACK_START_GRACE - 0.1)
        self.player.update_progress(0.1)
        self.player._advance_playlist.assert_called_once()

    def test_the_windows_delay_is_not_mistaken_for_a_failed_start(self):
        self.player.sound.state = "stop"
        self.player._playback_requested_at = time.perf_counter() - 0.1
        self.player.update_progress(0.1)
        self.player._advance_playlist.assert_not_called()

    def test_a_successful_start_clears_the_failure_count(self):
        self.player._consecutive_start_failures = 2
        self.player.sound.state = "play"
        self.player.sound.get_pos.return_value = 5.0
        self.player.update_progress(0.1)
        self.assertEqual(self.player._consecutive_start_failures, 0)
        self.assertIsNone(self.player._playback_requested_at)

    def test_start_failure_is_acted_on_rather_than_ignored(self):
        """_apply_platform_specific_play must not drop a False from _start_sound."""
        self.player._start_sound = MagicMock(return_value=False)
        self.player._handle_failed_start = MagicMock()
        with patch("music_player.platform.system", return_value="Linux"):
            self.player._apply_platform_specific_play()
        self.player._handle_failed_start.assert_called_once()


    def test_only_the_aggregate_popup_is_shown(self):
        """A broken backend must not stack one popup per song plus a summary."""
        self.player._start_sound = MagicMock(return_value=False)
        for _ in range(PlayerConstants.MAX_CONSECUTIVE_START_FAILURES):
            self.player.sound = MagicMock()
            with patch("music_player.platform.system", return_value="Linux"):
                self.player._apply_platform_specific_play()
        self.player.show_error_popup.assert_called_once()

    def test_the_aggregate_popup_names_the_songs(self):
        self.player._start_sound = MagicMock(return_value=False)
        for index in range(PlayerConstants.MAX_CONSECUTIVE_START_FAILURES):
            self.player.playlist_idx = index
            self.player.sound = MagicMock()
            with patch("music_player.platform.system", return_value="Linux"):
                self.player._apply_platform_specific_play()
        message = self.player.show_error_popup.call_args[0][0]
        self.assertIn("0.mp3", message)
        self.assertIn("2.mp3", message)

    def test_stopping_breaks_the_run_of_failures(self):
        """Two failures then a deliberate stop must not make the next one the third."""
        self.player.sound = MagicMock()
        self.player._handle_failed_start()
        self.player.sound = MagicMock()
        self.player._handle_failed_start()
        self.assertEqual(self.player._consecutive_start_failures, 2)

        self.player._cancel_pending_play = MagicMock()
        self.player.progress_value = 0
        self.player.progress_text = ""
        self.player.stop_sound()
        self.assertEqual(self.player._consecutive_start_failures, 0)
        self.assertEqual(self.player._failed_start_songs, ())

        self.player.sound = MagicMock()
        self.player._handle_failed_start()
        self.player.show_error_popup.assert_not_called()


class TestBackendCallIsolation(unittest.TestCase):
    """Backend exceptions must not escape into Kivy's event loop."""

    def setUp(self):
        self.player = MusicPlayer.__new__(MusicPlayer)
        self.player.sound = MagicMock()
        self.player._playing_position = 42.0
        self.player._pending_play_event = None
        self.player._playback_observed = False
        self.player._playback_requested_at = None
        self.player.play_pause_button = MagicMock()
        self.player._get_icon_path = MagicMock(return_value="play.png")
        self.player.progress_value = 0
        self.player.progress_text = ""
        self.player._unschedule_progress_update = MagicMock()

    def test_stop_survives_a_backend_exception(self):
        self.player.sound.stop.side_effect = RuntimeError("backend gone")
        self.player.sound.unload.side_effect = RuntimeError("backend gone")
        self.player.stop_sound()                  # must not raise
        self.assertIsNone(self.player.sound)

    def test_position_read_falls_back_to_the_last_known_value(self):
        self.player.sound.get_pos.side_effect = RuntimeError("backend gone")
        self.assertEqual(self.player._sound_position(), 42.0)

    def test_seek_survives_a_backend_exception(self):
        self.player.sound.seek.side_effect = RuntimeError("backend gone")
        self.player._sound_seek(10)               # must not raise

    def test_unload_on_a_missing_sound_is_harmless(self):
        self.player.sound = None
        self.player._sound_unload()
        self.player._sound_stop()

    def test_setting_volume_survives_a_backend_exception(self):
        def boom(_value):
            raise RuntimeError("backend gone")
        type(self.player.sound).volume = property(lambda self: 1.0, boom)
        try:
            self.player._sound_set_volume(0.5)        # must not raise
        finally:
            del type(self.player.sound).volume

    def test_reading_volume_falls_back(self):
        type(self.player.sound).volume = property(
            lambda self: (_ for _ in ()).throw(RuntimeError("backend gone")))
        try:
            self.assertEqual(self.player._sound_volume(default=0.7), 0.7)
        finally:
            del type(self.player.sound).volume

    def test_volume_on_a_missing_sound_is_harmless(self):
        self.player.sound = None
        self.player._sound_set_volume(0.5)
        self.assertEqual(self.player._sound_volume(default=0.3), 0.3)



class TestPracticeTypeFileRobustness(unittest.TestCase):
    """Structurally invalid but syntactically valid JSON must not stop startup."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.custom = os.path.join(self.tmp, "custom_practice_types.json")
        self.builtin = os.path.join(self.tmp, "builtin_practice_types.json")
        with open(self.builtin, "w", encoding="utf-8") as handle:
            json.dump({"Builtin": {"dances": ["Waltz"]}}, handle)
        self.player = MusicPlayer.__new__(MusicPlayer)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _load(self, content):
        with open(self.custom, "w", encoding="utf-8") as handle:
            handle.write(content)
        with patch.object(app_paths, "app_path", lambda *p: self.builtin), \
             patch.object(app_paths, "user_path", lambda f, **k: self.custom):
            return self.player.load_custom_practice_types()

    def test_top_level_list_is_ignored_not_fatal(self):
        self.assertEqual(list(self._load("[]")), ["Builtin"])

    def test_top_level_string_is_ignored(self):
        self.assertEqual(list(self._load('"practice"')), ["Builtin"])

    def test_top_level_number_is_ignored(self):
        self.assertEqual(list(self._load("42")), ["Builtin"])

    def test_valid_file_still_loads(self):
        types = self._load('{"Mine": {"dances": ["Tango"]}}')
        self.assertEqual(sorted(types), ["Builtin", "Mine"])


class TestPracticeTypeNormalisation(unittest.TestCase):
    """Malformed fields must be repaired before they reach Kivy properties.

    A dict property assigned a list raises inside set_practice_type, on the UI
    thread during startup, where the worker recovery cannot help.
    """

    def _normalize(self, data):
        return MusicPlayer._normalize_practice_type("Test", data)

    def test_definition_that_is_not_an_object_is_skipped(self):
        self.assertIsNone(self._normalize([]))
        self.assertIsNone(self._normalize("practice"))
        self.assertIsNone(self._normalize(7))

    def test_dance_max_playtimes_as_a_list_becomes_empty(self):
        self.assertEqual(self._normalize({"dance_max_playtimes": []})["dance_max_playtimes"], {})

    def test_dance_adjustments_as_a_number_becomes_empty(self):
        self.assertEqual(self._normalize({"dance_adjustments": 5})["dance_adjustments"], {})

    def test_non_numeric_playtimes_are_dropped(self):
        clean = self._normalize({"dance_max_playtimes": {"Waltz": "long", "Tango": 150}})
        self.assertEqual(clean["dance_max_playtimes"], {"Tango": 150.0})

    def test_non_positive_playtimes_are_dropped(self):
        clean = self._normalize({"dance_max_playtimes": {"Waltz": 0, "Tango": -5}})
        self.assertEqual(clean["dance_max_playtimes"], {})

    def test_empty_dance_entries_are_removed(self):
        clean = self._normalize({"dances": ["Waltz", "", "  ", None, "Tango"]})
        self.assertEqual(clean["dances"], ["Waltz", "Tango"])

    def test_dances_not_a_list_becomes_empty(self):
        self.assertEqual(self._normalize({"dances": "Waltz"})["dances"], [])

    def test_num_selections_is_coerced_and_floored(self):
        self.assertEqual(self._normalize({"num_selections": "3"})["num_selections"], 3)
        self.assertEqual(self._normalize({"num_selections": 0})["num_selections"], 1)
        self.assertEqual(self._normalize({"num_selections": "many"})["num_selections"], 2)

    def test_segments_not_a_list_becomes_empty(self):
        self.assertEqual(self._normalize({"segments": {}})["segments"], [])

    def test_a_malformed_type_does_not_break_set_practice_type(self):
        """The end-to-end path: bad JSON in, no exception during startup."""
        player = MusicPlayer.__new__(MusicPlayer)
        player.practice_dances = {"default": ["Waltz"]}
        player.custom_practice_mapping = {}
        player.settings_json = [{"key": "practice_type", "options": []}]
        player.update_playlist = MagicMock()
        player.music_dir = ""
        player.load_custom_practice_types = MagicMock(return_value={
            "Bad": {"dances": ["Waltz"], "dance_max_playtimes": ["nonsense"],
                    "dance_adjustments": 5, "num_selections": -1},
        })
        player.merge_custom_practice_types()
        player.set_practice_type(None, "Bad")     # must not raise
        self.assertEqual(dict(player.current_dance_max_playtimes), {})
        self.assertEqual(player.num_selections, 1)


class TestSongCacheEntryValidation(unittest.TestCase):
    """A structurally corrupt cache must rebuild itself, not fail every run."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cache_path = os.path.join(self.tmp, "cache.json")
        self.song = os.path.join(self.tmp, "song.mp3")
        with open(self.song, "wb") as handle:
            handle.write(b"x" * 100)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, entry):
        with open(self.cache_path, "w", encoding="utf-8") as handle:
            json.dump({"version": 1, "songs": {self.song: entry}}, handle)

    def test_entry_that_is_not_an_object_is_discarded(self):
        self._write("not-a-dict")
        cache = SongCache(self.cache_path)
        self.assertEqual(len(cache), 0)
        self.assertIsNone(cache.get(self.song))

    def test_entry_that_is_a_list_is_discarded(self):
        self._write(["a"])
        self.assertIsNone(SongCache(self.cache_path).get(self.song))

    def test_non_numeric_mtime_is_discarded(self):
        self._write({"size": 100, "mtime": "soon", "duration": 100})
        self.assertIsNone(SongCache(self.cache_path).get(self.song))

    def test_missing_size_is_discarded(self):
        self._write({"mtime": 1.0, "duration": 100})
        self.assertIsNone(SongCache(self.cache_path).get(self.song))

    def test_good_entries_survive_alongside_bad_ones(self):
        good = os.path.join(self.tmp, "good.mp3")
        with open(good, "wb") as handle:
            handle.write(b"y" * 50)
        stat = os.stat(good)
        with open(self.cache_path, "w", encoding="utf-8") as handle:
            json.dump({"version": 1, "songs": {
                self.song: "broken",
                good: {"size": stat.st_size, "mtime": stat.st_mtime, "duration": 120.0,
                       "title": "T", "artist": "A", "album": "B", "genre": "G"},
            }}, handle)
        cache = SongCache(self.cache_path)
        self.assertEqual(len(cache), 1)
        self.assertEqual(cache.get(good)["duration"], 120.0)


class TestPlaySoundOrchestration(unittest.TestCase):
    """play_sound wires together loading, UI state and scheduled playback."""

    def setUp(self):
        self.player = MusicPlayer.__new__(MusicPlayer)
        self.player.playlist = [
            {"path": "/m/Waltz/a.mp3", "dance": "Waltz", "title": "A", "genre": "G",
             "artist": "Ar", "album": "Al", "duration": 150.0, "max_playtime": 210,
             "fade_seconds": 10},
            {"path": "/m/Tango/b.mp3", "dance": "Tango", "title": "B", "genre": "G",
             "artist": "Ar", "album": "Al", "duration": 160.0, "max_playtime": 210,
             "fade_seconds": 10},
        ]
        self.player.playlist_idx = 0
        self.player.volume = 0.6
        self.player.sound = MagicMock()
        self.player._playing_position = 0
        self.player._playback_observed = False
        self.player._playback_requested_at = None
        self.player.play_pause_button = MagicMock()
        self.player._get_icon_path = MagicMock(side_effect=lambda name: name)

        # The parts play_sound delegates to, each covered by its own tests.
        self.player._skip_unplayable_songs = MagicMock(return_value=[])
        self.player._report_skipped_songs = MagicMock()
        self.player._sound_state = MagicMock(return_value="stop")
        self.player._sound_stop = MagicMock()
        self.player._sound_set_volume = MagicMock()
        self.player._update_song_button_highlight = MagicMock()
        self.player._scroll_to_current_song = MagicMock()
        self.player._unschedule_progress_update = MagicMock()
        self.player._schedule_progress_update = MagicMock()
        self.player._apply_platform_specific_play = MagicMock()
        self.player.restart_playlist = MagicMock()

    def test_the_current_song_is_prepared_and_started(self):
        self.player.play_sound()
        self.assertEqual(self.player.music_file, "/m/Waltz/a.mp3")
        self.player._sound_set_volume.assert_called_once_with(0.6)
        self.player._schedule_progress_update.assert_called_once_with(150.0)
        self.player._apply_platform_specific_play.assert_called_once()

    def test_the_pause_icon_is_shown_once_playing(self):
        self.player.play_sound()
        self.assertEqual(self.player.play_pause_button.background_normal,
                         PlayerConstants.ICON_PAUSE)

    def test_the_title_and_highlight_follow_the_song(self):
        self.player.playlist_idx = 1
        self.player.play_sound()
        self.assertIn("B", self.player.song_title)
        self.player._update_song_button_highlight.assert_called_once()
        self.player._scroll_to_current_song.assert_called_once()

    def test_the_start_time_is_recorded_for_failure_detection(self):
        self.player.play_sound()
        self.assertIsNotNone(self.player._playback_requested_at)

    def test_a_previous_progress_schedule_is_cancelled_first(self):
        self.player.play_sound()
        self.player._unschedule_progress_update.assert_called_once()

    def test_a_song_already_playing_is_stopped_before_restarting(self):
        self.player._sound_state = MagicMock(return_value="play")
        self.player.sound.get_pos.return_value = 12.0
        self.player._sound_position = MagicMock(return_value=12.0)
        self.player.play_sound()
        self.player._sound_stop.assert_called_once()
        self.assertEqual(self.player._playing_position, 12.0)

    def test_an_empty_playlist_restarts_instead_of_playing(self):
        self.player.playlist = []
        self.player.play_sound()
        self.player.restart_playlist.assert_called_once()
        self.player._apply_platform_specific_play.assert_not_called()

    def test_running_off_the_end_restarts_instead_of_playing(self):
        self.player.playlist_idx = 5
        self.player.play_sound()
        self.player.restart_playlist.assert_called_once()

    def test_skipped_songs_are_reported_once(self):
        self.player._skip_unplayable_songs = MagicMock(
            return_value=[("/m/Waltz/bad.mp3", "not found")])
        self.player.play_sound()
        self.player._report_skipped_songs.assert_called_once()

    def test_a_playlist_of_only_unplayable_songs_stops_cleanly(self):
        def skip_everything():
            self.player.playlist_idx = len(self.player.playlist)
            return [("/m/Waltz/a.mp3", "not found"), ("/m/Tango/b.mp3", "not found")]
        self.player._skip_unplayable_songs = MagicMock(side_effect=skip_everything)
        self.player.play_sound()
        self.player.restart_playlist.assert_called_once()
        self.player._apply_platform_specific_play.assert_not_called()


class TestAdvanceAndEndOfPlaylist(unittest.TestCase):
    """What happens between songs, and when the playlist runs out."""

    def setUp(self):
        self.player = MusicPlayer.__new__(MusicPlayer)
        self.player.playlist = [{"path": "/m/a.mp3"}, {"path": "/m/b.mp3"}]
        self.player.playlist_idx = 0
        self.player.sound = MagicMock()
        self.player._playing_position = 55.0
        self.player._playback_observed = True
        self.player._pending_play_event = None
        self.player.auto_update_restart_playlist = False
        self.player._sound_unload = MagicMock()
        self.player._cancel_pending_play = MagicMock()
        self.player.play_sound = MagicMock()
        self.player.update_playlist = MagicMock()
        self.player.restart_playlist = MagicMock()

    def test_advancing_unloads_and_plays_the_next_song(self):
        self.player._advance_playlist()
        self.player._sound_unload.assert_called_once()
        self.assertEqual(self.player.playlist_idx, 1)
        self.assertIsNone(self.player.sound)
        self.assertEqual(self.player._playing_position, 0)
        self.player.play_sound.assert_called_once()

    def test_advancing_clears_playback_state(self):
        self.player._advance_playlist()
        self.player._cancel_pending_play.assert_called_once()
        self.assertFalse(self.player._playback_observed)

    def test_the_end_restarts_the_playlist_by_default(self):
        self.player.playlist_idx = 1
        self.player._advance_playlist()
        self.player.restart_playlist.assert_called_once()
        self.player.update_playlist.assert_not_called()

    def test_the_end_regenerates_when_auto_update_is_set(self):
        self.player.auto_update_restart_playlist = True
        self.player.playlist_idx = 1
        self.player._advance_playlist()
        self.player.update_playlist.assert_called_once_with(start_playback=True)
        self.player.restart_playlist.assert_not_called()


class TestGStreamerPriming(unittest.TestCase):
    """The Windows priming workaround, including its delayed cleanup."""

    def setUp(self):
        self.player = MusicPlayer.__new__(MusicPlayer)
        self.player.playlist = [{"path": "/m/a.mp3"}]
        self.temp_sound = MagicMock()
        self.player._sound_set_volume = MagicMock()

    def _prime(self):
        scheduled = []
        with patch("music_player.SoundLoader.load", return_value=self.temp_sound), \
             patch("music_player.Clock.schedule_once",
                   side_effect=lambda cb, t: scheduled.append(cb)):
            self.player._prime_gstreamer()
        return scheduled

    def test_priming_plays_silently_and_schedules_cleanup(self):
        scheduled = self._prime()
        self.player._sound_set_volume.assert_called_once_with(0, self.temp_sound)
        self.temp_sound.play.assert_called_once()
        self.assertEqual(len(scheduled), 1)

    def test_cleanup_stops_and_unloads(self):
        self.player._sound_stop = MagicMock(return_value=True)
        self.player._sound_unload = MagicMock(return_value=True)
        self._prime()[0](0)
        self.player._sound_stop.assert_called_once_with(self.temp_sound)
        self.player._sound_unload.assert_called_once_with(self.temp_sound)

    def test_a_failed_cleanup_does_not_claim_success(self):
        self.player._sound_stop = MagicMock(return_value=False)
        self.player._sound_unload = MagicMock(return_value=False)
        with patch("builtins.print") as printed:
            self._prime()[0](0)
        messages = " ".join(str(call) for call in printed.call_args_list)
        self.assertIn("cleanup failed", messages)
        self.assertNotIn("priming successful", messages)

    def test_an_empty_playlist_primes_nothing(self):
        self.player.playlist = []
        with patch("music_player.SoundLoader.load") as load:
            self.player._prime_gstreamer()
        load.assert_not_called()

    def test_a_load_failure_is_not_fatal(self):
        with patch("music_player.SoundLoader.load", return_value=None), \
             patch("music_player.Clock.schedule_once") as schedule:
            self.player._prime_gstreamer()          # must not raise
        schedule.assert_not_called()

    def test_a_backend_exception_is_not_fatal(self):
        with patch("music_player.SoundLoader.load", side_effect=OSError("no device")):
            self.player._prime_gstreamer()          # must not raise


class TestSettingsLifecycle(unittest.TestCase):
    """Loading settings at startup and applying them when they change."""

    def setUp(self):
        self.app = MusicApp.__new__(MusicApp)
        self.app.config = ConfigParser()
        self.app.config.add_section("user")
        self.app.config.write = MagicMock()

        self.player = MusicPlayer.__new__(MusicPlayer)
        self.player.volume_slider = MagicMock()
        self.player.settings_json = [{"key": "practice_type",
                                      "options": ["60min", "Comp Rounds"]}]
        self.player.update_settings_options = MagicMock()
        self.player.update_playlist = MagicMock()
        self.player.set_practice_type = MagicMock()
        self.player.set_volume = MagicMock()
        self.app.player_widget = self.player

    def _set(self, **values):
        for key, value in values.items():
            self.app.config.set("user", key, str(value))

    def test_settings_are_applied_at_startup(self):
        self._set(volume=0.4, music_dir="/music", song_max_playtime=180,
                  practice_type="Comp Rounds")
        self.app._load_config_settings()
        self.assertEqual(self.player.volume, 0.4)
        self.assertEqual(self.player.music_dir, "/music")
        self.assertEqual(self.player.song_max_playtime, 180)
        self.assertEqual(self.player.practice_type, "Comp Rounds")

    def test_an_unknown_practice_type_falls_back_and_is_rewritten(self):
        """A practice type deleted since last run, or one from the other fork."""
        self._set(volume=0.7, music_dir="/music", song_max_playtime=210,
                  practice_type="Something Removed")
        self.app._load_config_settings()
        self.assertEqual(self.player.practice_type, PlayerConstants.PRACTICE_TYPE_60_MIN)
        self.assertEqual(self.app.config.get("user", "practice_type"),
                         PlayerConstants.PRACTICE_TYPE_60_MIN)
        self.app.config.write.assert_called_once()

    def test_no_user_section_leaves_defaults_alone(self):
        app = MusicApp.__new__(MusicApp)
        app.config = ConfigParser()
        app.player_widget = self.player
        app._load_config_settings()             # must not raise

    def test_changing_the_volume_applies_it_immediately(self):
        self.app.on_config_change(self.app.config, "user", "volume", "0.25")
        self.assertEqual(self.player.volume, 0.25)
        self.player.set_volume.assert_called_once()
        self.assertEqual(self.player.volume_slider.value, 0.25)

    def test_an_invalid_volume_is_ignored_rather_than_raising(self):
        self.player.volume = 0.7
        self.app.on_config_change(self.app.config, "user", "volume", "loud")
        self.assertEqual(self.player.volume, 0.7)

    def test_changing_the_music_directory_rebuilds_the_playlist(self):
        self.app.on_config_change(self.app.config, "user", "music_dir", "/other")
        self.assertEqual(self.player.music_dir, "/other")
        self.player.update_playlist.assert_called_once()

    def test_changing_the_max_playtime_applies_it(self):
        self.app.on_config_change(self.app.config, "user", "song_max_playtime", "150")
        self.assertEqual(self.player.song_max_playtime, 150)

    def test_an_invalid_max_playtime_is_ignored(self):
        self.player.song_max_playtime = 210
        self.app.on_config_change(self.app.config, "user", "song_max_playtime", "ages")
        self.assertEqual(self.player.song_max_playtime, 210)

    def test_changing_the_practice_type_reapplies_it(self):
        self.app.on_config_change(self.app.config, "user", "practice_type", "Comp Rounds")
        self.assertEqual(self.player.practice_type, "Comp Rounds")
        self.player.set_practice_type.assert_called_once_with(None, "Comp Rounds")

    def test_an_unrecognised_key_is_ignored(self):
        self.app.on_config_change(self.app.config, "user", "mystery", "1")

    def test_other_sections_are_ignored(self):
        self.app.on_config_change(self.app.config, "kivy", "volume", "0.1")
        self.player.set_volume.assert_not_called()


class TestDanceAdjustmentValidation(unittest.TestCase):
    """Rule contents, not just the outer type.

    A string result reaches arithmetic in _get_adjusted_song_count, and a
    negative result makes _pick_songs walk the whole dance folder instead of
    rejecting the value.
    """

    def _validate(self, raw):
        return practice_type_rules.validate_dance_adjustments(raw)

    def test_known_string_rules_are_kept(self):
        for rule in practice_type_rules.ADJUSTMENT_RULES:
            self.assertEqual(self._validate({"Waltz": rule}), {"Waltz": rule})

    def test_an_unknown_string_rule_is_dropped(self):
        self.assertEqual(self._validate({"Waltz": "half"}), {})

    def test_a_valid_mapping_is_kept(self):
        rule = {"1": 0, "2": 1, "default": 2}
        self.assertEqual(self._validate({"PasoDoble": rule}), {"PasoDoble": rule})

    def test_a_non_numeric_result_is_dropped(self):
        self.assertEqual(self._validate({"Waltz": {"2": "two"}}), {})

    def test_a_negative_result_is_dropped(self):
        self.assertEqual(self._validate({"Waltz": {"2": -3}}), {})

    def test_a_boolean_result_is_dropped(self):
        self.assertEqual(self._validate({"Waltz": {"2": True}}), {})

    def test_a_nonsense_key_is_dropped_but_the_rest_kept(self):
        self.assertEqual(self._validate({"Waltz": {"two": 1, "3": 2}}),
                         {"Waltz": {"3": 2}})

    def test_a_rule_of_the_wrong_type_is_dropped(self):
        self.assertEqual(self._validate({"Waltz": 5}), {})
        self.assertEqual(self._validate({"Waltz": ["n-1"]}), {})

    def test_problems_are_reported_to_the_caller(self):
        problems = []
        self._validate_with = practice_type_rules.validate_dance_adjustments(
            {"Waltz": {"2": -1}}, problems.append)
        self.assertTrue(problems)
        self.assertIn("negative", problems[0])

    def test_a_bad_rule_cannot_reach_the_song_count(self):
        """End to end: the normalizer strips it before the player uses it."""
        clean = MusicPlayer._normalize_practice_type(
            "T", {"dance_adjustments": {"Waltz": {"2": -3}}, "adjust_song_counts": True})
        player = MusicPlayer.__new__(MusicPlayer)
        player._generation_config = None
        player.adjust_song_counts_for_playlist = True
        player.current_dance_adjustments = clean["dance_adjustments"]
        self.assertEqual(player._get_adjusted_song_count("Waltz", 2), 2)


class TestSegmentTimingValidation(unittest.TestCase):
    """Negative timings quietly break a round rather than failing loudly."""

    def test_a_negative_clip_length_is_rejected(self):
        self.assertEqual(
            MusicPlayer._validate_segments([{"round": ["Waltz"], "clip_seconds": -10}]), [])

    def test_a_zero_clip_length_is_rejected(self):
        self.assertEqual(
            MusicPlayer._validate_segments([{"round": ["Waltz"], "clip_seconds": 0.0}]),
            [{"round": ["Waltz"], "count": 1, "clip_seconds": None, "gap_seconds": 0,
              "announce": False, "label": None}])

    def test_a_negative_gap_is_rejected(self):
        """A negative gap looks for a cue named gap_-5 and silently finds none."""
        self.assertEqual(
            MusicPlayer._validate_segments([{"round": ["Waltz"], "gap_seconds": -5}]), [])

    def test_a_zero_gap_is_allowed(self):
        segments = MusicPlayer._validate_segments([{"round": ["Waltz"], "gap_seconds": 0}])
        self.assertEqual(segments[0]["gap_seconds"], 0)

    def test_an_empty_dance_name_rejects_the_segment(self):
        self.assertEqual(MusicPlayer._validate_segments([{"round": ["", "Waltz"]}]), [])

    def test_a_non_string_dance_name_rejects_the_segment(self):
        self.assertEqual(MusicPlayer._validate_segments([{"round": ["Waltz", 7]}]), [])

    def test_a_valid_round_still_passes(self):
        segments = MusicPlayer._validate_segments(
            [{"round": ["Waltz", "Tango"], "count": 2, "clip_seconds": 100,
              "gap_seconds": 20}])
        self.assertEqual(segments[0]["clip_seconds"], 100.0)
        self.assertEqual(segments[0]["count"], 2)


class TestBooleanNormalisation(unittest.TestCase):
    """bool("false") is true, which is the mistake a hand-edited file makes."""

    def test_the_string_false_does_not_become_true(self):
        clean = MusicPlayer._normalize_practice_type("T", {"play_all_songs": "false"})
        self.assertFalse(clean["play_all_songs"])

    def test_the_string_true_does_not_become_true_either(self):
        """Not a boolean, so the documented default is used rather than guessing."""
        clean = MusicPlayer._normalize_practice_type("T", {"play_all_songs": "true"})
        self.assertFalse(clean["play_all_songs"])

    def test_a_field_defaulting_to_true_keeps_its_default(self):
        clean = MusicPlayer._normalize_practice_type("T", {"randomize_playlist": "no"})
        self.assertTrue(clean["randomize_playlist"])

    def test_real_booleans_are_left_alone(self):
        clean = MusicPlayer._normalize_practice_type(
            "T", {"play_all_songs": True, "randomize_playlist": False})
        self.assertTrue(clean["play_all_songs"])
        self.assertFalse(clean["randomize_playlist"])

    def test_a_numeric_boolean_uses_the_default(self):
        clean = MusicPlayer._normalize_practice_type("T", {"auto_update": 1})
        self.assertFalse(clean["auto_update"])


class TestInvalidTypesAreNotOffered(unittest.TestCase):
    """A definition that had to be skipped must not appear selectable."""

    def setUp(self):
        self.player = MusicPlayer.__new__(MusicPlayer)
        self.player.practice_dances = {"default": ["Waltz"]}
        self.player.custom_practice_mapping = {}
        self.player.settings_json = [{"key": "practice_type", "options": []}]
        self.player.practice_type = PlayerConstants.PRACTICE_TYPE_60_MIN
        self.player.load_custom_practice_types = MagicMock(return_value={
            "Good": {"dances": ["Waltz"]},
            "Broken": [],
        })

    def _options(self):
        return self.player.settings_json[0]["options"]

    def test_a_skipped_definition_is_not_added_to_the_settings_list(self):
        self.player.merge_custom_practice_types()
        self.assertIn("Good", self._options())
        self.assertNotIn("Broken", self._options())

    def test_a_skipped_definition_has_no_mapping(self):
        self.player.merge_custom_practice_types()
        self.assertIn("Good", self.player.custom_practice_mapping)
        self.assertNotIn("Broken", self.player.custom_practice_mapping)

    def test_update_settings_options_filters_too(self):
        self.player.update_settings_options()
        self.assertIn("Good", self._options())
        self.assertNotIn("Broken", self._options())

    def test_the_options_list_and_the_mappings_agree(self):
        """Anything offered must be selectable without falling back to default."""
        self.player.merge_custom_practice_types()
        custom = [name for name in self._options()
                  if name not in (PlayerConstants.PRACTICE_TYPE_60_MIN,
                                  PlayerConstants.PRACTICE_TYPE_NC_60_MIN)]
        for name in custom:
            self.assertIn(name, self.player.custom_practice_mapping)


class TestAppPathsPlatforms(unittest.TestCase):
    """The per-user directory differs per platform."""

    def test_windows_uses_appdata(self):
        with patch.object(app_paths.sys, "platform", "win32"), \
             patch.dict(os.environ, {"APPDATA": r"C:\Users\me\AppData\Roaming"}):
            self.assertTrue(app_paths.default_user_data_dir().startswith(
                r"C:\Users\me\AppData\Roaming"))

    def test_windows_without_appdata_falls_back_to_home(self):
        with patch.object(app_paths.sys, "platform", "win32"), \
             patch.dict(os.environ, {}, clear=True):
            self.assertIn(app_paths.APP_NAME, app_paths.default_user_data_dir())

    def test_macos_uses_application_support(self):
        with patch.object(app_paths.sys, "platform", "darwin"):
            self.assertIn("Application Support", app_paths.default_user_data_dir())

    def test_linux_honours_xdg_config_home(self):
        with patch.object(app_paths.sys, "platform", "linux"), \
             patch.dict(os.environ, {"XDG_CONFIG_HOME": "/tmp/xdg"}):
            self.assertEqual(app_paths.default_user_data_dir(),
                             os.path.join("/tmp/xdg", app_paths.APP_NAME))

    def test_linux_without_xdg_uses_dot_config(self):
        with patch.object(app_paths.sys, "platform", "linux"), \
             patch.dict(os.environ, {}, clear=True):
            self.assertIn(os.path.join(".config", app_paths.APP_NAME),
                          app_paths.default_user_data_dir())


class TestAppPathsFallbackFailures(unittest.TestCase):
    """What happens when even the fallback cannot be used."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.app_dir = os.path.join(self.tmp, "app")
        os.makedirs(self.app_dir)
        app_paths.reset()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        app_paths.reset()

    def _app_dir_is_not_writable(self):
        """Makes the permission check report the application directory read-only."""
        return patch.object(
            app_paths, "directory_is_writable",
            side_effect=lambda directory: os.path.abspath(directory) != os.path.abspath(
                self.app_dir))

    def test_an_uncreatable_fallback_falls_back_to_the_app_directory(self):
        with self._app_dir_is_not_writable(), \
             patch.object(app_paths.os, "makedirs", side_effect=OSError("read-only")):
            self.assertEqual(
                app_paths.state_dir(self.app_dir, os.path.join(self.tmp, "user")),
                self.app_dir)

    def test_a_failed_seed_copy_still_returns_a_usable_path(self):
        user_dir = os.path.join(self.tmp, "user")
        os.makedirs(user_dir)
        with open(os.path.join(self.app_dir, "play_history.json"), "w",
                  encoding="utf-8") as handle:
            handle.write("{}")

        with self._app_dir_is_not_writable(), \
             patch.object(app_paths, "APP_DIR", self.app_dir), \
             patch.object(app_paths, "default_user_data_dir", lambda: user_dir), \
             patch.object(app_paths.shutil, "copyfile", side_effect=OSError("nope")):
            path = app_paths.user_path("play_history.json")

        self.assertEqual(os.path.dirname(path), user_dir)
        self.assertFalse(os.path.exists(path))


class TestHistoryMemberValidation(unittest.TestCase):
    """History entries end up in a set, so their members must be hashable paths."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "play_history.json")
        self.player = MusicPlayer.__new__(MusicPlayer)
        self.player._get_history_path = lambda: self.path

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, data):
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(data, handle)

    def test_a_dict_inside_a_history_list_is_dropped(self):
        self._write({"Waltz": [{}, "a.mp3"]})
        self.assertEqual(self.player._load_play_history(), {"Waltz": ["a.mp3"]})

    def test_a_list_inside_a_history_list_is_dropped(self):
        self._write({"Waltz": [["nested"], "a.mp3"]})
        self.assertEqual(self.player._load_play_history(), {"Waltz": ["a.mp3"]})

    def test_numbers_and_nulls_are_dropped(self):
        self._write({"Waltz": [5, None, "a.mp3", True]})
        self.assertEqual(self.player._load_play_history(), {"Waltz": ["a.mp3"]})

    def test_an_entry_of_only_bad_members_becomes_empty(self):
        self._write({"Waltz": [{}, 5]})
        self.assertEqual(self.player._load_play_history(), {"Waltz": []})

    def test_valid_history_is_untouched(self):
        self._write({"Waltz": ["a.mp3", "b.mp3"], "Tango": []})
        self.assertEqual(self.player._load_play_history(),
                         {"Waltz": ["a.mp3", "b.mp3"], "Tango": []})

    def test_a_bad_member_cannot_reach_the_selector(self):
        """Previously raised "unhashable type: dict" inside the worker."""
        self._write({"Waltz": [{}, "played.mp3"]})
        history = self.player._load_play_history()
        candidates = self.player._draw_candidates(
            ["played.mp3", "fresh.mp3"], "Waltz", history)
        self.assertEqual(candidates[0], "fresh.mp3")


class TestStrictSegmentBooleans(unittest.TestCase):
    """Segments must use the same strict boolean rule as the top-level fields."""

    def test_the_string_false_does_not_enable_announcements(self):
        segments = MusicPlayer._validate_segments(
            [{"round": ["Waltz"], "announce": "false"}])
        self.assertFalse(segments[0]["announce"])

    def test_the_string_true_does_not_enable_them_either(self):
        segments = MusicPlayer._validate_segments(
            [{"round": ["Waltz"], "announce": "true"}])
        self.assertFalse(segments[0]["announce"])

    def test_a_real_boolean_is_honoured(self):
        segments = MusicPlayer._validate_segments(
            [{"round": ["Waltz"], "announce": True}])
        self.assertTrue(segments[0]["announce"])

    def test_a_boolean_count_is_rejected_rather_than_becoming_one(self):
        self.assertEqual(
            MusicPlayer._validate_segments([{"round": ["Waltz"], "count": True}]), [])

    def test_a_boolean_num_selections_is_rejected(self):
        clean = MusicPlayer._normalize_practice_type("T", {"num_selections": True})
        self.assertEqual(clean["num_selections"], 2)

    def test_a_boolean_clip_length_is_rejected(self):
        self.assertEqual(
            MusicPlayer._validate_segments(
                [{"round": ["Waltz"], "clip_seconds": True}]), [])


class TestApplicationSmoke(unittest.TestCase):
    """Build the real application against its real JSON files.

    This is the widget construction that unit tests deliberately skip: it is not
    worth asserting over line by line, but it must not raise, and a practice type
    file that the validators reject must not stop the app being built.
    """

    def test_the_app_builds_its_screen_tree(self):
        app = MusicApp()
        try:
            root = app.build()
            self.assertIsNotNone(root.get_screen("player"))
            self.assertIsNotNone(root.get_screen("editor"))
            player = app.player_widget
            self.assertTrue(player.playlist_button)
            self.assertTrue(player.button_grid)
            self.assertTrue(player.volume_slider)
        finally:
            app.stop()

    def test_the_shipped_practice_types_all_survive_validation(self):
        """Every type the player offers must have a usable definition."""
        player = MusicPlayer.__new__(MusicPlayer)
        valid = player._valid_practice_types()
        raw = player.load_custom_practice_types()
        self.assertEqual(sorted(valid), sorted(raw),
                         "a shipped practice type was rejected by validation")
        self.assertIn("Comp Rounds", valid)
        self.assertIn("Silver+ Std 60min Timed", valid)

    def test_the_shipped_segments_and_budgets_validate(self):
        player = MusicPlayer.__new__(MusicPlayer)
        types = player._valid_practice_types()
        rounds = types["Comp Rounds"]
        self.assertEqual(len(MusicPlayer._validate_segments(rounds["segments"])),
                         len(rounds["segments"]))
        timed = types["Silver+ Std 60min Timed"]
        self.assertEqual(
            MusicPlayer._validate_dance_minutes(timed["dance_minutes"], timed["dances"]),
            {name: float(value) for name, value in timed["dance_minutes"].items()})


class TestNonFiniteNumbers(unittest.TestCase):
    """Python's JSON parser accepts Infinity and NaN; the validators must not."""

    def test_infinite_num_selections_does_not_crash_loading(self):
        """int(inf) raises OverflowError, which used to escape validation."""
        clean = MusicPlayer._normalize_practice_type(
            "T", {"num_selections": float("inf")})
        self.assertEqual(clean["num_selections"], 2)

    def test_negative_infinity_and_nan_are_rejected(self):
        for value in (float("-inf"), float("nan")):
            clean = MusicPlayer._normalize_practice_type("T", {"num_selections": value})
            self.assertEqual(clean["num_selections"], 2)

    def test_an_infinite_count_rejects_the_segment(self):
        self.assertEqual(
            MusicPlayer._validate_segments(
                [{"round": ["Waltz"], "count": float("inf")}]), [])

    def test_an_infinite_clip_length_rejects_the_segment(self):
        self.assertEqual(
            MusicPlayer._validate_segments(
                [{"round": ["Waltz"], "clip_seconds": float("inf")}]), [])

    def test_an_infinite_max_playtime_is_dropped(self):
        clean = MusicPlayer._normalize_practice_type(
            "T", {"dance_max_playtimes": {"Waltz": float("inf")}})
        self.assertEqual(clean["dance_max_playtimes"], {})

    def test_an_infinite_block_budget_is_dropped(self):
        """An infinite budget would make a timed block use the whole folder."""
        self.assertEqual(
            MusicPlayer._validate_dance_minutes({"Waltz": float("inf")}, ["Waltz"]), {})

    def test_a_json_file_containing_infinity_loads_safely(self):
        """json.loads accepts the literal Infinity, so this reaches validation."""
        data = json.loads('{"num_selections": Infinity, "dances": ["Waltz"]}')
        clean = MusicPlayer._normalize_practice_type("T", data)
        self.assertEqual(clean["num_selections"], 2)


class TestFractionalNumbers(unittest.TestCase):
    """Counts are whole; durations are not."""

    def test_a_fractional_count_is_rejected_not_truncated(self):
        self.assertEqual(
            MusicPlayer._validate_segments([{"round": ["Waltz"], "count": 1.9}]), [])

    def test_a_fractional_gap_is_rejected(self):
        self.assertEqual(
            MusicPlayer._validate_segments(
                [{"round": ["Waltz"], "gap_seconds": 2.9}]), [])

    def test_a_fractional_num_selections_is_rejected(self):
        clean = MusicPlayer._normalize_practice_type("T", {"num_selections": 3.5})
        self.assertEqual(clean["num_selections"], 2)

    def test_a_whole_number_written_as_a_float_is_accepted(self):
        clean = MusicPlayer._normalize_practice_type("T", {"num_selections": 4.0})
        self.assertEqual(clean["num_selections"], 4)

    def test_a_fractional_clip_length_is_kept(self):
        """A clip length is a duration, so fractions of a second are meaningful."""
        segments = MusicPlayer._validate_segments(
            [{"round": ["Waltz"], "clip_seconds": 90.5}])
        self.assertEqual(segments[0]["clip_seconds"], 90.5)

    def test_a_fractional_block_budget_is_kept(self):
        self.assertEqual(
            MusicPlayer._validate_dance_minutes({"Waltz": 8.5}, ["Waltz"]), {"Waltz": 8.5})

    def test_a_fractional_max_playtime_is_kept(self):
        clean = MusicPlayer._normalize_practice_type(
            "T", {"dance_max_playtimes": {"Waltz": 150.5}})
        self.assertEqual(clean["dance_max_playtimes"], {"Waltz": 150.5})


class TestEnormousAndPreciseNumbers(unittest.TestCase):
    """JSON integers have no size limit, and floats have 53 bits of precision."""

    def test_an_integer_too_large_for_a_float_is_rejected(self):
        """float(10**400) raises OverflowError, which used to escape validation."""
        self.assertIsNone(practice_type_rules.strict_number(10 ** 400, "value"))

    def test_an_enormous_num_selections_does_not_crash_loading(self):
        clean = MusicPlayer._normalize_practice_type("T", {"num_selections": 10 ** 400})
        self.assertEqual(clean["num_selections"], 10 ** 400)

    def test_an_enormous_playtime_is_dropped(self):
        clean = MusicPlayer._normalize_practice_type(
            "T", {"dance_max_playtimes": {"Waltz": 10 ** 400}})
        self.assertEqual(clean["dance_max_playtimes"], {})

    def test_an_enormous_clip_length_rejects_the_segment(self):
        self.assertEqual(
            MusicPlayer._validate_segments(
                [{"round": ["Waltz"], "clip_seconds": 10 ** 400}]), [])

    def test_an_enormous_block_budget_is_dropped(self):
        self.assertEqual(
            MusicPlayer._validate_dance_minutes({"Waltz": 10 ** 400}, ["Waltz"]), {})

    def test_a_large_integer_keeps_its_exact_value(self):
        """Going through float would return ...992."""
        self.assertEqual(
            practice_type_rules.strict_int(9007199254740993, "count"), 9007199254740993)

    def test_a_large_count_survives_segment_validation_exactly(self):
        segments = MusicPlayer._validate_segments(
            [{"round": ["Waltz"], "count": 9007199254740993}])
        self.assertEqual(segments[0]["count"], 9007199254740993)

    def test_booleans_are_still_rejected_by_the_integer_path(self):
        self.assertIsNone(practice_type_rules.strict_int(True, "count"))
        self.assertIsNone(practice_type_rules.strict_int(False, "count"))

    def test_ordinary_integers_are_unaffected(self):
        self.assertEqual(practice_type_rules.strict_int(4, "count"), 4)
        self.assertEqual(practice_type_rules.strict_int(-2, "count"), -2)
        self.assertEqual(practice_type_rules.strict_int("7", "count"), 7)


class TestCaseInsensitiveLookup(unittest.TestCase):
    """Folder and file names match without regard to case, on every platform.

    Windows and macOS do this themselves; Linux does not, so a library built on
    one and used on the other would silently lose a whole dance. "QuickStep"
    against a "Quickstep" folder is the case that prompted it.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.music = os.path.join(self.tmp, "music")
        os.makedirs(self.music)
        self.player = MusicPlayer.__new__(MusicPlayer)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_dance(self, folder_name, songs=2):
        folder = os.path.join(self.music, folder_name)
        os.makedirs(folder, exist_ok=True)
        for index in range(songs):
            with open(os.path.join(folder, f"{index}.mp3"), "wb") as handle:
                handle.write(b"x")
        return folder

    def test_a_differently_cased_folder_is_found(self):
        self._make_dance("quickstep", songs=3)
        self.assertEqual(len(self.player._collect_music_files(self.music, "QuickStep")), 3)

    def test_an_upper_case_folder_is_found(self):
        self._make_dance("WALTZ", songs=2)
        self.assertEqual(len(self.player._collect_music_files(self.music, "Waltz")), 2)

    def _require_case_sensitivity(self):
        if not filesystem_is_case_sensitive(self.tmp):
            self.skipTest("this filesystem cannot hold two names differing only "
                          "in case, so the situation cannot arise here")

    def test_an_exact_match_still_wins(self):
        self._require_case_sensitivity()
        self._make_dance("Waltz", songs=2)
        self._make_dance("waltz", songs=5)
        found = self.player._collect_music_files(self.music, "Waltz")
        self.assertEqual(len(found), 2, "the exact spelling must be preferred")

    def test_an_ambiguous_match_is_stable_and_warned_about(self):
        self._require_case_sensitivity()
        self._make_dance("Quickstep", songs=1)
        self._make_dance("quickstep", songs=3)
        first = self.player._collect_music_files(self.music, "QuickStep")
        second = self.player._collect_music_files(self.music, "QuickStep")
        self.assertEqual(len(first), 1, "picks the first by name, not by directory order")
        self.assertEqual(first, second, "and picks the same one every time")

    def test_the_selection_rule_prefers_an_exact_match(self):
        """The rule itself, without needing two real folders to exist."""
        with patch("music_player.os.listdir",
                   return_value=["quickstep", "QuickStep", "Quickstep"]), \
             patch("music_player.os.path.isdir", return_value=True):
            chosen = self.player._entry_ignoring_case(
                self.music, "QuickStep", want_dir=True)
        self.assertEqual(os.path.basename(chosen), "QuickStep")

    def test_the_selection_rule_is_stable_without_an_exact_match(self):
        with patch("music_player.os.listdir",
                   return_value=["quickstep", "Quickstep"]), \
             patch("music_player.os.path.isdir",
                   side_effect=lambda path: not path.endswith("QuickStep")):
            chosen = self.player._entry_ignoring_case(
                self.music, "QuickStep", want_dir=True)
        self.assertEqual(os.path.basename(chosen), "Quickstep",
                         "the first by name, not by directory order")

    def test_the_selection_rule_warns_when_it_has_to_choose(self):
        with patch("music_player.os.listdir",
                   return_value=["quickstep", "Quickstep"]), \
             patch("music_player.os.path.isdir",
                   side_effect=lambda path: not path.endswith("QuickStep")), \
             patch("music_player.Logger.warning") as warned:
            self.player._entry_ignoring_case(self.music, "QuickStep", want_dir=True)
        self.assertTrue(warned.called)
        self.assertIn("differing only in case", warned.call_args[0][0])

    def test_a_directory_is_not_matched_when_a_file_is_wanted(self):
        os.makedirs(os.path.join(self.music, "Waltz.ogg"))
        self.assertIsNone(
            self.player._entry_ignoring_case(self.music, "Waltz.ogg", want_dir=False))

    def test_a_missing_dance_is_still_missing(self):
        self._make_dance("Waltz")
        self.assertEqual(self.player._collect_music_files(self.music, "Tango"), [])

    def test_a_file_is_not_mistaken_for_a_dance_folder(self):
        with open(os.path.join(self.music, "Waltz"), "wb") as handle:
            handle.write(b"not a folder")
        self.assertEqual(self.player._collect_music_files(self.music, "Waltz"), [])

    def test_announcements_are_found_regardless_of_case(self):
        for spelling in ("quickstep", "QUICKSTEP", "QuickStep"):
            path = self.player._get_announce_path(spelling)
            self.assertIsNotNone(path)
            self.assertTrue(os.path.basename(path).lower().startswith("quickstep"),
                            f"{spelling} found {path}")

    def test_an_unknown_dance_still_falls_back_to_the_generic_announcement(self):
        path = self.player._get_announce_path("NoSuchDance")
        self.assertEqual(os.path.basename(path), "Generic.ogg")

    def test_cue_audio_is_found_regardless_of_case(self):
        self.assertIsNotNone(self.player._get_cue_path("ROUND_GAP"))
        self.assertIsNotNone(self.player._get_cue_path("Gap_20"))

    def test_a_missing_cue_is_still_missing(self):
        self.assertIsNone(self.player._get_cue_path("no_such_cue"))


if __name__ == '__main__':
    # The verbosity argument increases the detail of the test output.
    unittest.main(verbosity=2)
