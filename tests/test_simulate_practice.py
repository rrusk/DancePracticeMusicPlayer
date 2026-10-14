"""Offline playlist previews must keep the player's selection and timing behavior."""

import contextlib
import csv
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from utils import simulate_practice as script


def practice(**changes):
    return script.load_practice("Example", {"Example": {
        "dances": ["Waltz", "Jive"], "num_selections": 2,
        "randomize_playlist": False, "dance_intros": {"default": "none"},
        **changes,
    }})


def cache_entry(path, duration):
    file_stat = path.stat()
    return {"duration": duration, "size": file_stat.st_size, "mtime": file_stat.st_mtime,
            "title": None, "artist": None, "album": None, "genre": None}


class TestGeneration(unittest.TestCase):
    def setUp(self):
        self.pools = {
            dance: [script.Song(f"/{dance}/{i}.mp3", length)
                    for i, length in enumerate([30, 80, 100, 200, 300])]
            for dance in ["Waltz", "Jive"]
        }
        self.intros = {"Waltz": 10, "Jive": 10}

    def generate(self, definition, counts=None, cap=210):
        return script.generate(definition, self.pools, self.intros, counts or {}, cap, 1)

    def test_counts_apply_adjustments_and_exact_overrides_skip_intros(self):
        definition = practice(adjust_song_counts=True, dance_adjustments={"Jive": "n-1"})
        original = self.generate(definition)
        self.assertEqual([len(block.songs) for block in original], [2, 1])
        overridden = self.generate(definition, {"Waltz": 0, "Jive": 3})
        self.assertEqual([len(block.songs) for block in overridden], [0, 3])
        self.assertEqual(overridden[0].seconds, 0)
        self.assertEqual(overridden[1].play_lengths, [100, 200, 220])

    def test_fixed_count_prefers_long_tracks_then_longest_short_tracks(self):
        block = self.generate(practice(num_selections=4))[0]
        self.assertEqual([song.duration for song in block.songs], [100, 200, 300, 80])
        self.assertEqual(block.seconds, 610)
        self.assertEqual(len(self.generate(practice(num_selections=20))[0].songs), 5)

    def test_play_all_keeps_short_songs_and_single_song_ignores_caps(self):
        block = self.generate(practice(play_all_songs=True, play_single_song=True))[0]
        self.assertEqual(len(block.songs), 5)
        self.assertEqual(block.play_lengths[-1], 300)
        self.assertEqual(self.generate(practice(play_all_songs=True))[0].play_lengths[-1], 220)

    def test_timed_blocks_include_intro_and_individual_count_replaces_budget(self):
        definition = practice(dance_minutes={"Waltz": 5}, min_song_play_seconds=90)
        block = self.generate(definition)[0]
        self.assertEqual(block.mode, "timed")
        # The 410s draw is trimmed to a 290s music budget plus its 10s intro.
        self.assertEqual(len(block.songs), 4)
        self.assertAlmostEqual(block.seconds, 300)
        self.assertEqual(self.generate(definition, {"Waltz": 1})[0].seconds, 110)

    def test_intro_only_and_empty_pools(self):
        definition = practice(dance_minutes={"Waltz": .1})
        self.assertEqual(self.generate(definition)[0].seconds, 10)
        self.pools["Waltz"] = []
        self.assertEqual(self.generate(definition)[0].seconds, 0)

    def test_timed_planner_drops_a_song_instead_of_excessive_trimming(self):
        self.pools["Waltz"] = [script.Song(f"/{i}.mp3", 200) for i in range(3)]
        self.intros["Waltz"] = 0
        block = self.generate(practice(dance_minutes={"Waltz": 450 / 60}))[0]
        self.assertEqual(block.play_lengths, [200, 200])
        self.assertEqual(block.seconds, 400)

    def test_duplicate_dance_blocks_use_unused_tracks_first(self):
        blocks = self.generate(practice(dances=["Waltz", "Waltz"], num_selections=1))
        self.assertNotEqual(blocks[0].songs[0].path, blocks[1].songs[0].path)

    def test_random_scenarios_are_reproducible_and_share_candidate_order(self):
        definition = practice(randomize_playlist=True)
        self.assertEqual(self.generate(definition), self.generate(definition))
        self.assertEqual(self.generate(definition)[0].songs[:1],
                         self.generate(definition, {"Waltz": 1})[0].songs)


