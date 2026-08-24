# practice_type_editor.py
"""
Provides a Kivy Screen for creating, editing, and deleting custom practice types
for the Dance Practice Music Player. Supports separate built-in and user files.
"""
import json
import os
from functools import partial
from kivy.app import App
from kivy.uix.screenmanager import Screen
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
# pylint: disable=no-name-in-module
from kivy.properties import ObjectProperty, StringProperty
from kivy.lang import Builder
from kivy.clock import Clock

import app_paths
import practice_type_rules


class PracticeTypeEditorScreen(Screen):
    """
    The main screen widget for the practice type editor. It handles loading
    practice types from both Built-in (Read-only) and Custom (Read-write) sources,
    merging them for display.
    """
    practice_type_list_layout = ObjectProperty(None)
    edit_form = ObjectProperty(None)
    current_practice_type_name = StringProperty(None, allownone=True)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.script_path = os.path.dirname(os.path.abspath(__file__))
        
        # Split paths: one for shipping (read-only), one for user edits (read-write).
        # The writable one follows the player's rule: beside the application when
        # that is writable, otherwise the per-user data directory.
        self.builtin_path = app_paths.app_path("builtin_practice_types.json")
        self.custom_path = app_paths.user_path("custom_practice_types.json")

        self.builtin_types = {}
        self.custom_types = {}
        self.practice_types = {} # This represents the combined/merged view
        
        self._current_button = None
        self.changes_saved_since_enter = False

    def on_enter(self, *args):
        """Called when the screen is entered."""
        self.changes_saved_since_enter = False
        
        # Schedule loading with a small buffer (0.1s) to allow 
        # OS file locks to clear and widgets to initialize.
        Clock.schedule_once(self._deferred_load_and_display, 0.1)

    def _deferred_load_and_display(self, dt):
        """Load data and update UI after screen has fully initialized."""
        # 1. Load Data (now safe from race conditions)
        self.load_practice_types()
        
        # 2. Update UI (now safe from widget binding issues)
        if self.practice_type_list_layout:
            self.display_practice_type_list()
            self.clear_form()
        else:
            print("WARNING: Layout not ready even after delay.")

    def _load_json_file(self, path):
        """Helper to safely load a JSON file."""
        if not os.path.exists(path):
            return {}
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"Warning loading {path}: {e}")
            return {}

        # Valid JSON is not necessarily a practice type file; calling .items() on
        # a list here would stop the editor from opening.
        if not isinstance(data, dict):
            print(f"Ignoring {os.path.basename(path)}: it must contain a JSON object, "
                  f"not {type(data).__name__}.")
            return {}

        # Filter out comment keys, and definitions that are not objects
        return {k: v for k, v in data.items()
                if not k.startswith("__COMMENT__") and isinstance(v, dict)}

    def load_practice_types(self):
        """
        Loads practice types from both the built-in JSON and the user's local
        custom JSON, merging them so custom overrides built-in.
        """
        self.builtin_types = self._load_json_file(self.builtin_path)

        # If custom file doesn't exist, we just start with an empty dict for it
        # (It will be created on first save)
        self.custom_types = self._load_json_file(self.custom_path)

        # Merge strategy: Built-ins first, then Custom overrides them
        self.practice_types = self.builtin_types.copy()
        self.practice_types.update(self.custom_types)

    def save_practice_types(self):
        """
        Saves ONLY the custom types to the user-writable JSON file.
        Returns True on success, False on failure.
        """
        try:
            # 1. Read original custom file to preserve comments (if it exists)
            current_file_data = {}
            if os.path.exists(self.custom_path):
                try:
                    with open(self.custom_path, 'r', encoding='utf-8') as f:
                        current_file_data = json.load(f)
                except (OSError, json.JSONDecodeError):
                    current_file_data = {}
                # The file is re-read to preserve its comments, but it may be
                # the same structurally invalid file the loader already skipped.
                # Without this, saving fails and the user has to repair the file
                # by hand before the editor becomes usable again.
                if not isinstance(current_file_data, dict):
                    print(f"Replacing {os.path.basename(self.custom_path)}: "
                          "it did not contain a JSON object.")
                    current_file_data = {}

            # 2. Update only the non-comment keys based on self.custom_types
            for key in self.custom_types:
                current_file_data[key] = self.custom_types[key]

            # 3. Find keys to delete (present in file but removed from our active custom dict)
            # We ignore __COMMENT__ keys so they aren't deleted
            keys_to_delete = [
                k for k in current_file_data 
                if not k.startswith("__COMMENT__") and k not in self.custom_types
            ]
            for key in keys_to_delete:
                del current_file_data[key]

            # 4. Write back to the custom file, via a temporary file so that
            # losing power mid-write cannot truncate it. A corrupt history is
            # discarded harmlessly on the next run, but corrupt practice types
            # are silently ignored, which is much harder to notice.
            temporary = f"{self.custom_path}.tmp"
            with open(temporary, 'w', encoding='utf-8') as f:
                json.dump(current_file_data, f, indent=4)
            os.replace(temporary, self.custom_path)
            
            # Reload to ensure the merged view (self.practice_types) is perfectly synced
            self.load_practice_types()
            self.display_practice_type_list()
            return True 
        except (OSError, TypeError) as e:
            self.show_popup("Error", f"Failed to save Practice Types: {e}")
            return False

    def display_practice_type_list(self):
        """Populates the scroll view with buttons for each practice type."""
        self.practice_type_list_layout.clear_widgets()
        self._current_button = None

        sorted_names = sorted(self.practice_types.keys())
        for name in sorted_names:
            # Visual cue: Green text for custom/overridden types, White for built-ins
            is_custom = name in self.custom_types
            
            # Note: We use color (text color) to distinguish, keeping background consistent
            # unless selected.
            text_color = (0.5, 1, 0.5, 1) if is_custom else (1, 1, 1, 1)
            
            btn = Button(
                text=name, 
                size_hint_y=None, 
                height=40,
                color=text_color
            )
            btn.bind(on_press=partial(self.load_practice_type_into_form, btn, name))  # pylint: disable=no-member
            self.practice_type_list_layout.add_widget(btn)

    def load_practice_type_into_form(self, button_instance, name, *_args):
        """Loads the selected practice type's data into the form and highlights the button."""
        # Reset the color of the previously selected button, if it exists
        if self._current_button:
            self._current_button.background_color = (1, 1, 1, 1) # Default background

        # Set the color of the newly clicked button
        button_instance.background_color = (0, 1, 1, 1) # Highlight background (cyan)
        self._current_button = button_instance

        self.current_practice_type_name = name
        data = self.practice_types[name]

        # Populate form fields
        self.edit_form.name_input.text = name
        self.edit_form.dances_input.text = ", ".join(data.get("dances", []))
        self.edit_form.num_selections_input.text = str(data.get("num_selections", 1))
        self.edit_form.order_input.text = str(data.get("order", 0))
        self.edit_form.play_all_songs_input.active = data.get("play_all_songs", False)
        self.edit_form.auto_update_input.active = data.get("auto_update", False)
        self.edit_form.play_single_song_input.active = data.get("play_single_song", False)
        self.edit_form.randomize_playlist_input.active = data.get("randomize_playlist", True)
        self.edit_form.adjust_song_counts_input.active = data.get("adjust_song_counts", False)

        adjustments = data.get("dance_adjustments", {})
        if adjustments:
            self.edit_form.dance_adjustments_input.text = json.dumps(adjustments, indent=4)
        else:
            self.edit_form.dance_adjustments_input.text = ""

        playtimes = data.get("dance_max_playtimes", {})
        if playtimes:
            self.edit_form.dance_max_playtimes_input.text = json.dumps(playtimes, indent=4)
        else:
            self.edit_form.dance_max_playtimes_input.text = ""

        intros = data.get("dance_intros", {})
        if intros:
            self.edit_form.dance_intros_input.text = json.dumps(intros, indent=4)
        else:
            self.edit_form.dance_intros_input.text = ""

        minutes = data.get("dance_minutes", {})
        if minutes:
            self.edit_form.dance_minutes_input.text = json.dumps(minutes, indent=4)
        else:
            self.edit_form.dance_minutes_input.text = ""

        segments = data.get("segments", [])
        if segments:
            self.edit_form.segments_input.text = json.dumps(segments, indent=4)
        else:
            self.edit_form.segments_input.text = ""

    @staticmethod
    def _player_widget():
        """Returns the player widget, or None if there is no running app.

        Saving should not depend on the app being up: without this guard a rename
        raises AttributeError before the practice type is written to disk.
        """
        app = App.get_running_app()
        if app is None or getattr(app, "manager", None) is None:
            return None
        try:
            return app.manager.get_screen('player').children[0]
        except (ValueError, IndexError, AttributeError):
            return None

    @staticmethod
    def _available_cues():
        """Returns the cue names present in cues/, without their extensions."""
        cue_dir = app_paths.app_path("cues")
        try:
            entries = os.listdir(cue_dir)
        except OSError:
            return set()
        return {os.path.splitext(name)[0] for name in entries
                if name.lower().endswith((".ogg", ".mp3", ".wav", ".flac", ".m4a"))}

    def _check_cues_exist(self, data, problems):
        """Adds a problem for any cue named that is not in cues/.

        The player copes with a missing cue by warning and starting the block
        without it, which is the right behaviour there but a poor way to learn
        about a typo -- the silence simply does not happen, in the middle of a
        practice. The editor can see the folder, so it refuses instead.
        """
        available = self._available_cues()
        # Compared without regard to case, because that is how the player looks
        # cues up. Refusing "GAP_10" while the player would load gap_10.ogg
        # would be the editor disagreeing with the thing it validates for.
        folded = {name.casefold() for name in available}

        named = set()
        if isinstance(data.get("dance_intros"), dict):
            named |= {value for value in data["dance_intros"].values()
                      if isinstance(value, str)
                      and value not in (practice_type_rules.INTRO_ANNOUNCE,
                                        practice_type_rules.INTRO_NONE)}
        if isinstance(data.get("segments"), list):
            named |= {segment["cue"] for segment in data["segments"]
                      if isinstance(segment, dict) and isinstance(segment.get("cue"), str)}

        # The original spelling is kept for the message; only the comparison folds.
        for cue in sorted(name for name in named if name.casefold() not in folded):
            problems.append(
                f"Dance Intros / Segments: there is no cue named \"{cue}\" in cues/. "
                f"Available: {', '.join(sorted(available)) or 'none'}.")

    def _validation_problems(self, data):
        """Returns a list of reasons the practice type cannot be saved.

        The form already checks that each JSON field parses; this checks that it
        parsed into the right shape. A field of the wrong type is accepted by
        JSON but breaks the player later -- a list where a dictionary is expected
        raises when the value is assigned to a Kivy property during startup.

        Args:
            data: The practice type about to be saved.

        Returns:
            Human-readable problems, empty if the definition is usable.
        """
        problems = []

        if not data["dances"] or not any(d.strip() for d in data["dances"]):
            problems.append("Dances: at least one dance is required.")
        elif any(not d.strip() for d in data["dances"]):
            problems.append("Dances: remove the empty entries "
                            "(usually a trailing or doubled comma).")

        if data["num_selections"] < 1:
            problems.append("Num Selections: must be at least 1.")

        for label, key in (("Dance Max Playtimes", "dance_max_playtimes"),
                           ("Dance Minutes", "dance_minutes")):
            value = data.get(key)
            if not isinstance(value, dict):
                problems.append(
                    f"{label}: must be a JSON object like "
                    f'{{"Waltz": ...}}, not a {type(value).__name__}.')

        # The rules the player applies, so the editor cannot save a definition
        # the player would have to repair or ignore.
        practice_type_rules.validate_dance_adjustments(
            data.get("dance_adjustments"), problems.append)
        practice_type_rules.validate_dance_intros(
            data.get("dance_intros"), problems.append)
        self._check_cues_exist(data, problems)
        practice_type_rules.validate_segments(data.get("segments"), problems.append)

        # Durations go through the player's own number check, so the editor
        # cannot save a value the player would then silently drop -- Infinity is
        # a float greater than zero, and used to pass a type-and-sign test.
        for label, key in (("Dance Max Playtimes", "dance_max_playtimes"),
                           ("Dance Minutes", "dance_minutes")):
            if not isinstance(data.get(key), dict):
                continue
            for dance, amount in data[key].items():
                number = practice_type_rules.strict_number(
                    amount, f"{label}: '{dance}'", problems.append)
                if number is None:
                    continue
                if number <= 0:
                    problems.append(f"{label}: '{dance}' must be positive.")

        return problems

    def save_current_practice_type(self):
        """Gathers data from the form and saves it to the custom_practice_types dict."""
        name = self.edit_form.name_input.text.strip()
        if not name:
            self.show_popup("Error", "Practice Type name cannot be empty.")
            return

        old_name = self.current_practice_type_name

        try:
            new_data = {
                "dances": [d.strip() for d in self.edit_form.dances_input.text.split(',')],
                "num_selections": int(self.edit_form.num_selections_input.text),
                "order": int(self.edit_form.order_input.text or 0),
                "play_all_songs": self.edit_form.play_all_songs_input.active,
                "auto_update": self.edit_form.auto_update_input.active,
                "play_single_song": self.edit_form.play_single_song_input.active,
                "randomize_playlist": self.edit_form.randomize_playlist_input.active,
                "adjust_song_counts": self.edit_form.adjust_song_counts_input.active,
                "dance_adjustments": json.loads(
                    self.edit_form.dance_adjustments_input.text or "{}"),
                "dance_max_playtimes": json.loads(
                    self.edit_form.dance_max_playtimes_input.text or "{}"),
                "dance_minutes": json.loads(
                    self.edit_form.dance_minutes_input.text or "{}"),
                "dance_intros": json.loads(
                    self.edit_form.dance_intros_input.text or "{}"),
                "segments": json.loads(
                    self.edit_form.segments_input.text or "[]"),
            }
            
            if problems := self._validation_problems(new_data):
                self.show_popup("Invalid Practice Type", "\n\n".join(problems))
                return

            # Prepare the change and keep it out of self.custom_types until the
            # write succeeds. Renaming used to remove the old entry before the
            # new one was parsed, so a rename that then failed validation left
            # the original missing -- and the next successful save in the same
            # session wrote that deletion to disk.
            # Note: We do NOT delete from builtin_types.
            previous = dict(self.custom_types)
            candidate = dict(self.custom_types)
            if old_name and old_name != name:
                candidate.pop(old_name, None)

            # Always save to custom types (this creates an override if name matches a built-in)
            candidate[name] = new_data
            self.custom_types = candidate
            self.current_practice_type_name = name

            if self.save_practice_types():
                # Only now that the file is written: setting practice_type
                # reconfigures the player and writes the name to music.ini, and
                # doing that before a failed write leaves the running session
                # pointing at a practice type that exists nowhere on disk.
                if old_name and old_name != name:
                    if player_widget := self._player_widget():
                        if player_widget.practice_type == old_name:
                            player_widget.practice_type = name

                self.changes_saved_since_enter = True
                self.show_popup("Success", "Practice Type saved successfully!")
            else:
                # The write failed and has already been reported; put the
                # in-memory copy back so nothing is lost from this session.
                self.custom_types = previous
                self.current_practice_type_name = old_name
                
        except (ValueError) as e:
            self.show_popup(
                "Error", f"Invalid data format: {e}\nCheck numeric fields and JSON formatting.")

    def delete_practice_type(self):
        """Deletes the currently selected practice type (from custom types)."""
        name = self.current_practice_type_name
        if not name:
            self.show_popup("Error", "No Practice Type selected.")
            return

        # Check if it's strictly a built-in type (not in custom)
        if name in self.builtin_types and name not in self.custom_types:
            self.show_popup("Error", "Cannot delete a built-in Practice Type.\nYou can only delete custom types or overrides.")
            return

        # It is in custom (either a new type or an override), so we can delete it
        if name in self.custom_types:
            del self.custom_types[name]

        if self.save_practice_types():
            # Check if we just deleted an override (meaning the built-in version reappears)
            if name in self.builtin_types:
                self.show_popup("Reverted", f"Override for '{name}' deleted.\nReverted to built-in default.")
            else:
                self.show_popup("Success", f"Practice Type '{name}' deleted successfully.")
            self.clear_form()

    def clear_form(self, *_args):
        """Resets the form to a template for a new practice type."""
        # Reset the color of the previously selected button, if it exists
        if self._current_button:
            self._current_button.background_color = (1, 1, 1, 1) # Default color
            self._current_button = None

        self.current_practice_type_name = None

        default_data = {
            "dances": [
                "Waltz", "Tango", "VWSlow", "VienneseWaltz", "Foxtrot", "QuickStep",
                "WCS", "Samba", "ChaCha", "Rumba", "PasoDoble", "JSlow", "Jive"
            ],
            "num_selections": 2,
            "play_all_songs": False,
            "auto_update": False,
            "play_single_song": False,
            "randomize_playlist": True,
            "adjust_song_counts": True,
            "dance_adjustments": {
                "PasoDoble": {"1": 0, "2": 1, "3": 1, "default": 2},
                "VWSlow": "cap_at_1", "JSlow": "cap_at_1",
                "VienneseWaltz": "n-1", "Jive": "n-1", "WCS": "cap_at_2"
            },
            "dance_max_playtimes": {"VienneseWaltz": 150},
            "dance_minutes": {}
        }

        self.edit_form.name_input.text = ""
        self.edit_form.dances_input.text = ", ".join(default_data["dances"])
        self.edit_form.num_selections_input.text = str(default_data["num_selections"])
        self.edit_form.order_input.text = "0"
        self.edit_form.play_all_songs_input.active = default_data["play_all_songs"]
        self.edit_form.auto_update_input.active = default_data["auto_update"]
        self.edit_form.play_single_song_input.active = default_data["play_single_song"]
        self.edit_form.randomize_playlist_input.active = default_data["randomize_playlist"]
        self.edit_form.adjust_song_counts_input.active = default_data["adjust_song_counts"]
        self.edit_form.dance_adjustments_input.text = json.dumps(
            default_data["dance_adjustments"], indent=4)
        self.edit_form.dance_max_playtimes_input.text = json.dumps(
            default_data["dance_max_playtimes"], indent=4)
        self.edit_form.dance_minutes_input.text = ""
        self.edit_form.dance_intros_input.text = ""
        self.edit_form.segments_input.text = ""

    def copy_practice_type(self, *_args):
        """Copies the currently loaded practice type data to create a new one."""
        if not self.current_practice_type_name:
            self.show_popup("Info", "Please select a Practice Type to copy first.")
            return

        self.edit_form.name_input.text = ""
        self.current_practice_type_name = None
        self.show_popup(
            "Copied",
            "Practice Type data copied.\nEnter a new name, edit as needed, and click Save.")

    def reset_current_practice_type(self, *_args):
        """Resets the form fields to the saved state of the current practice type."""
        if not self.current_practice_type_name:
            self.show_popup(
                "Info", "No Practice Type selected to reset.\nClick 'New' to load a template.")
            return

        # Use next() to find the first matching button and a named expression (:=)
        # to assign it to 'button_to_reset' within the if statement.
        if button_to_reset := next((btn for btn in self.practice_type_list_layout.children
                                if btn.text == self.current_practice_type_name), None):
            self.load_practice_type_into_form(button_to_reset, self.current_practice_type_name)
            self.show_popup(
                "Reset", f"'{self.current_practice_type_name}' has been reset to its saved state.")

    def go_back_to_player(self):
        """
        Switches back to the player. If a different practice type was chosen,
        or if the current practice type was edited and saved, the playlist is
        regenerated. Otherwise, it returns without interruption.
        """
        player_widget = self._player_widget()
        if player_widget is None:
            self.manager.current = 'player'
            return

        # Condition 1: A different practice type was selected.
        if ((new_type := self.current_practice_type_name) and
            new_type != player_widget.practice_type):
            # Condition 1: A different practice type was selected.
            # The property change will trigger the playlist reset automatically.
            player_widget.practice_type = new_type
        elif self.changes_saved_since_enter:
            # Condition 2: The current type's settings were saved.
            # Force a full reload to apply the new settings from the JSON file.
            self.manager.reload_custom_types()

        # If neither condition is met, no changes are made and the current
        # playlist is not interrupted.
        self.manager.current = 'player'

    def show_popup(self, title, message):
        """Utility function to show a popup with an OK button."""
        content_layout = BoxLayout(orientation='vertical', spacing=10, padding=10)
        message_label = Label(text=message, text_size=(380, None), size_hint_y=None)
        message_label.bind(texture_size=message_label.setter('size'))  # pylint: disable=no-member
        ok_button = Button(text="OK", size_hint_y=None, height='44dp')
        content_layout.add_widget(message_label)
        content_layout.add_widget(ok_button)
        popup = Popup(
            title=title, content=content_layout, size_hint=(None, None), size=('400dp', '220dp'))
        ok_button.bind(on_press=popup.dismiss)  # pylint: disable=no-member
        popup.open()


