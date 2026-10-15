"""Exported JSON must reproduce ordinary preview settings when the player loads it."""

import copy
import contextlib
import csv
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from utils import simulate_practice as script
from tests.support import PracticePreviewFixture, preview_practice as practice


class TestDefinitionExport(unittest.TestCase):
    def round_trip(self, scenario, counts=None, cap=180, reference=None, explicit_cap=False):
        counts = counts or {}
        definition = script.export_definition("Exported", scenario, counts, cap if explicit_cap else None, reference or {})
        payload = json.loads(json.dumps({"Exported": definition}, allow_nan=False))
        reloaded = script.load_practice("Exported", payload)
        pools = {dance: [script.Song(f"/{dance}/{i}.mp3", duration)
                         for i, duration in enumerate([80, 100, 150, 200, 300] * 3)]
                 for dance in scenario["dances"]}
        intros = {dance: 10 for dance in pools}
        original = script.generate(scenario, pools, intros, counts, cap, 1)
        # Ordinary exports share the player setting; explicit overrides stand alone.
        loaded = script.generate(reloaded, pools, intros, {}, 999 if explicit_cap else cap, 1)
        self.assertEqual(original, loaded)
        return definition, reloaded

    def test_exact_counts_and_zero_are_encoded_without_activating_dormant_rules(self):
        scenario = practice(num_selections=3, adjust_song_counts=False,
                            dance_adjustments={"Waltz": {"default": 1}})
        before = copy.deepcopy(scenario)
        definition, reloaded = self.round_trip(scenario, {"Jive": 0})
        self.assertEqual(definition["dance_adjustments"], {"Jive": {"default": 0}})
        self.assertEqual(script.block_mode(reloaded, "Waltz", {}), ("count", 3))
        self.assertEqual(script.block_mode(reloaded, "Jive", {}), ("count", 0))
        self.assertEqual(scenario, before)

    def test_exact_override_replaces_count_specific_mappings_and_preserves_other_adjustments(self):
        scenario = practice(num_selections=3, adjust_song_counts=True,
                            dance_adjustments={"Waltz": {"3": 1, "default": 2}, "Jive": "n-1"})
        definition, reloaded = self.round_trip(scenario, {"Waltz": 4})
        self.assertEqual(definition["dance_adjustments"]["Waltz"], {"default": 4})
        self.assertEqual(script.block_mode(reloaded, "Jive", {}), ("count", 2))

    def test_count_override_replaces_a_timed_budget_for_every_occurrence(self):
        scenario = practice(dances=["Waltz", "Jive", "Waltz"], dance_minutes={"Waltz": 5})
        definition, reloaded = self.round_trip(scenario, {"Waltz": 1})
        self.assertNotIn("dance_minutes", definition)
        self.assertEqual(script.block_mode(reloaded, "Waltz", {}), ("count", 1))

    def test_timed_budgets_minimum_and_per_dance_caps_survive(self):
        scenario = practice(dances=["Waltz", "Jive", "Waltz"],
                            dance_minutes={"Waltz": 20 / 3, "Jive": 20 / 3},
                            min_song_play_seconds=100, dance_max_playtimes={"Jive": 150})
        definition, _reloaded = self.round_trip(scenario, cap=190)
        self.assertEqual(definition["dance_minutes"], scenario["dance_minutes"])
        self.assertEqual(definition["min_song_play_seconds"], 100)
        self.assertEqual(definition["dance_max_playtimes"], {"Jive": 150})

    def test_base_types_export_without_internal_dance_list_names(self):
        source = script.rules.base_practice_types()["60min"]
        scenario = script.load_practice("60min", {"60min": source})
        definition, _reloaded = self.round_trip(scenario, reference=source)
        self.assertNotIn("dance_type", definition)
        self.assertNotIn("segments", definition)
        self.assertNotIn("dance_minutes", definition)
        self.assertNotIn("order", definition)

    def test_unchanged_latin_export_matches_the_builtin_text_format(self):
        source = script.load_definitions(script.app_paths.app_path("builtin_practice_types.json"))[
            "Silver+ Latin 30min"]
        scenario = script.load_practice("Source", {"Source": source})
        definition, _reloaded = self.round_trip(scenario, reference=source)
        self.assertEqual(json.dumps(definition, indent=4), json.dumps(source, indent=4))

    def test_sparse_caps_continue_to_follow_the_player_setting(self):
        definition, reloaded = self.round_trip(practice(dance_max_playtimes={"Jive": 150}))
        self.assertEqual(definition["dance_max_playtimes"], {"Jive": 150})
        pools = {dance: [script.Song(f"/{dance}/{i}.mp3", 500) for i in range(2)]
                 for dance in ("Waltz", "Jive")}
        intros = {dance: 0 for dance in pools}
        lower = script.generate(reloaded, pools, intros, {}, 120, 1)
        higher = script.generate(reloaded, pools, intros, {}, 210, 1)
        self.assertEqual(lower[0].play_lengths, [130, 130])
        self.assertEqual(higher[0].play_lengths, [220, 220])
        self.assertEqual(lower[1].play_lengths, higher[1].play_lengths)

    def test_explicit_global_override_is_encoded_without_replacing_specific_caps(self):
        definition, _reloaded = self.round_trip(practice(dance_max_playtimes={"Jive": 150}),
                                               cap=180, explicit_cap=True)
        self.assertEqual(definition["dance_max_playtimes"], {"Waltz": 180, "Jive": 150})

    def test_source_field_order_and_existing_intros_are_preserved(self):
        reference = {"dances": ["Waltz", "Jive"], "dance_intros": {"default": "gap_10"},
                     "num_selections": 2, "dance_max_playtimes": {"Jive": 150}, "order": 10}
        scenario = script.load_practice("Source", {"Source": reference})
        definition, _reloaded = self.round_trip(scenario, reference=reference)
        self.assertEqual([key for key in definition if key in reference], list(reference))
        self.assertEqual(definition["dance_intros"], reference["dance_intros"])

    def test_play_all_and_single_song_definitions_survive_without_individual_overrides(self):
        for single_song in (True, False):
            with self.subTest(single_song=single_song):
                self.round_trip(practice(play_all_songs=True, play_single_song=single_song))

    def test_unrepresentable_counts_and_invalid_names_or_caps_are_refused(self):
        with self.assertRaisesRegex(ValueError, "play-all practice requires --selections"):
            self.round_trip(practice(play_all_songs=True), {"Waltz": 2})
        for name in ("", "default", "newcomer", "__COMMENT__ hidden"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                script.export_definition(name, practice(), {}, 180, {})
        with self.assertRaisesRegex(ValueError, "Cannot export"):
            self.round_trip(practice(), cap=-1, explicit_cap=True)

    def test_export_round_trips_through_the_actual_players_settings(self):
        from music_player import MusicPlayer
        scenario = practice(dance_minutes={"Waltz": 5}, dance_max_playtimes={"Jive": 150})
        definition, loaded = self.round_trip(scenario, {"Waltz": 3, "Jive": 0}, cap=180)
        player = MusicPlayer.__new__(MusicPlayer)
        player.music_dir = ""
        player.practice_dances = {"default": ["Waltz"], "Exported": loaded["dances"]}
        player.custom_practice_mapping = {"Exported": dict(loaded, dance_type="Exported")}
        player.set_practice_type(None, "Exported")
        self.assertEqual(player.current_dance_minutes, {})
        self.assertEqual(player.current_dance_max_playtimes, definition["dance_max_playtimes"])
        self.assertEqual(player._get_adjusted_song_count("Waltz", player.num_selections), 3)
        self.assertEqual(player._get_adjusted_song_count("Jive", player.num_selections), 0)


class TestExportWorkflow(PracticePreviewFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        previous_directory = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, previous_directory)

    def test_preview_without_export_options_does_not_write_a_file(self):
        self.run_script("--selections", "2")
        self.assertFalse((self.root / "export.json").exists())

    def test_export_json_defaults_to_source_name_and_overwrites_default_file(self):
        path = self.root / "export.json"
        before = self.builtin.read_bytes()
        for option in (["--export-json"], ["--export-json", "export.json"],
                       ["--export-json", str(path)]):
            with self.subTest(option=option):
                path.write_text("previous export")
                self.run_script(*option, "--selections", "3")
                payload = json.loads(path.read_text())
                self.assertEqual(list(payload), ["Example"])
                self.assertEqual(payload["Example"]["num_selections"], 3)
        self.assertEqual(self.builtin.read_bytes(), before)

    def test_export_name_alone_uses_default_file(self):
        path = self.root / "export.json"
        path.write_text("previous export")
        self.run_script("--export-name", "Saved Practice")
        self.assertEqual(list(json.loads(path.read_text())), ["Saved Practice"])

    def test_export_json_custom_path_defaults_to_source_name(self):
        path = self.root / "saved.json"
        self.run_script("--export-json", str(path))
        self.assertEqual(list(json.loads(path.read_text())), ["Example"])
        self.assertFalse((self.root / "export.json").exists())

    def test_explicit_source_name_is_allowed(self):
        path = self.root / "saved.json"
        self.run_script("--export-name", "Example", "--export-json", str(path))
        self.assertEqual(list(json.loads(path.read_text())), ["Example"])

    def test_failed_default_replacement_keeps_previous_file_and_removes_temporary_file(self):
        path = self.root / "export.json"
        path.write_text("previous export")
        with patch.object(Path, "replace", side_effect=OSError("replacement failed")), \
                contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.run_script("--export-json")
        self.assertEqual(path.read_text(), "previous export")
        self.assertEqual(list(self.root.glob(".practice-export-*")), [])

    def test_exported_file_reproduces_the_changed_preview_and_preserves_inputs(self):
        before = {p: p.read_bytes() for p in (self.builtin, self.custom, self.cache, self.config)}
        export_path = self.root / "export.json"
        changed_csv, loaded_csv = self.root / "changed.csv", self.root / "loaded.csv"
        output = self.run_script("--selections", "2", "--dance-selections", "Waltz=3",
                                 "--dance-selections", "Jive=0", "--default-cap", "100",
                                 "--export-name", "Saved Practice", "--export-json", str(export_path),
                                 "--csv", str(changed_csv))
        self.assertIn("Exported practice 'Saved Practice'", output)
        payload = json.loads(export_path.read_text())
        self.assertEqual(list(payload), ["Saved Practice"])
        self.assertIn('\n    "Saved Practice": {\n        "dances": [', export_path.read_text())
        self.assertEqual(payload["Saved Practice"]["dance_max_playtimes"], {"Waltz": 100, "Jive": 100})
        self.run_script("--practice-type", "Saved Practice", "--custom-types", str(export_path),
                        "--csv", str(loaded_csv))
        with changed_csv.open(newline="") as handle:
            expected = [{k: v for k, v in row.items() if k != "scenario"} for row in csv.DictReader(handle)
                        if row["scenario"].startswith("Changed")]
        with loaded_csv.open(newline="") as handle:
            actual = [{k: v for k, v in row.items() if k != "scenario"} for row in csv.DictReader(handle)]
        self.assertEqual(expected, actual)
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_ambiguous_or_simulation_only_export_options_fail_without_writing(self):
        path = self.root / "export.json"
        export = ["--export-name", "Saved", "--export-json", str(path)]
        cases = [(export + ["--selections", "2", "--selections", "3"], "requires one scenario"),
                 (export + ["--dance-intro-seconds", "Waltz=5"], "simulation-only"),
                 (export + ["--csv", str(path)], "different files"),
                 (export + ["--list"], "cannot be combined")]
        for extra, message in cases:
            with self.subTest(extra=extra), contextlib.redirect_stderr(io.StringIO()) as errors:
                with self.assertRaises(SystemExit) as caught:
                    self.run_script(*extra)
                self.assertEqual(caught.exception.code, 2)
                self.assertIn(message, errors.getvalue())
                self.assertFalse(path.exists())

    def test_existing_files_are_not_overwritten(self):
        path = self.root / "saved.json"
        path.write_text("keep this file")
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.run_script("--export-name", "Saved", "--export-json", str(path))
        self.assertEqual(path.read_text(), "keep this file")

    def test_existing_builtin_base_and_custom_names_fail_before_loading_songs(self):
        self.custom.write_text(json.dumps({"Custom Practice": {"dances": ["Waltz"]}}))
        # A name is protected even when its definition is not the chosen source.
        builtins = json.loads(self.builtin.read_text())
        builtins["Silver+ Latin 30min"] = {"dances": ["Waltz"]}
        self.builtin.write_text(json.dumps(builtins))
        path = self.root / "export.json"
        for name in ("Silver+ Latin 30min", "60min", "NC 60min", "Custom Practice"):
            with self.subTest(name=name), \
                    patch.object(script, "load_cache", side_effect=AssertionError("must fail early")), \
                    contextlib.redirect_stdout(io.StringIO()) as output, \
                    contextlib.redirect_stderr(io.StringIO()) as errors:
                with self.assertRaises(SystemExit) as caught:
                    self.run_script("--export-name", name, "--export-json", str(path))
                self.assertEqual(caught.exception.code, 2)
                self.assertIn("already exists", errors.getvalue())
                self.assertEqual(output.getvalue(), "")
                self.assertFalse(path.exists())

    def test_missing_output_folder_fails_before_loading_songs(self):
        path = self.root / "missing" / "export.json"
        with patch.object(script, "load_cache", side_effect=AssertionError("must fail early")), \
                contextlib.redirect_stdout(io.StringIO()) as output, \
                contextlib.redirect_stderr(io.StringIO()) as errors:
            with self.assertRaises(SystemExit) as caught:
                self.run_script("--export-name", "Saved", "--export-json", str(path))
        self.assertEqual(caught.exception.code, 2)
        self.assertIn("Export folder does not exist", errors.getvalue())
        self.assertEqual(output.getvalue(), "")
        self.assertFalse(path.exists())

    def test_intro_estimate_can_be_supplied_without_changing_the_exported_intro(self):
        path = self.root / "export.json"
        self.run_script("--intro-seconds", "7", "--export-name", "Saved", "--export-json", str(path))
        definition = json.loads(path.read_text())["Saved"]
        self.assertEqual(definition["dance_intros"], {"default": "none"})
        self.assertNotIn("intro_seconds", definition)

    def test_scaled_budgets_keep_exact_thousandths_before_preview_and_export(self):
        name = "Silver+ Std 60min Timed"
        source = script.load_definitions(script.app_paths.app_path("builtin_practice_types.json"))[name]
        self.builtin.write_text(json.dumps({name: source}))
        self.cache.write_text(json.dumps({"songs": {
            str(self.remote_library / dance / f"{i}.mp3"): {"duration": 300}
            for dance in source["dances"] for i in range(12)}}))
        path = self.root / "export.json"
        before_csv, after_csv = self.root / "before.csv", self.root / "after.csv"
        self.run_script("--practice-type", name, "--playlist-minutes", "57",
                        "--export-name", "Saved 57min", "--export-json", str(path),
                        "--csv", str(before_csv))
        definition = json.loads(path.read_text())["Saved 57min"]
        self.assertEqual(definition["dance_minutes"], {
            "Waltz": 12.996, "Tango": 12.996, "VienneseWaltz": 7.999,
            "Foxtrot": 12.996, "QuickStep": 10.013})
        self.run_script("--practice-type", "Saved 57min", "--custom-types", str(path),
                        "--csv", str(after_csv))
        with before_csv.open(newline="") as handle:
            expected = [{k: v for k, v in row.items() if k != "scenario"} for row in csv.DictReader(handle)
                        if row["scenario"] == "Changed"]
        with after_csv.open(newline="") as handle:
            actual = [{k: v for k, v in row.items() if k != "scenario"} for row in csv.DictReader(handle)]
        self.assertEqual(expected, actual)


if __name__ == "__main__":
    unittest.main()