class TestCacheAndDefinitions(unittest.TestCase):
    def test_windows_case_insensitive_paths_and_root_filter(self):
        cache = {
            r"C:\Music\quickstep\album\a.mp3": {"duration": 100},
            r"C:\Other\QuickStep\b.mp3": {"duration": 200},
            r"C:\Music\QuickStep\bad.mp3": {"duration": float("nan")},
            r"C:\Music\notquickstep\x.mp3": {"duration": 100},
        }
        with contextlib.redirect_stderr(io.StringIO()):
            pools = script.load_pools(cache, ["QuickStep"], r"C:\Music")
        self.assertEqual([s.duration for s in pools["QuickStep"]], [100])

    def test_cache_intros_follow_dance_specific_default_and_none(self):
        definition = practice(dance_intros={"default": "gap_10", "Waltz": "announce"})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = {"/old/announce/Waltz.ogg": {"duration": 999}}
            for folder, name, duration in (("announce", "Waltz.ogg", 9), ("cues", "gap_10.ogg", 10)):
                path = root / folder / name
                path.parent.mkdir(exist_ok=True)
                path.write_bytes(b"fixture")
                stat = path.stat()
                cache[str(path)] = {"duration": duration, "size": stat.st_size, "mtime": stat.st_mtime,
                                    "title": None, "artist": None, "album": None, "genre": None}
            with patch.object(script.app_paths, "app_path", side_effect=lambda folder: str(root / folder)):
                self.assertEqual(script.intro_lengths(definition, cache, 99, {}), {"Waltz": 9, "Jive": 10})
                definition["dance_intros"]["Waltz"] = "none"
                self.assertEqual(script.intro_lengths(definition, cache, 99, {"Jive": 0}),
                                 {"Waltz": 0, "Jive": 0})

    def test_missing_intros_ignore_foreign_cache_entries_and_add_no_time(self):
        cache = {"/old/announce/Waltz.ogg": {"duration": 999}}
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stderr(io.StringIO()):
            with patch.object(script.app_paths, "app_path", return_value=directory):
                self.assertEqual(script.intro_lengths(practice(dance_intros={}), cache, 10, {}),
                                 {"Waltz": 0, "Jive": 0})

    def test_unreadable_specific_announcement_does_not_fall_back_to_generic(self):
        from tinytag import TinyTagException
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("Waltz.ogg", "Generic.ogg"):
                (root / name).write_bytes(b"unreadable")
            with patch.object(script.app_paths, "app_path", return_value=directory), \
                    patch("tinytag.TinyTag.get", side_effect=TinyTagException("bad audio")) as read:
                self.assertIsNone(script.asset_duration({}, "announce", ["Waltz.ogg", "Generic.ogg"]))
                read.assert_called_once_with(str(root / "Waltz.ogg"))

    def test_a_current_entry_without_a_duration_is_skipped_without_tinytag(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Waltz.ogg"
            path.write_bytes(b"fixture")
            stat = path.stat()
            cache = {str(path): {"duration": None, "size": stat.st_size, "mtime": stat.st_mtime,
                                 "title": None, "artist": None, "album": None, "genre": None}}
            with patch.object(script.app_paths, "app_path", return_value=directory), \
                    patch.dict(sys.modules, {"tinytag": None}):
                self.assertIsNone(script.asset_duration(cache, "announce", ["Waltz.ogg"]))

    def test_existing_intro_estimate_is_used_only_when_metadata_dependency_is_missing(self):
        definition = practice(dance_intros={"default": "announce"})
        with patch.object(script, "asset_duration", side_effect=ImportError("tinytag")), \
                contextlib.redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(script.intro_lengths(definition, {}, 7, {}), {"Waltz": 7, "Jive": 7})
            self.assertIn("exists but TinyTag is unavailable", errors.getvalue())

    def test_relative_and_home_library_roots(self):
        with tempfile.TemporaryDirectory() as directory:
            song = Path(directory) / "music" / "Waltz" / "song.mp3"
            song.parent.mkdir(parents=True)
            song.write_bytes(b"fixture")
            cache = {str(song): cache_entry(song, 100)}
            previous = os.getcwd()
            os.chdir(directory)
            try:
                self.assertEqual(len(script.load_pools(cache, ["Waltz"], "music")["Waltz"]), 1)
            finally:
                os.chdir(previous)
            with patch.dict(os.environ, {"HOME": directory, "USERPROFILE": directory}):
                self.assertEqual(len(script.load_pools(cache, ["Waltz"], "~/music")["Waltz"]), 1)

    @unittest.skipIf(os.name == "nt", "Windows has one folder per name whatever its case")
    def test_a_local_library_uses_the_players_folder_and_skips_deleted_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = {}
            # The lowercase folder and one QuickStep song were deleted after caching.
            for folder, name, exists in (("QuickStep", "kept.mp3", True),
                                         ("QuickStep", "deleted.mp3", False),
                                         ("Quickstep", "other_spelling.mp3", True),
                                         ("quickstep", "old.mp3", False)):
                path = root / folder / name
                cache[str(path)] = {"duration": 100}
                if exists:
                    path.parent.mkdir(exist_ok=True)
                    path.write_bytes(b"fixture")
                    cache[str(path)] = cache_entry(path, 100)
            with contextlib.redirect_stderr(io.StringIO()) as errors:
                pools = script.load_pools(cache, ["QuickStep"], directory)
            self.assertEqual([Path(s.path).name for s in pools["QuickStep"]], ["kept.mp3"])
            self.assertIn("ignored 1 cache entries for files no longer", errors.getvalue())

    @unittest.skipIf(os.name == "nt", "Windows has one folder per name whatever its case")
    def test_a_copied_cache_uses_the_spelling_the_player_would_choose(self):
        cache = {"/elsewhere/Quickstep/a.mp3": {"duration": 100},
                 "/elsewhere/quickstep/b.mp3": {"duration": 200}}
        self.assertEqual([s.duration for s in script.load_pools(
            cache, ["QuickStep"], "/elsewhere")["QuickStep"]], [100])

    @unittest.skipIf(os.name == "nt", "Native Windows roots ignore case")
    def test_posix_library_root_case_is_preserved(self):
        cache = {"/Music/Waltz/song.mp3": {"duration": 100}, "/music/Waltz/song.mp3": {"duration": 200}}
        self.assertEqual([s.duration for s in script.load_pools(cache, ["Waltz"], "/music")["Waltz"]], [200])

    def test_both_simulators_use_the_same_case_tolerant_music_pools(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.json"
            library = Path(directory) / "unavailable"
            cache = {str(library / "quickstep" / "album" / "song.mp3"): {"duration": 100},
                     "/old/announce/QuickStep/song.mp3": {"duration": 9}}
            path.write_text(json.dumps({"songs": cache}))
            self.assertEqual(script.load_pools(cache, ["QuickStep"], library),
                             script.timed.load_pools(path, ["QuickStep"], str(library)))

    def test_custom_overrides_builtin_and_empty_adjustments_use_player_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            builtin, custom = Path(directory) / "builtin.json", Path(directory) / "custom.json"
            builtin.write_text(json.dumps({"Example": {"dances": ["Waltz"]}}))
            custom.write_text(json.dumps({"Example": {"dances": ["Jive"], "adjust_song_counts": True}}))
            definition = script.load_practice("Example", script.load_types(builtin, custom))
        self.assertEqual(definition["dances"], ["Jive"])
        self.assertEqual(script.block_mode(definition, "Jive", {}), ("count", 1))

    def test_assignments_reject_typos_fractions_nonfinite_and_duplicates(self):
        for assignments in (["Wlatz=1"], ["Waltz=1.5"], ["Waltz=nan"],
                            ["Waltz=-1"], ["Waltz=1", "Waltz=2"]):
            with self.subTest(assignments=assignments), self.assertRaises(ValueError):
                script.assignments(assignments, ["Waltz"], "count", integer=True, allow_zero=True)


class TestCommandLine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.builtin = self.root / "builtin.json"
        self.custom = self.root / "custom.json"
        self.cache = self.root / "cache.json"
        self.config = self.root / "music.ini"
        self.remote_library = self.root / "unavailable"
        self.builtin.write_text(json.dumps({"Example": {
            "dances": ["Waltz", "Jive"], "num_selections": 1,
            "dance_intros": {"default": "none"}, "randomize_playlist": False,
        }}))
        self.custom.write_text("{}")
        self.config.write_text(f"[user]\nmusic_dir = {self.remote_library}\n")
        self.cache.write_text(json.dumps({"songs": {
            str(self.remote_library / dance / f"{i}.mp3"): {"duration": 300}
            for dance in ("Waltz", "Jive") for i in range(3)
        }}))
        self.args = [str(self.cache), "--builtin-types", str(self.builtin),
                     "--custom-types", str(self.custom), "--config", str(self.config),
                     "--practice-type", "Example", "--runs", "2"]

    def run_script(self, *extra):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            result = script.main(self.args + list(extra))
        self.assertEqual(result, 0)
        return output.getvalue()

    def test_compare_global_counts_individual_overrides_and_csv_without_changing_inputs(self):
        before = {p: p.read_bytes() for p in (self.builtin, self.custom, self.cache, self.config)}
        output_path = self.root / "results.csv"
        output = self.run_script("--selections", "2", "--selections", "3",
                                 "--dance-selections", "Jive=0", "--csv", str(output_path),
                                 "--show-playlist")
        self.assertIn("Changed (default selections=2)", output)
        self.assertIn("Example playlist", output)
        with output_path.open(newline="") as handle:
            totals = [r for r in csv.DictReader(handle) if r["dance"] == "TOTAL"]
        self.assertEqual([float(r["mean_songs"]) for r in totals], [2, 2, 3])
        self.assertEqual([float(r["mean_seconds"]) for r in totals], [440, 440, 660])
        self.assertEqual(before, {p: p.read_bytes() for p in before})
        self.assertEqual(set(self.root.iterdir()), set(before) | {output_path})

    def test_global_cap_change_compares_against_baseline(self):
        output = self.run_script("--default-cap", "100")
        self.assertIn("Mean runtime change: -3:40.0", output)

    def test_baseline_reads_player_settings_without_changing_them(self):
        settings = f"[user]\nsong_max_playtime = 100\nmusic_dir = {self.remote_library}\n"
        self.config.write_text(settings)
        output = self.run_script("--default-cap", "150")
        self.assertIn("Baseline global cap: 100s", output)
        self.assertIn("Mean runtime change: 1:40.0", output)
        self.assertEqual(self.config.read_text(), settings)

    def test_invalid_cap_preserves_the_configured_library_and_ignores_foreign_tracks(self):
        library = self.root / "library"
        song = library / "Waltz" / "song.mp3"
        song.parent.mkdir(parents=True)
        song.write_bytes(b"fixture")
        self.config.write_text(f"[user]\nmusic_dir = {library}\nsong_max_playtime = broken\n")
        self.builtin.write_text(json.dumps({"Example": {
            "dances": ["Waltz"], "num_selections": 1, "randomize_playlist": False,
            "dance_intros": {"default": "none"}}}))
        self.cache.write_text(json.dumps({"songs": {
            str(song): cache_entry(song, 100), "/000foreign/Waltz/deleted.mp3": {"duration": 200}}}))
        before = self.config.read_bytes()
        output_path = self.root / "results.csv"
        with contextlib.redirect_stderr(io.StringIO()) as warnings:
            output = self.run_script("--csv", str(output_path))
        self.assertIn("retaining music_dir", warnings.getvalue())
        self.assertIn(f"Music library: {library}", output)
        self.assertIn("Baseline global cap: 210s", output)
        with output_path.open(newline="") as handle:
            total = next(row for row in csv.DictReader(handle) if row["dance"] == "TOTAL")
        self.assertEqual(float(total["mean_seconds"]), 100)
        self.assertEqual(self.config.read_bytes(), before)

    def test_duplicate_timed_dances_scale_each_occurrence_to_the_requested_total(self):
        self.builtin.write_text(json.dumps({"Example": {
            "dances": ["Waltz", "Jive", "Waltz"], "dance_minutes": {"Waltz": 5, "Jive": 5},
            "dance_intros": {"default": "none"}, "randomize_playlist": False}}))
        self.cache.write_text(json.dumps({"songs": {
            str(self.remote_library / dance / f"{i}.mp3"): {"duration": 100}
            for dance in ("Waltz", "Jive") for i in range(12)}}))
        output_path = self.root / "results.csv"
        self.run_script("--playlist-minutes", "20", "--csv", str(output_path))
        with output_path.open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        changed_total = [row for row in rows if row["scenario"] == "Changed" and row["dance"] == "TOTAL"][0]
        self.assertEqual(float(changed_total["mean_seconds"]), 1200)
        changed_blocks = [row for row in rows if row["scenario"] == "Changed" and row["dance"] != "TOTAL"]
        self.assertEqual([float(row["mean_seconds"]) for row in changed_blocks], [400, 400, 400])

    def test_play_all_can_be_changed_to_counts_and_timed_blocks_in_one_command(self):
        definition = json.loads(self.builtin.read_text())
        definition["Example"]["play_all_songs"] = True
        self.builtin.write_text(json.dumps(definition))
        output = self.run_script("--selections", "2", "--dance-minutes", "Waltz=5",
                                 "--playlist-minutes", "6")
        self.assertIn("6.00 min", output)
        self.assertIn("Changed (default selections=2)", output)

    def test_timed_conversion_and_scaling(self):
        output = self.run_script("--dance-minutes", "Waltz=5", "--playlist-minutes", "6")
        self.assertIn("6.00 min", output)
        self.assertIn("Target difference", output)

    def test_an_unreadable_custom_file_is_ignored_as_in_the_player(self):
        self.custom.write_text("{not json")
        with contextlib.redirect_stderr(io.StringIO()) as errors:
            self.assertIn("Example", self.run_script("--list"))
        self.assertIn("ignoring it", errors.getvalue())

    def test_the_players_music_dir_is_the_default_library(self):
        self.config.write_text("[user]\nmusic_dir = /elsewhere\n")
        with contextlib.redirect_stderr(io.StringIO()) as errors, \
                self.assertRaises(SystemExit):
            script.main(self.args)
        self.assertIn("under /elsewhere", errors.getvalue())
        self.assertIn(f"Music library: {self.remote_library}",
                      self.run_script("--music-dir", str(self.remote_library)))

    def test_list_does_not_need_cache(self):
        self.cache.unlink()
        with patch.object(script, "load_cache", side_effect=AssertionError("should not load cache")):
            self.assertIn("Example", self.run_script("--list"))

    def test_list_filters_unsupported_types_and_uses_player_menu_order(self):
        self.builtin.write_text(json.dumps({
            "Later": {"dances": ["Waltz"], "order": 10},
            "Rounds": {"dances": ["Waltz"], "segments": [{"round": ["Waltz"]}]},
            "Earlier": {"dances": ["Waltz"]},
            "Broken": [],
        }))
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.run_script("--list").splitlines(),
                             ["60min", "NC 60min", "Earlier", "Later"])

    def test_invalid_parameters_fail_with_actionable_errors(self):
        for extra, expected in [(["--playlist-minutes", "10"], "needs active timed dances"),
                                (["--default-cap", "nan"], "must be finite"),
                                (["--dance-selections", "Walz=1"], "dance in this practice"),
                                (["--dance-selections", "Waltz=1", "--dance-minutes", "Waltz=5"],
                                 "cannot have both"),
                                (["--config", str(self.root / "musc.ini")],
                                 "Settings file does not exist")]:
            with self.subTest(extra=extra), contextlib.redirect_stderr(io.StringIO()) as errors:
                with self.assertRaises(SystemExit) as caught:
                    script.main(self.args + extra)
                self.assertEqual(caught.exception.code, 2)
                self.assertIn(expected, errors.getvalue())


class TestPlayerParity(unittest.TestCase):
    """Compare generated items against the actual player for each block mode."""

    def test_selection_and_play_lengths_match_the_player(self):
        from music_player import MusicPlayer, PlayerConstants
        pools = {dance: [script.Song(f"/{dance}/{i}.mp3", length)
                         for i, length in enumerate([30, 80, 100, 200, 300])]
                 for dance in ("Waltz", "Jive")}
        by_path = {song.path: song for pool in pools.values() for song in pool}
        cases = [
            {}, {"num_selections": 4}, {"play_all_songs": True},
            {"play_all_songs": True, "play_single_song": True},
            {"play_single_song": True, "dance_minutes": {"Waltz": 5}},
            {"dance_minutes": {"Waltz": 5}}, {"dance_minutes": {"Waltz": .1}},
            {"dance_minutes": {"Waltz": 450 / 60}, "min_song_play_seconds": 1},
            {"adjust_song_counts": True, "dance_adjustments": {"Waltz": {"default": 0}}},
            {"dances": ["Waltz", "Jive", "Waltz"]},
        ]
        for changes in cases:
            with self.subTest(changes=changes):
                definition = practice(dance_max_playtimes={"Jive": 150}, **changes)
                player = MusicPlayer.__new__(MusicPlayer)
                player._generation_config = None
                player.play_all_songs = definition["play_all_songs"]
                player.play_single_song = definition["play_single_song"]
                player.current_dance_minutes = definition["dance_minutes"]
                player.current_dance_adjustments = definition["dance_adjustments"]
                player.adjust_song_counts_for_playlist = definition["adjust_song_counts"]
                player.current_dance_max_playtimes = definition["dance_max_playtimes"]
                player.current_min_song_play_seconds = definition["min_song_play_seconds"]
                player.song_max_playtime = 210
                player._collect_music_files = lambda directory, dance: [s.path for s in pools[dance]]
                player._create_song_info = lambda path, dance: {
                    "path": path, "dance": dance, "duration": by_path[path].duration,
                    "max_playtime": player._cap_for_dance(dance), "fade_seconds": PlayerConstants.FADE_TIME}
                player._block_intro = lambda dance: {
                    "path": f"/intro/{dance}", "dance": "cue", "duration": 10,
                    "max_playtime": 10, "fade_seconds": 0}
                player._report_timed_block = MagicMock()
                preview = script.generate(definition, pools, {"Waltz": 10, "Jive": 10}, {}, 210, 1)
                taken = set()
                for block in preview:
                    with contextlib.redirect_stdout(io.StringIO()):
                        items = player._get_songs_for_dance(
                            "unused", block.dance, definition["num_selections"], False, taken)
                    music = [item for item in items if item["dance"] != "cue"]
                    self.assertEqual([s.path for s in block.songs], [item["path"] for item in music])
                    self.assertEqual(block.play_lengths, [player._play_length(item) for item in music])
                    self.assertEqual(block.seconds, sum(player._play_length(item) for item in items))
                    taken.update(item["path"] for item in items)

    def test_base_types_and_minimum_song_length_match_the_player(self):
        from music_player import MusicPlayer, PlayerConstants
        self.assertEqual(script.MIN_COUNT_SONG_SECONDS, PlayerConstants.MIN_SONG_LENGTH_SECONDS)
        for name, raw in script.rules.base_practice_types().items():
            player = MusicPlayer.__new__(MusicPlayer)
            player.practice_dances = script.copy.deepcopy(script.rules.BASE_DANCE_LISTS)
            player.music_dir = ""
            player.custom_practice_mapping = {}
            player.set_practice_type(None, name)
            definition = script.load_practice(name, {name: raw})
            self.assertEqual(player.dances, definition["dances"])
            self.assertEqual(player.num_selections, definition["num_selections"])
            self.assertEqual(player.current_dance_max_playtimes, definition["dance_max_playtimes"])
            for dance in definition["dances"]:
                self.assertEqual(player._get_adjusted_song_count(dance, player.num_selections),
                                 script.block_mode(definition, dance, {})[1])


if __name__ == "__main__":
    unittest.main()
