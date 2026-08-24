"""Workflow tests for the practice type editor.

The editor is the only place practice types are written, and a bad write is not
noticed until a practice type is next selected -- often at a practice. These
tests drive the real screen against temporary files rather than mocking it, so
they exercise loading, saving, renaming, deleting, overriding a built-in, and
the validation that stops an unusable definition from being saved.

To run these tests:
    python -m pytest tests/test_practice_type_editor.py
"""
import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

# Stop Kivy from consuming the test runner's arguments. Note that Kivy does
# still open a window: the editor tests build real widgets and fail without a
# window provider, so these tests need a display.
os.environ["KIVY_NO_ARGS"] = "1"

# pylint: disable=wrong-import-position
from practice_type_editor import PracticeTypeEditorScreen

BUILTIN = {
    "Silver+ Standard 60min": {
        "dances": ["Waltz", "Tango"],
        "num_selections": 4,
        "dance_max_playtimes": {"VienneseWaltz": 150},
    },
    "LineDance": {"dances": ["LineDance"], "num_selections": 1},
}


class EditorTestCase(unittest.TestCase):
    """A real editor screen pointed at temporary practice type files."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.builtin_path = os.path.join(self.tmp, "builtin_practice_types.json")
        self.custom_path = os.path.join(self.tmp, "custom_practice_types.json")
        with open(self.builtin_path, "w", encoding="utf-8") as handle:
            json.dump(BUILTIN, handle)

        self.screen = PracticeTypeEditorScreen(name="editor")
        self.screen.builtin_path = self.builtin_path
        self.screen.custom_path = self.custom_path
        self.popups = []
        self.screen.show_popup = lambda title, message: self.popups.append((title, message))
        self.screen.display_practice_type_list = MagicMock()
        self.screen.load_practice_types()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def form(self):
        """The edit form, for filling in directly."""
        return self.screen.edit_form

    def fill(self, name="New Practice", dances="Waltz, Tango", selections="2",
             adjustments="", playtimes="", minutes="", segments="", intros="",
             order="0"):
        """Fills the form as a user would."""
        form = self.form()
        form.name_input.text = name
        form.dances_input.text = dances
        form.num_selections_input.text = selections
        form.play_all_songs_input.active = False
        form.auto_update_input.active = False
        form.play_single_song_input.active = False
        form.randomize_playlist_input.active = True
        form.adjust_song_counts_input.active = False
        form.dance_adjustments_input.text = adjustments
        form.dance_max_playtimes_input.text = playtimes
        form.dance_minutes_input.text = minutes
        form.segments_input.text = segments
        form.dance_intros_input.text = intros
        form.order_input.text = order

    def saved(self):
        """The custom practice types as written to disk."""
        if not os.path.exists(self.custom_path):
            return {}
        with open(self.custom_path, encoding="utf-8") as handle:
            return json.load(handle)

    def select(self, name):
        """Loads a practice type into the form, as clicking it would."""
        button = MagicMock()
        button.background_color = (1, 1, 1, 1)
        self.screen.load_practice_type_into_form(button, name)


class TestLoading(EditorTestCase):
    """Loading practice types, including files that are not usable."""

    def test_builtins_are_listed(self):
        self.assertIn("Silver+ Standard 60min", self.screen.practice_types)

    def test_custom_types_override_builtins(self):
        with open(self.custom_path, "w", encoding="utf-8") as handle:
            json.dump({"Silver+ Standard 60min": {"dances": ["Jive"]}}, handle)
        self.screen.load_practice_types()
        self.assertEqual(self.screen.practice_types["Silver+ Standard 60min"]["dances"], ["Jive"])

    def test_a_custom_file_that_is_a_list_does_not_stop_the_editor(self):
        with open(self.custom_path, "w", encoding="utf-8") as handle:
            handle.write("[]")
        self.screen.load_practice_types()          # must not raise
        self.assertEqual(self.screen.custom_types, {})
        self.assertIn("LineDance", self.screen.practice_types)

    def test_a_definition_that_is_not_an_object_is_skipped(self):
        with open(self.custom_path, "w", encoding="utf-8") as handle:
            json.dump({"Broken": [], "Fine": {"dances": ["Waltz"]}}, handle)
        self.screen.load_practice_types()
        self.assertNotIn("Broken", self.screen.custom_types)
        self.assertIn("Fine", self.screen.custom_types)

    def test_truncated_json_is_ignored(self):
        with open(self.custom_path, "w", encoding="utf-8") as handle:
            handle.write('{"Broken": ')
        self.screen.load_practice_types()
        self.assertEqual(self.screen.custom_types, {})

    def test_comments_are_not_shown_as_practice_types(self):
        with open(self.custom_path, "w", encoding="utf-8") as handle:
            json.dump({"__COMMENT__ note": {}, "Real": {"dances": ["Waltz"]}}, handle)
        self.screen.load_practice_types()
        self.assertEqual(list(self.screen.custom_types), ["Real"])

    def test_loading_a_type_into_the_form_populates_every_field(self):
        self.select("Silver+ Standard 60min")
        self.assertEqual(self.form().name_input.text, "Silver+ Standard 60min")
        self.assertEqual(self.form().dances_input.text, "Waltz, Tango")
        self.assertEqual(self.form().num_selections_input.text, "4")
        self.assertIn("VienneseWaltz", self.form().dance_max_playtimes_input.text)


class TestSaving(EditorTestCase):
    """Creating, renaming, and overriding."""

    def test_a_new_practice_type_is_written(self):
        self.fill(name="Evening Practice")
        self.screen.save_current_practice_type()
        self.assertIn("Evening Practice", self.saved())
        self.assertEqual(self.saved()["Evening Practice"]["dances"], ["Waltz", "Tango"])

    def test_saving_leaves_no_temporary_file(self):
        self.fill(name="Evening Practice")
        self.screen.save_current_practice_type()
        self.assertEqual(os.listdir(self.tmp),
                         sorted(["builtin_practice_types.json", "custom_practice_types.json"]))

    def test_renaming_removes_the_old_entry(self):
        self.fill(name="First")
        self.screen.save_current_practice_type()
        self.fill(name="Second")
        self.screen.current_practice_type_name = "First"
        self.screen.save_current_practice_type()
        self.assertNotIn("First", self.saved())
        self.assertIn("Second", self.saved())

    def test_saving_over_a_builtin_creates_an_override_only(self):
        self.select("LineDance")
        self.form().num_selections_input.text = "9"
        self.screen.save_current_practice_type()

        self.assertEqual(self.saved()["LineDance"]["num_selections"], 9)
        with open(self.builtin_path, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["LineDance"]["num_selections"], 1)

    def test_comments_in_the_custom_file_are_preserved(self):
        with open(self.custom_path, "w", encoding="utf-8") as handle:
            json.dump({"__COMMENT__ keep me": {"note": 1}}, handle)
        self.screen.load_practice_types()
        self.fill(name="Another")
        self.screen.save_current_practice_type()
        self.assertIn("__COMMENT__ keep me", self.saved())

    def test_an_empty_name_is_refused(self):
        self.fill(name="   ")
        self.screen.save_current_practice_type()
        self.assertEqual(self.saved(), {})
        self.assertEqual(self.popups[-1][0], "Error")

    def test_unparsable_json_in_a_field_is_refused(self):
        self.fill(name="Bad JSON", playtimes="{not json}")
        self.screen.save_current_practice_type()
        self.assertEqual(self.saved(), {})
        self.assertIn("Invalid data format", self.popups[-1][1])

    def test_a_write_failure_is_reported_and_loses_nothing(self):
        self.fill(name="First")
        self.screen.save_current_practice_type()
        self.fill(name="Second")
        with patch("practice_type_editor.json.dump", side_effect=OSError("disk full")):
            self.screen.save_current_practice_type()
        self.assertEqual(list(self.saved()), ["First"])
        self.assertEqual(self.popups[-1][0], "Error")


class TestFieldValidation(EditorTestCase):
    """Fields that parse as JSON but are the wrong shape must not be saved.

    These break the player later, when the value is assigned to a Kivy property
    during startup, which is a long way from the editor that accepted them.
    """

    def _refused(self, **fields):
        self.fill(name="Suspect", **fields)
        self.screen.save_current_practice_type()
        self.assertEqual(self.saved(), {}, "the definition should not have been saved")
        self.assertEqual(self.popups[-1][0], "Invalid Practice Type")
        return self.popups[-1][1]

    def test_dance_max_playtimes_as_a_list_is_refused(self):
        self.assertIn("Dance Max Playtimes", self._refused(playtimes="[]"))

    def test_dance_adjustments_as_a_number_is_refused(self):
        self.assertIn("Dance Adjustments", self._refused(adjustments="5"))

    def test_dance_minutes_as_a_list_is_refused(self):
        self.assertIn("Dance Minutes", self._refused(minutes="[13]"))

    def test_segments_as_an_object_is_refused(self):
        self.assertIn("Segments", self._refused(segments="{}"))

    def test_non_numeric_playtime_is_refused(self):
        self.assertIn("must be a number", self._refused(playtimes='{"Waltz": "long"}'))

    def test_an_infinite_playtime_is_refused(self):
        """Infinity is a float greater than zero, so a type-and-sign test passed it."""
        self.assertIn("ordinary number", self._refused(playtimes='{"Waltz": Infinity}'))

    def test_a_negative_infinite_playtime_is_refused(self):
        self.assertIn("ordinary number", self._refused(playtimes='{"Waltz": -Infinity}'))

    def test_a_nan_playtime_is_refused(self):
        self.assertIn("ordinary number", self._refused(playtimes='{"Waltz": NaN}'))

    def test_an_infinite_block_budget_is_refused(self):
        self.assertIn("ordinary number", self._refused(minutes='{"Waltz": Infinity}'))

    def test_a_nan_block_budget_is_refused(self):
        self.assertIn("ordinary number", self._refused(minutes='{"Waltz": NaN}'))

    def test_an_enormous_playtime_is_refused(self):
        self.assertIn("too large", self._refused(playtimes='{"Waltz": 1' + "0" * 400 + '}'))

    def test_negative_playtime_is_refused(self):
        self.assertIn("positive", self._refused(playtimes='{"Waltz": -5}'))

    def test_zero_minutes_is_refused(self):
        self.assertIn("positive", self._refused(minutes='{"Waltz": 0}'))

    def test_no_dances_is_refused(self):
        self.assertIn("at least one dance", self._refused(dances=""))

    def test_an_empty_dance_entry_is_refused(self):
        self.assertIn("empty entries", self._refused(dances="Waltz,,Tango"))

    def test_zero_selections_is_refused(self):
        self.assertIn("Num Selections", self._refused(selections="0"))

    def test_a_valid_definition_is_accepted(self):
        self.fill(name="Good", playtimes='{"VienneseWaltz": 150}',
                  minutes='{"Waltz": 13}', segments='[]')
        self.screen.save_current_practice_type()
        self.assertIn("Good", self.saved())


class TestDeleting(EditorTestCase):
    """Deleting a custom type, and deleting an override."""

    def test_a_custom_type_is_removed(self):
        self.fill(name="Temporary")
        self.screen.save_current_practice_type()
        self.screen.current_practice_type_name = "Temporary"
        self.screen.delete_practice_type()
        self.assertNotIn("Temporary", self.saved())

    def test_deleting_an_override_restores_the_builtin(self):
        self.select("LineDance")
        self.form().num_selections_input.text = "9"
        self.screen.save_current_practice_type()

        self.screen.current_practice_type_name = "LineDance"
        self.screen.delete_practice_type()

        self.assertNotIn("LineDance", self.saved())
        self.screen.load_practice_types()
        self.assertEqual(self.screen.practice_types["LineDance"]["num_selections"], 1)
        self.assertEqual(self.popups[-1][0], "Reverted")

    def test_deleting_a_builtin_that_was_never_overridden_is_refused(self):
        self.screen.current_practice_type_name = "Silver+ Standard 60min"
        self.screen.delete_practice_type()
        self.assertIn("Silver+ Standard 60min", self.screen.practice_types)

    def test_deleting_with_nothing_selected_is_harmless(self):
        self.screen.current_practice_type_name = None
        self.screen.delete_practice_type()


class TestFormHelpers(EditorTestCase):
    """New, Copy and Reset."""

    def test_new_clears_the_name_and_offers_a_template(self):
        self.select("LineDance")
        self.screen.clear_form()
        self.assertEqual(self.form().name_input.text, "")
        self.assertIsNone(self.screen.current_practice_type_name)
        self.assertTrue(self.form().dances_input.text)

    def test_copy_keeps_the_fields_but_clears_the_name(self):
        self.select("Silver+ Standard 60min")
        self.screen.copy_practice_type()
        self.assertEqual(self.form().name_input.text, "")
        self.assertEqual(self.form().dances_input.text, "Waltz, Tango")
        self.assertIsNone(self.screen.current_practice_type_name)

    def test_copy_then_save_creates_a_second_type(self):
        self.select("Silver+ Standard 60min")
        self.screen.copy_practice_type()
        self.form().name_input.text = "Copy of Standard"
        self.screen.save_current_practice_type()
        self.assertIn("Copy of Standard", self.saved())

    def test_reset_with_nothing_selected_explains_itself(self):
        self.screen.current_practice_type_name = None
        self.screen.reset_current_practice_type()
        self.assertEqual(self.popups[-1][0], "Info")


class TestReturningToThePlayer(EditorTestCase):
    """Going back must regenerate only when something actually changed.

    Regenerating needlessly interrupts a playlist that is already loaded, and
    failing to regenerate leaves the player using settings that were just edited.
    """

    def setUp(self):
        super().setUp()
        self.player = MagicMock()
        self.player.practice_type = "LineDance"
        self.manager = MagicMock()
        self.screen.manager = self.manager
        self.screen._player_widget = lambda: self.player

    def test_choosing_a_different_type_switches_the_player_to_it(self):
        self.screen.current_practice_type_name = "Silver+ Standard 60min"
        self.screen.go_back_to_player()
        self.assertEqual(self.player.practice_type, "Silver+ Standard 60min")
        self.manager.reload_custom_types.assert_not_called()
        self.assertEqual(self.manager.current, "player")

    def test_saving_the_active_type_forces_a_reload(self):
        self.screen.current_practice_type_name = "LineDance"
        self.screen.changes_saved_since_enter = True
        self.screen.go_back_to_player()
        self.manager.reload_custom_types.assert_called_once()

    def test_looking_without_changing_anything_leaves_the_playlist_alone(self):
        self.screen.current_practice_type_name = "LineDance"
        self.screen.changes_saved_since_enter = False
        self.screen.go_back_to_player()
        self.manager.reload_custom_types.assert_not_called()
        self.assertEqual(self.player.practice_type, "LineDance")
        self.assertEqual(self.manager.current, "player")

    def test_nothing_selected_just_returns(self):
        self.screen.current_practice_type_name = None
        self.screen.changes_saved_since_enter = False
        self.screen.go_back_to_player()
        self.manager.reload_custom_types.assert_not_called()
        self.assertEqual(self.manager.current, "player")

    def test_no_running_player_still_returns_to_the_player_screen(self):
        self.screen._player_widget = lambda: None
        self.screen.current_practice_type_name = "Silver+ Standard 60min"
        self.screen.go_back_to_player()
        self.assertEqual(self.manager.current, "player")

    def test_entering_the_screen_schedules_a_reload(self):
        self.screen.changes_saved_since_enter = True
        with patch("practice_type_editor.Clock.schedule_once") as schedule:
            self.screen.on_enter()
        self.assertFalse(self.screen.changes_saved_since_enter)
        schedule.assert_called_once()

    def test_the_player_widget_is_found_when_the_app_is_running(self):
        app = MagicMock()
        app.manager.get_screen.return_value.children = ["the-player"]
        with patch("practice_type_editor.App.get_running_app", return_value=app):
            self.assertEqual(PracticeTypeEditorScreen._player_widget(), "the-player")

    def test_no_running_app_yields_no_player_widget(self):
        with patch("practice_type_editor.App.get_running_app", return_value=None):
            self.assertIsNone(PracticeTypeEditorScreen._player_widget())

    def test_an_app_without_a_screen_manager_yields_none(self):
        app = MagicMock()
        app.manager = None
        with patch("practice_type_editor.App.get_running_app", return_value=app):
            self.assertIsNone(PracticeTypeEditorScreen._player_widget())

    def test_a_missing_player_screen_yields_none(self):
        app = MagicMock()
        app.manager.get_screen.side_effect = ValueError("no such screen")
        with patch("practice_type_editor.App.get_running_app", return_value=app):
            self.assertIsNone(PracticeTypeEditorScreen._player_widget())

    def test_the_deferred_load_populates_the_list(self):
        self.screen.practice_type_list_layout = MagicMock()
        self.screen._deferred_load_and_display(0)
        self.assertIn("LineDance", self.screen.practice_types)
        self.screen.display_practice_type_list.assert_called()


class TestSavingRepairsAnInvalidFile(EditorTestCase):
    """A custom file that is not an object must not block saving."""

    def test_saving_over_a_top_level_list_succeeds(self):
        with open(self.custom_path, "w", encoding="utf-8") as handle:
            handle.write("[]")
        self.screen.load_practice_types()
        self.fill(name="Fresh Start")
        self.screen.save_current_practice_type()
        self.assertIn("Fresh Start", self.saved())
        self.assertEqual(self.popups[-1][0], "Success")

    def test_saving_over_a_scalar_succeeds(self):
        with open(self.custom_path, "w", encoding="utf-8") as handle:
            handle.write('"practice types"')
        self.screen.load_practice_types()
        self.fill(name="Fresh Start")
        self.screen.save_current_practice_type()
        self.assertIn("Fresh Start", self.saved())

    def test_saving_over_truncated_json_succeeds(self):
        with open(self.custom_path, "w", encoding="utf-8") as handle:
            handle.write('{"Half": ')
        self.screen.load_practice_types()
        self.fill(name="Fresh Start")
        self.screen.save_current_practice_type()
        self.assertIn("Fresh Start", self.saved())


class TestRenameIsTransactional(EditorTestCase):
    """A rename that fails must not remove the original."""

    def setUp(self):
        super().setUp()
        self.fill(name="Original")
        self.screen.save_current_practice_type()

    def test_a_failed_rename_keeps_the_original_in_memory(self):
        self.fill(name="Renamed", playtimes="{not json}")
        self.screen.current_practice_type_name = "Original"
        self.screen.save_current_practice_type()
        self.assertIn("Original", self.screen.custom_types)
        self.assertNotIn("Renamed", self.screen.custom_types)

    def test_a_failed_rename_does_not_delete_the_original_on_a_later_save(self):
        """The original bug: the deletion was written by the *next* save."""
        self.fill(name="Renamed", playtimes="{not json}")
        self.screen.current_practice_type_name = "Original"
        self.screen.save_current_practice_type()

        self.fill(name="Something Else")
        self.screen.current_practice_type_name = None
        self.screen.save_current_practice_type()

        self.assertIn("Original", self.saved())
        self.assertIn("Something Else", self.saved())

    def test_a_rename_refused_by_field_validation_keeps_the_original(self):
        self.fill(name="Renamed", playtimes='{"Waltz": -5}')
        self.screen.current_practice_type_name = "Original"
        self.screen.save_current_practice_type()
        self.assertEqual(self.popups[-1][0], "Invalid Practice Type")
        self.assertIn("Original", self.saved())

    def test_a_successful_rename_still_replaces_the_original(self):
        self.fill(name="Renamed")
        self.screen.current_practice_type_name = "Original"
        self.screen.save_current_practice_type()
        self.assertNotIn("Original", self.saved())
        self.assertIn("Renamed", self.saved())

    def test_a_failed_write_does_not_rename_the_active_practice(self):
        """The player and music.ini must not name a type that was never saved."""
        player = MagicMock()
        player.practice_type = "Original"
        self.screen._player_widget = lambda: player

        self.fill(name="Renamed")
        self.screen.current_practice_type_name = "Original"
        with patch("practice_type_editor.json.dump", side_effect=OSError("disk full")):
            self.screen.save_current_practice_type()

        self.assertEqual(player.practice_type, "Original")
        self.assertIn("Original", self.screen.custom_types)
        self.assertIn("Original", self.saved())
        self.assertEqual(self.screen.current_practice_type_name, "Original")

    def test_a_successful_rename_does_move_the_active_practice(self):
        player = MagicMock()
        player.practice_type = "Original"
        self.screen._player_widget = lambda: player

        self.fill(name="Renamed")
        self.screen.current_practice_type_name = "Original"
        self.screen.save_current_practice_type()

        self.assertEqual(player.practice_type, "Renamed")
        self.assertIn("Renamed", self.saved())

    def test_a_rename_of_an_inactive_practice_leaves_the_player_alone(self):
        player = MagicMock()
        player.practice_type = "Something Else"
        self.screen._player_widget = lambda: player

        self.fill(name="Renamed")
        self.screen.current_practice_type_name = "Original"
        self.screen.save_current_practice_type()

        self.assertEqual(player.practice_type, "Something Else")

    def test_a_failed_write_restores_the_in_memory_copy(self):
        self.fill(name="Renamed")
        self.screen.current_practice_type_name = "Original"
        with patch("practice_type_editor.json.dump", side_effect=OSError("disk full")):
            self.screen.save_current_practice_type()
        self.assertIn("Original", self.screen.custom_types)
        self.assertNotIn("Renamed", self.screen.custom_types)
        self.assertEqual(self.screen.current_practice_type_name, "Original")


class TestSharedRuleValidation(EditorTestCase):
    """The editor applies the same rules the player would."""

    def _refused(self, **fields):
        self.fill(name="Suspect", **fields)
        self.screen.save_current_practice_type()
        self.assertEqual(self.saved(), {})
        self.assertEqual(self.popups[-1][0], "Invalid Practice Type")
        return self.popups[-1][1]

    def test_an_unknown_adjustment_rule_is_refused(self):
        self.assertIn("unknown rule", self._refused(adjustments='{"Waltz": "half"}'))

    def test_a_non_numeric_adjustment_result_is_refused(self):
        self.assertIn("whole number", self._refused(adjustments='{"Waltz": {"2": "two"}}'))

    def test_a_negative_adjustment_result_is_refused(self):
        self.assertIn("negative", self._refused(adjustments='{"Waltz": {"2": -3}}'))

    def test_a_negative_clip_length_is_refused(self):
        self.assertIn("clip_seconds", self._refused(
            segments='[{"round": ["Waltz"], "clip_seconds": -10}]'))

    def test_a_negative_gap_is_refused(self):
        self.assertIn("gap_seconds", self._refused(
            segments='[{"round": ["Waltz"], "gap_seconds": -5}]'))

    def test_an_empty_dance_name_in_a_round_is_refused(self):
        self.assertIn("dance names", self._refused(
            segments='[{"round": ["", "Waltz"]}]'))

    def test_the_list_position_survives_a_round_trip(self):
        self.fill(name="At The Bottom", order="30")
        self.screen.save_current_practice_type()
        self.assertEqual(self.saved()["At The Bottom"]["order"], 30)

    def test_dance_intros_survive_a_round_trip(self):
        """The editor rebuilds a type from its fields; a dropped key is silent."""
        self.fill(name="Quiet Practice", intros='{"default": "gap_10", "PasoDoble": "announce"}')
        self.screen.save_current_practice_type()
        self.assertEqual(self.saved()["Quiet Practice"]["dance_intros"],
                         {"default": "gap_10", "PasoDoble": "announce"})

    def test_an_unknown_intro_is_refused(self):
        self.assertIn("Dance Intros", self._refused(intros='{"Waltz": "shout it"}'))

    def test_a_cue_name_that_escapes_the_cues_folder_is_refused(self):
        self.assertIn("Dance Intros", self._refused(intros='{"Waltz": "../../secrets"}'))

    def test_a_cue_that_does_not_exist_is_refused(self):
        """A typo would otherwise show up as silence that never happens."""
        message = self._refused(intros='{"Waltz": "gap_11"}')
        self.assertIn("no cue named", message)
        self.assertIn("gap_10", message, "it should say what is available")

    def test_a_segment_naming_a_missing_cue_is_refused(self):
        self.assertIn("no cue named",
                      self._refused(segments='[{"cue": "no_such_cue"}]'))

    def test_an_existing_cue_is_accepted(self):
        self.fill(name="Quiet", intros='{"default": "gap_10"}')
        self.screen.save_current_practice_type()
        self.assertIn("Quiet", self.saved())

    def test_announce_and_none_are_accepted(self):
        self.fill(name="Mixed", intros='{"Waltz": "announce", "Tango": "none"}')
        self.screen.save_current_practice_type()
        self.assertIn("Mixed", self.saved())

    def test_valid_adjustments_and_segments_are_accepted(self):
        self.fill(name="Good", adjustments='{"VienneseWaltz": "n-1", "PasoDoble": {"2": 1}}',
                  segments='[{"cue": "round_gap"}, {"round": ["Waltz"], "clip_seconds": 90}]')
        self.screen.save_current_practice_type()
        self.assertIn("Good", self.saved())


class TestEditingPreservesExistingFields(EditorTestCase):
    """Selecting a practice type and saving it must not quietly drop what it had.

    The editor rebuilds a definition from its form fields, so a field that fails
    to load is indistinguishable from one the user cleared. Nothing complains;
    the setting is simply gone the next time the practice runs.
    """

    DEFINITION = {
        "dances": ["Waltz", "Tango"],
        "num_selections": 2,
        "dance_intros": {"default": "gap_10", "PasoDoble": "announce"},
        "dance_minutes": {"Waltz": 13},
        "dance_max_playtimes": {"VienneseWaltz": 150},
        "order": 20,
    }

    def setUp(self):
        super().setUp()
        with open(self.custom_path, "w", encoding="utf-8") as handle:
            json.dump({"Quiet Practice": self.DEFINITION}, handle)
        self.screen.load_practice_types()

    def test_the_intros_reach_the_form(self):
        self.select("Quiet Practice")
        self.assertIn("gap_10", self.form().dance_intros_input.text)
        self.assertIn("PasoDoble", self.form().dance_intros_input.text)

    def test_the_intros_survive_a_save(self):
        self.select("Quiet Practice")
        self.screen.save_current_practice_type()
        self.assertEqual(self.saved()["Quiet Practice"]["dance_intros"],
                         self.DEFINITION["dance_intros"])

    def test_an_unrelated_edit_leaves_the_intros_alone(self):
        """Changing the song count must not turn the announcements back on."""
        self.select("Quiet Practice")
        self.form().num_selections_input.text = "4"
        self.screen.save_current_practice_type()
        saved = self.saved()["Quiet Practice"]
        self.assertEqual(saved["num_selections"], 4)
        self.assertEqual(saved["dance_intros"], self.DEFINITION["dance_intros"])

    def test_every_other_field_survives_too(self):
        self.select("Quiet Practice")
        self.screen.save_current_practice_type()
        saved = self.saved()["Quiet Practice"]
        for key in ("dance_minutes", "dance_max_playtimes", "order"):
            self.assertEqual(saved[key], self.DEFINITION[key], key)

    def test_new_does_not_carry_the_intros_into_the_next_type(self):
        self.select("Quiet Practice")
        self.screen.clear_form()
        self.assertEqual(self.form().dance_intros_input.text, "")


class TestCueNamesAreMatchedLikeThePlayer(EditorTestCase):
    """The player resolves cue names without regard to case; so must the editor."""

    def _saves(self, **fields):
        self.fill(**fields)
        self.screen.save_current_practice_type()
        return fields["name"] in self.saved()

    def test_an_intro_cue_in_a_different_case_is_accepted(self):
        self.assertTrue(self._saves(name="Loud", intros='{"default": "GAP_10"}'))

    def test_a_segment_cue_in_a_different_case_is_accepted(self):
        self.assertTrue(self._saves(name="Rounds", segments='[{"cue": "ROUND_GAP"}]'))

    def test_a_cue_that_really_is_missing_is_still_refused(self):
        self.assertFalse(self._saves(name="Typo", intros='{"default": "gap_11"}'))
        self.assertEqual(self.popups[-1][0], "Invalid Practice Type")

    def test_the_message_keeps_the_spelling_that_was_typed(self):
        self.fill(name="Typo", intros='{"default": "Gap_Eleven"}')
        self.screen.save_current_practice_type()
        self.assertIn("Gap_Eleven", self.popups[-1][1])


if __name__ == "__main__":
    unittest.main()