class EditForm(GridLayout):
    """The layout for the practice type editing form fields."""


Builder.load_string("""
#:kivy 1.11.1
#:import ScrollView kivy.uix.scrollview.ScrollView
#:import Switch kivy.uix.switch.Switch
#:import TextInput kivy.uix.textinput.TextInput
#:import Widget kivy.uix.widget.Widget

<EditForm>:
    cols: 1
    size_hint_y: None
    height: self.minimum_height
    padding: 10
    spacing: 10

    name_input: name_input
    dances_input: dances_input
    num_selections_input: num_selections_input
    order_input: order_input
    play_all_songs_input: play_all_songs_input
    auto_update_input: auto_update_input
    play_single_song_input: play_single_song_input
    randomize_playlist_input: randomize_playlist_input
    adjust_song_counts_input: adjust_song_counts_input
    dance_adjustments_input: dance_adjustments_input
    dance_max_playtimes_input: dance_max_playtimes_input
    dance_minutes_input: dance_minutes_input
    dance_intros_input: dance_intros_input
    segments_input: segments_input

    BoxLayout:
        size_hint_y: None
        height: '35dp'
        Label:
            text: 'Practice Type Name:'
            size_hint_x: 0.4
            text_size: self.size
            halign: 'left'
            valign: 'middle'
        TextInput:
            id: name_input
            multiline: False
            size_hint_x: 0.6

    BoxLayout:
        size_hint_y: None
        height: '60dp'
        Label:
            text: 'Dances (comma-separated):'
            size_hint_x: 0.4
            text_size: self.size
            halign: 'left'
            valign: 'top'
        TextInput:
            id: dances_input
            size_hint_x: 0.6

    BoxLayout:
        size_hint_y: None
        height: '35dp'
        Label:
            text: 'Num Selections Per Dance:'
            size_hint_x: 0.4
            text_size: self.size
            halign: 'left'
            valign: 'middle'
        TextInput:
            id: num_selections_input
            multiline: False
            size_hint_x: 0.6

    BoxLayout:
        size_hint_y: None
        height: '35dp'
        Label:
            text: 'List Position:'
            size_hint_x: 0.4
            text_size: self.size
            halign: 'left'
            valign: 'middle'
        TextInput:
            id: order_input
            multiline: False
            size_hint_x: 0.6
    Label:
        text: "0 keeps this type where it is in the file; a higher number sinks it towards the bottom of the practice type list."
        font_size: '11sp'
        color: 0.7, 0.7, 0.7, 1
        size_hint_y: None
        height: self.texture_size[1]
        text_size: self.width, None
        padding: [10, 0]

    BoxLayout:
        orientation: 'vertical'
        size_hint_y: None
        height: self.minimum_height
        BoxLayout:
            size_hint_y: None
            height: '30dp'
            Label:
                text: 'Play All Songs'
                size_hint_x: 0.8
                text_size: self.size
                halign: 'left'
                valign: 'middle'
            Switch:
                id: play_all_songs_input
                size_hint_x: None
                width: '60dp'
        Label:
            text: "Includes in the playlist every song in the dance subfolder, ignoring 'Num Selections'."
            font_size: '11sp'
            color: 0.7, 0.7, 0.7, 1
            size_hint_y: None
            height: self.texture_size[1]
            text_size: self.width, None
            padding: [10, 0]

    BoxLayout:
        orientation: 'vertical'
        size_hint_y: None
        height: self.minimum_height
        BoxLayout:
            size_hint_y: None
            height: '30dp'
            Label:
                text: 'Auto Update/Restart'
                size_hint_x: 0.8
                text_size: self.size
                halign: 'left'
                valign: 'middle'
            Switch:
                id: auto_update_input
                size_hint_x: None
                width: '60dp'
        Label:
            text: "Automatically generates and starts a new playlist when the current one ends."
            font_size: '11sp'
            color: 0.7, 0.7, 0.7, 1
            size_hint_y: None
            height: self.texture_size[1]
            text_size: self.width, None
            padding: [10, 0]

    BoxLayout:
        orientation: 'vertical'
        size_hint_y: None
        height: self.minimum_height
        BoxLayout:
            size_hint_y: None
            height: '30dp'
            Label:
                text: 'Play Single Song'
                size_hint_x: 0.8
                text_size: self.size
                halign: 'left'
                valign: 'middle'
            Switch:
                id: play_single_song_input
                size_hint_x: None
                width: '60dp'
        Label:
            text: "Stops after each song. Overrides 'Play All Songs' and 'Auto Update'."
            font_size: '11sp'
            color: 0.7, 0.7, 0.7, 1
            size_hint_y: None
            height: self.texture_size[1]
            text_size: self.width, None
            padding: [10, 0]

    BoxLayout:
        orientation: 'vertical'
        size_hint_y: None
        height: self.minimum_height
        BoxLayout:
            size_hint_y: None
            height: '30dp'
            Label:
                text: 'Randomize Playlist'
                size_hint_x: 0.8
                text_size: self.size
                halign: 'left'
                valign: 'middle'
            Switch:
                id: randomize_playlist_input
                size_hint_x: None
                width: '60dp'
        Label:
            text: "Shuffles songs within each dance. If off, plays in a fixed order."
            font_size: '11sp'
            color: 0.7, 0.7, 0.7, 1
            size_hint_y: None
            height: self.texture_size[1]
            text_size: self.width, None
            padding: [10, 0]

    BoxLayout:
        orientation: 'vertical'
        size_hint_y: None
        height: self.minimum_height
        BoxLayout:
            size_hint_y: None
            height: '30dp'
            Label:
                text: 'Adjust Song Counts'
                size_hint_x: 0.8
                text_size: self.size
                halign: 'left'
                valign: 'middle'
            Switch:
                id: adjust_song_counts_input
                size_hint_x: None
                width: '60dp'
        Label:
            text: "Applies rules from built-in defaults or custom 'Dance Adjustments (JSON)' to change song counts."
            font_size: '11sp'
            color: 0.7, 0.7, 0.7, 1
            size_hint_y: None
            height: self.texture_size[1]
            text_size: self.width, None
            padding: [10, 0]

    BoxLayout:
        size_hint_y: None
        height: '170dp'
        BoxLayout:
            orientation: 'vertical'
            size_hint_x: 0.4
            spacing: 4
            Label:
                text: 'Dance Adjustments (JSON):'
                size_hint_y: None
                height: self.texture_size[1]
                text_size: self.width, None
                halign: 'left'
                valign: 'top'
            Label:
                text: 'Overrides "Num Selections" for specific dances.\\n\\n[b]String Rules:[/b] Simple formulas.\\n  "n-1": Play one less than Num Selections.\\n  "cap_at_1": Play a maximum of 1 song.\\n\\n[b]Mapping Rule:[/b] A dictionary to map the "Num Selections" value to a song count. Use a "default" key as a fallback.'
                markup: True
                font_size: '11sp'
                color: 0.7, 0.7, 0.7, 1
                text_size: self.width, None
                size_hint_y: None
                height: self.texture_size[1]
            Widget:
        ScrollView:
            size_hint_x: 0.6
            bar_width: 10
            TextInput:
                id: dance_adjustments_input
                size_hint_y: None
                height: self.minimum_height
                font_name: 'RobotoMono-Regular'

    BoxLayout:
        size_hint_y: None
        height: '100dp'
        BoxLayout:
            orientation: 'vertical'
            size_hint_x: 0.4
            spacing: 2
            Label:
                text: 'Dance Max Playtimes (JSON):'
                size_hint_y: None
                height: self.texture_size[1]
                text_size: self.width, None
                halign: 'left'
                valign: 'top'
            Label:
                text: 'Overrides default max song playtime for specific dances (in seconds).'
                font_size: '11sp'
                color: 0.7, 0.7, 0.7, 1
                size_hint_y: None
                height: self.texture_size[1]
                text_size: self.width, None
            Widget:
        ScrollView:
            size_hint_x: 0.6
            bar_width: 10
            TextInput:
                id: dance_max_playtimes_input
                size_hint_y: None
                height: self.minimum_height
                font_name: 'RobotoMono-Regular'

    BoxLayout:
        size_hint_y: None
        height: '120dp'
        BoxLayout:
            orientation: 'vertical'
            size_hint_x: 0.4
            spacing: 2
            Label:
                text: 'Dance Minutes (JSON):'
                size_hint_y: None
                height: self.texture_size[1]
                text_size: self.width, None
                halign: 'left'
                valign: 'top'
            Label:
                text: 'Plays a dance for a set number of minutes instead of a set number of songs, e.g. {"Waltz": 13}.\\n\\nOverrides "Num Selections" for the dances listed. The dance announcement counts toward the time. Songs are trimmed slightly and evenly so the block ends on time.'
                font_size: '11sp'
                color: 0.7, 0.7, 0.7, 1
                size_hint_y: None
                height: self.texture_size[1]
                text_size: self.width, None
            Widget:
        ScrollView:
            size_hint_x: 0.6
            bar_width: 10
            TextInput:
                id: dance_minutes_input
                size_hint_y: None
                height: self.minimum_height
                font_name: 'RobotoMono-Regular'

    BoxLayout:
        size_hint_y: None
        height: '120dp'
        BoxLayout:
            orientation: 'vertical'
            size_hint_x: 0.4
            spacing: 2
            Label:
                text: 'Dance Intros (JSON):'
                size_hint_y: None
                height: self.texture_size[1]
                text_size: self.width, None
                halign: 'left'
                valign: 'top'
            Label:
                text: 'What plays before each dance: "announce" for the spoken announcement, "none" for nothing, or a cue in cues/ such as "gap_10" for ten seconds of silence.\\n\\nA "default" key covers every dance not named, e.g. {"default": "gap_10", "PasoDoble": "announce"}. Without this the announcement is used.'
                font_size: '11sp'
                color: 0.7, 0.7, 0.7, 1
                size_hint_y: None
                height: self.texture_size[1]
                text_size: self.width, None
            Widget:
        ScrollView:
            size_hint_x: 0.6
            bar_width: 10
            TextInput:
                id: dance_intros_input
                size_hint_y: None
                height: self.minimum_height
                font_name: 'RobotoMono-Regular'

    BoxLayout:
        size_hint_y: None
        height: '220dp'
        BoxLayout:
            orientation: 'vertical'
            size_hint_x: 0.4
            spacing: 2
            Label:
                text: 'Segments (JSON):'
                size_hint_y: None
                height: self.texture_size[1]
                text_size: self.width, None
                halign: 'left'
                valign: 'top'
            Label:
                text: 'Competition rounds. Replaces the dances list when set.\\n\\n[b]Cue:[/b] an audio file from cues/, played in full.\\n  {"cue": "round_gap", "label": "2:00 break"}\\n\\n[b]Round:[/b] each dance played "count" times for "clip_seconds", cut off with no fade, separated by "gap_seconds".\\n  {"round": ["Waltz", "Tango"], "count": 1,\\n   "clip_seconds": 90, "gap_seconds": 20}\\n\\nRounds have no announcements unless "announce" is true.'
                markup: True
                font_size: '11sp'
                color: 0.7, 0.7, 0.7, 1
                size_hint_y: None
                height: self.texture_size[1]
                text_size: self.width, None
            Widget:
        ScrollView:
            size_hint_x: 0.6
            bar_width: 10
            TextInput:
                id: segments_input
                size_hint_y: None
                height: self.minimum_height
                font_name: 'RobotoMono-Regular'

<PracticeTypeEditorScreen>:
    practice_type_list_layout: practice_type_list_layout
    edit_form: edit_form

    BoxLayout:
        orientation: 'horizontal'

        # Left Panel: List of practice types
        BoxLayout:
            orientation: 'vertical'
            size_hint_x: 0.3

            Label:
                text: "Custom Practice Types"
                size_hint_y: None
                height: 40
                font_size: '18sp'

            ScrollView:
                GridLayout:
                    id: practice_type_list_layout
                    cols: 1
                    size_hint_y: None
                    height: self.minimum_height

        # Right Panel: Editing Form
        BoxLayout:
            orientation: 'vertical'
            size_hint_x: 0.7

            Label:
                text: "Practice Type Editor"
                size_hint_y: None
                height: 40
                font_size: '18sp'

            ScrollView:
                EditForm:
                    id: edit_form

            # Bottom Buttons
            BoxLayout:
                size_hint_y: None
                height: 50
                padding: 5
                spacing: 5

                Button:
                    text: 'New'
                    on_press: root.clear_form()
                Button:
                    text: 'Copy'
                    on_press: root.copy_practice_type()
                Button:
                    text: 'Reset'
                    on_press: root.reset_current_practice_type()
                Button:
                    text: 'Save'
                    on_press: root.save_current_practice_type()
                    background_color: (0.2, 0.8, 0.2, 1) # Green
                Button:
                    text: 'Delete'
                    on_press: root.delete_practice_type()
                    background_color: (0.8, 0.2, 0.2, 1) # Red
                Button:
                    text: 'Back to Player'
                    on_press: root.go_back_to_player()
""")
