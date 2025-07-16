# practice_type_editor.py
"""
Provides a Kivy Screen for creating, editing, and deleting custom practice types
for the Dance Practice Music Player.
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


class PracticeTypeEditorScreen(Screen):
    """
    The main screen widget for the practice type editor. It handles loading
    practice types from JSON, displaying them in a list, and providing
    a form to edit the selected practice type.
    """
    practice_type_list_layout = ObjectProperty(None)
    edit_form = ObjectProperty(None)
    current_practice_type_name = StringProperty(None, allownone=True)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.script_path = os.path.dirname(os.path.abspath(__file__))
        self.json_path = os.path.join(self.script_path, "custom_practice_types.json")
        self.practice_types = {}
        self._current_button = None

    def on_enter(self, *args):
        """Called when the screen is entered. Loads and displays the practice types."""
        self.load_practice_types()
        self.display_practice_type_list()
        self.clear_form()

    def load_practice_types(self):
        """Loads the custom practice types from the JSON file."""
        try:
            with open(self.json_path, 'r', encoding='utf-8') as f:
                all_data = json.load(f)
                # Filter out comment keys
                self.practice_types = {
                    k: v for k, v in all_data.items() if not k.startswith("__COMMENT__")
                }
        except (FileNotFoundError, json.JSONDecodeError):
            self.practice_types = {}
            # If the file doesn't exist or is empty, create a placeholder
            if not os.path.exists(self.json_path):
                with open(self.json_path, 'w', encoding='utf-8') as f:
                    json.dump({}, f)

    def save_practice_types(self):
        """
        Saves the current practice types back to the JSON file.
        Returns True on success, False on failure.
        """
        try:
            # Read original file to preserve comments
            with open(self.json_path, 'r', encoding='utf-8') as f:
                all_data = json.load(f)

            # Update only the non-comment keys
            for key in self.practice_types:
                all_data[key] = self.practice_types[key]

            # Find keys to delete (present in original file but not in our active dict)
            keys_to_delete = [k for k in all_data if not k.startswith("__COMMENT__")
                              and k not in self.practice_types]
            for key in keys_to_delete:
                del all_data[key]

            with open(self.json_path, 'w', encoding='utf-8') as f:
                json.dump(all_data, f, indent=4)
            self.display_practice_type_list() # Refresh the list
            return True # Indicate success
        except (OSError, TypeError) as e:
            self.show_popup("Error", f"Failed to save Practice Types: {e}")
            return False # Indicate failure

    def display_practice_type_list(self):
        """Populates the scroll view with buttons for each practice type."""
        self.practice_type_list_layout.clear_widgets()
        # When clearing the list, also reset the tracked button
        self._current_button = None

        sorted_names = sorted(self.practice_types.keys())
        for name in sorted_names:
            btn = Button(text=name, size_hint_y=None, height=40)
            # Pass the button 'btn' as an argument to the callback
            # Pass the button 'btn' as an argument to the callback
            btn.bind(on_press=partial(self.load_practice_type_into_form, btn, name))  # pylint: disable=no-member
            self.practice_type_list_layout.add_widget(btn)

    def load_practice_type_into_form(self, button_instance, name, *_args):
        """Loads the selected practice type's data into the form and highlights the button."""
        # Reset the color of the previously selected button, if it exists
        if self._current_button:
            self._current_button.background_color = (1, 1, 1, 1) # Default color

        # Set the color of the newly clicked button
        button_instance.background_color = (0, 1, 1, 1) # Highlight color (cyan)
        self._current_button = button_instance

        self.current_practice_type_name = name
        data = self.practice_types[name]

        # Populate form fields
        self.edit_form.name_input.text = name
        self.edit_form.dances_input.text = ", ".join(data.get("dances", []))
        self.edit_form.num_selections_input.text = str(data.get("num_selections", 1))
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

    def save_current_practice_type(self):
        """Gathers data from the form and saves it to the practice_types dict."""
        name = self.edit_form.name_input.text.strip()
        if not name:
            self.show_popup("Error", "Practice Type name cannot be empty.")
            return

        old_name = self.current_practice_type_name

        # If name changed, remove old entry
        if old_name and old_name != name and old_name in self.practice_types:
            del self.practice_types[old_name]

        try:
            new_data = {
                "dances": [d.strip() for d in self.edit_form.dances_input.text.split(',')],
                "num_selections": int(self.edit_form.num_selections_input.text),
                "play_all_songs": self.edit_form.play_all_songs_input.active,
                "auto_update": self.edit_form.auto_update_input.active,
                "play_single_song": self.edit_form.play_single_song_input.active,
                "randomize_playlist": self.edit_form.randomize_playlist_input.active,
                "adjust_song_counts": self.edit_form.adjust_song_counts_input.active,
                "dance_adjustments": json.loads(
                    self.edit_form.dance_adjustments_input.text or "{}"),
                "dance_max_playtimes": json.loads(
                    self.edit_form.dance_max_playtimes_input.text or "{}"),
            }
            self.practice_types[name] = new_data
            self.current_practice_type_name = name

            # If a rename of the active type occurred, update the player's state.
            # The binding in MusicPlayer will handle updating the config file.
            if old_name and old_name != name:
                app = App.get_running_app()
                player_widget = app.manager.get_screen('player').children[0]

                if player_widget.practice_type == old_name:
                    # Update the live widget property
                    player_widget.practice_type = name

            if self.save_practice_types():
                self.show_popup("Success", "Practice Type saved successfully!")
        except (ValueError) as e:
            self.show_popup(
                "Error", f"Invalid data format: {e}\nCheck numeric fields and JSON formatting.")

    def delete_practice_type(self):
        """Deletes the currently selected practice type."""
        name = self.current_practice_type_name
        if not name or name not in self.practice_types:
            self.show_popup("Error", "No Practice Type selected to delete.")
            return

        practice_type_name = self.current_practice_type_name
        del self.practice_types[self.current_practice_type_name]

        if self.save_practice_types():
            self.show_popup(
                "Success", f"Practice Type '{practice_type_name}' deleted successfully.")
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
            "dance_max_playtimes": {"VienneseWaltz": 150}
        }

        self.edit_form.name_input.text = ""
        self.edit_form.dances_input.text = ", ".join(default_data["dances"])
        self.edit_form.num_selections_input.text = str(default_data["num_selections"])
        self.edit_form.play_all_songs_input.active = default_data["play_all_songs"]
        self.edit_form.auto_update_input.active = default_data["auto_update"]
        self.edit_form.play_single_song_input.active = default_data["play_single_song"]
        self.edit_form.randomize_playlist_input.active = default_data["randomize_playlist"]
        self.edit_form.adjust_song_counts_input.active = default_data["adjust_song_counts"]
        self.edit_form.dance_adjustments_input.text = json.dumps(
            default_data["dance_adjustments"], indent=4)
        self.edit_form.dance_max_playtimes_input.text = json.dumps(
            default_data["dance_max_playtimes"], indent=4)

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
        Updates the player's active practice type to the one currently selected
        in the editor, then switches back to the player screen and forces a reload.
        """
        # If a practice type is selected in the editor form, update the player
        if self.current_practice_type_name:
            app = App.get_running_app()
            player_widget = app.manager.get_screen('player').children[0]
            player_widget.practice_type = self.current_practice_type_name

        # Now, the reload will use the newly set practice type
        self.manager.reload_custom_types()
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
    play_all_songs_input: play_all_songs_input
    auto_update_input: auto_update_input
    play_single_song_input: play_single_song_input
    randomize_playlist_input: randomize_playlist_input
    adjust_song_counts_input: adjust_song_counts_input
    dance_adjustments_input: dance_adjustments_input
    dance_max_playtimes_input: dance_max_playtimes_input

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
