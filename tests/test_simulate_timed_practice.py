"""Tests for utils/simulate_timed_practice.py.

The simulator is only useful while it models what the player does: the same
practice type definition and the same block planner.

To run these tests:
    python -m pytest tests/test_simulate_timed_practice.py
"""
import argparse
import contextlib
import io
import json
import math
import os
import shutil
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "utils"))

# pylint: disable=wrong-import-position
import simulate_timed_practice as script
import app_paths
import practice_type_rules


class TestLoadingThePracticeType(unittest.TestCase):
    """The simulated type comes from the same files the player reads."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.builtin_path = os.path.join(self.tmp, "builtin_practice_types.json")
        self.custom_path = os.path.join(self.tmp, "custom_practice_types.json")
        self.write(self.builtin_path, {
            "Timed": {"dances": ["Waltz", "Tango"],
                      "dance_minutes": {"Waltz": 13.5, "Tango": 10},
                      "dance_max_playtimes": {"Tango": 150}},
        })

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    @staticmethod
    def write(path, data):
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle)

    def load(self, name="Timed"):
        return script.load_practice_type(name, self.builtin_path, self.custom_path)

    def test_minutes_and_caps_are_taken_from_the_definition(self):
        practice = self.load()
        self.assertEqual(practice.dance_minutes, {"Waltz": 13.5, "Tango": 10.0})
        self.assertEqual(practice.dance_caps, {"Tango": 150.0})
        self.assertEqual(practice.total_minutes, 23.5)

    def test_without_its_own_minimum_the_player_default_is_used(self):
        self.assertEqual(self.load().min_play,
                         practice_type_rules.DEFAULT_MIN_SONG_PLAY_SECONDS)

    def test_a_custom_definition_overrides_the_builtin_one(self):
        self.write(self.custom_path, {
            "Timed": {"dances": ["Waltz"], "dance_minutes": {"Waltz": 20},
                      "min_song_play_seconds": 120},
        })
        practice = self.load()
        self.assertEqual(practice.dance_minutes, {"Waltz": 20.0})
        self.assertEqual(practice.min_play, 120)

    def test_minutes_for_a_dance_the_type_does_not_play_are_ignored(self):
        """The player ignores them; counting them would rescale every block."""
        self.write(self.custom_path, {
            "Timed": {"dances": ["Waltz"],
                      "dance_minutes": {"Waltz": 13, "Wlatz": 13}},
        })
        self.assertEqual(self.load().dance_minutes, {"Waltz": 13.0})

    def test_an_untimed_type_is_refused(self):
        self.write(self.custom_path, {"Untimed": {"dances": ["Waltz"]}})
        with self.assertRaises(ValueError):
            self.load("Untimed")

    def test_an_unknown_type_is_refused(self):
        with self.assertRaises(ValueError):
            self.load("No Such Type")

    def test_a_repeated_dance_is_a_block_per_listing(self):
        self.write(self.custom_path, {
            "Timed": {"dances": ["Waltz", "Tango", "Waltz"],
                      "dance_minutes": {"Waltz": 5, "Tango": 5}},
        })
        practice = self.load()
        self.assertEqual(practice.blocks, ["Waltz", "Tango", "Waltz"])
        self.assertEqual(practice.block_labels, ["Waltz #1", "Tango", "Waltz #2"])
        self.assertEqual(practice.total_minutes, 15)
        pools = {dance: [script.Song(path=f"{dance}/{i}.mp3", duration=100.0) for i in range(12)]
                 for dance in ("Waltz", "Tango")}
        row = script.compact_scenario(practice, pools, 2, 1, 210.0, 0.0, 90, 20)
        self.assertAlmostEqual(row["mean_runtime"], 1200.0)

    def test_a_repeated_dance_draws_unused_songs_first(self):
        practice = script.PracticeType(name="T", dance_minutes={"Waltz": 200 / 60},
                                       dance_caps={}, min_play=90)
        pool = [script.Song(path=f"Waltz/{i}.mp3", duration=100.0) for i in range(4)]
        first = script.simulate_block(practice, "Waltz", pool, script.random.Random(1),
                                      210.0, 0.0, 90, 200 / 60)
        taken = {song.path for song in first.songs}
        second = script.simulate_block(practice, "Waltz", pool, script.random.Random(1),
                                       210.0, 0.0, 90, 200 / 60, taken)
        self.assertFalse(taken & {song.path for song in second.songs})

    def test_an_unreadable_custom_file_leaves_the_builtin_types(self):
        with open(self.custom_path, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        with contextlib.redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(self.load().dance_minutes, {"Waltz": 13.5, "Tango": 10.0})
        self.assertIn("ignoring it", errors.getvalue())

    def test_the_default_type_is_shipped(self):
        practice = script.load_practice_type(
            script.DEFAULT_PRACTICE_TYPE,
            app_paths.app_path("builtin_practice_types.json"), self.custom_path)
        self.assertTrue(practice.dance_minutes)


class TestSharedWithThePlayer(unittest.TestCase):
    """The script repeats a couple of the player's values to avoid importing Kivy."""

    def test_the_fade_matches_the_player(self):
        from music_player import PlayerConstants
        self.assertEqual(script.FADE_SECONDS, PlayerConstants.FADE_TIME)

    def test_the_default_cap_matches_the_player(self):
        from music_player import PlayerConstants
        self.assertEqual(script.DEFAULT_GLOBAL_CAP,
                         PlayerConstants.DEFAULT_SONG_MAX_PLAYTIME)

    def test_a_block_shorter_than_its_intro_plays_the_intro_alone(self):
        practice = script.PracticeType(
            name="Short", dance_minutes={"Waltz": 0.1}, dance_caps={}, min_play=90)
        pool = [script.Song(path="Waltz/a.mp3", duration=100.0)]
        result = script.simulate_block(
            practice, "Waltz", pool, script.random.Random(1), 210.0, 10.0, 90, 0.1)
        self.assertEqual(result.songs, [])
        self.assertEqual(result.actual_seconds, 10.0)

    def test_a_comparison_of_intro_only_blocks_reports_no_songs(self):
        """Every block is its intro alone, so there is no song to measure."""
        practice = script.PracticeType(
            name="Short", dance_minutes={"Waltz": 0.1}, dance_caps={}, min_play=90)
        pools = {"Waltz": [script.Song(path="Waltz/a.mp3", duration=100.0)]}
        args = argparse.Namespace(runs=3, seed=1, default_cap=210.0,
                                  intro_seconds=10.0, playlist_minutes=0.1)
        with contextlib.redirect_stdout(io.StringIO()) as output:
            script.print_comparison(practice, pools, args)
        self.assertIn("nan", output.getvalue())

        row = script.compact_scenario(practice, pools, 3, 1, 210.0, 10.0, 90, 0.1)
        self.assertTrue(math.isnan(row["mean_song"]))
        self.assertTrue(math.isnan(row["floor_pct"]))
        self.assertEqual(row["mean_songs"], 0)
        self.assertEqual(row["mean_runtime"], 10.0)

    def test_a_dropped_song_is_reported(self):
        # Three 200 s songs over a 400 s budget would need 67 s off each.
        planned, dropped = script.plan_timed_block([200, 200, 200], 400, 90)
        self.assertEqual(planned, [200.0, 200.0])
        self.assertTrue(dropped)


if __name__ == "__main__":
    unittest.main()
