# playlist_editor.py
"""
Provides a Kivy Screen for creating, editing, and deleting custom practice types
for the Dance Practice Music Player.
"""
import json
import os
from functools import partial
from kivy.uix.screenmanager import Screen
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
#from kivy.uix.scrollview import ScrollView
from kivy.uix.button import Button
from kivy.uix.label import Label
#from kivy.uix.textinput import TextInput
#from kivy.uix.checkbox import CheckBox
from kivy.uix.popup import Popup
#from kivy.uix.switch import Switch
from kivy.properties import ObjectProperty, StringProperty

class PlaylistEditorScreen(Screen):
    """
    The main screen widget for the playlist editor. It handles loading
    practice types from JSON, displaying them in a list, and providing
    a form to edit the selected practice type.
    """
    playlist_list_layout = ObjectProperty(None)
    edit_form = ObjectProperty(None)
    current_playlist_name = StringProperty(None, allownone=True)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.script_path = os.path.dirname(os.path.abspath(__file__))
        self.json_path = os.path.join(self.script_path, "custom_practice_types.json")
        self.practice_types = {}

    def on_enter(self, *args):
        """Called when the screen is entered. Loads and displays the playlists."""
        self.load_practice_types()
        self.display_playlist_list()
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
            self.display_playlist_list() # Refresh the list
            return True # Indicate success
        except (OSError, TypeError) as e:
            self.show_popup("Error", f"Failed to save playlists: {e}")
            return False # Indicate failure


    def display_playlist_list(self):
        """Populates the scroll view with buttons for each practice type."""
        self.playlist_list_layout.clear_widgets()
        sorted_names = sorted(self.practice_types.keys())
        for name in sorted_names:
            btn = Button(text=name, size_hint_y=None, height=40)
            btn.bind(on_press=partial(self.load_playlist_into_form, name))
            self.playlist_list_layout.add_widget(btn)

    def load_playlist_into_form(self, name, *args):
        """Loads the selected playlist's data into the form."""
        self.current_playlist_name = name
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

    def save_current_playlist(self):
        """Gathers data from the form and saves it to the practice_types dict."""
        name = self.edit_form.name_input.text.strip()
        if not name:
            self.show_popup("Error", "Playlist name cannot be empty.")
            return

        # If name changed, remove old entry (but not if it was a copy)
        if (self.current_playlist_name and
                self.current_playlist_name != name and
                self.current_playlist_name in self.practice_types):
            del self.practice_types[self.current_playlist_name]

        try:
            new_data = {
                "dances": [d.strip() for d in self.edit_form.dances_input.text.split(',')],
                "num_selections": int(self.edit_form.num_selections_input.text),
                "play_all_songs": self.edit_form.play_all_songs_input.active,
                "auto_update": self.edit_form.auto_update_input.active,
                "play_single_song": self.edit_form.play_single_song_input.active,
                "randomize_playlist": self.edit_form.randomize_playlist_input.active,
                "adjust_song_counts": self.edit_form.adjust_song_counts_input.active,
                "dance_adjustments": json.loads(self.edit_form.dance_adjustments_input.text or "{}"),
                "dance_max_playtimes": json.loads(self.edit_form.dance_max_playtimes_input.text or "{}"),
            }
            self.practice_types[name] = new_data
            self.current_playlist_name = name
            if self.save_practice_types():
                self.show_popup("Success", "Playlist saved successfully!")
        except (ValueError, json.JSONDecodeError) as e:
            self.show_popup("Error", f"Invalid data format: {e}\nCheck numeric fields and JSON formatting.")

    def delete_playlist(self):
        """Deletes the currently selected playlist."""
        if not self.current_playlist_name or self.current_playlist_name not in self.practice_types:
            self.show_popup("Error", "No playlist selected to delete.")
            return

        playlist_name = self.current_playlist_name
        del self.practice_types[self.current_playlist_name]
        
        if self.save_practice_types():
            self.show_popup("Success", f"Playlist '{playlist_name}' deleted successfully.")
            self.clear_form()

    def clear_form(self, *args):
        """Resets the form to a template for a new playlist."""
        self.current_playlist_name = None

        default_60min_data = {
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
                "VWSlow": "cap_at_1",
                "JSlow": "cap_at_1",
                "VienneseWaltz": "n-1",
                "Jive": "n-1",
                "WCS": "cap_at_2"
            },
            "dance_max_playtimes": {
                "VienneseWaltz": 150
            }
        }

        self.edit_form.name_input.text = ""
        self.edit_form.dances_input.text = ", ".join(default_60min_data["dances"])
        self.edit_form.num_selections_input.text = str(default_60min_data["num_selections"])
        self.edit_form.play_all_songs_input.active = default_60min_data["play_all_songs"]
        self.edit_form.auto_update_input.active = default_60min_data["auto_update"]
        self.edit_form.play_single_song_input.active = default_60min_data["play_single_song"]
        self.edit_form.randomize_playlist_input.active = default_60min_data["randomize_playlist"]
        self.edit_form.adjust_song_counts_input.active = default_60min_data["adjust_song_counts"]
        self.edit_form.dance_adjustments_input.text = json.dumps(
            default_60min_data["dance_adjustments"], indent=4
        )
        self.edit_form.dance_max_playtimes_input.text = json.dumps(
            default_60min_data["dance_max_playtimes"], indent=4
        )

    def copy_playlist(self, *args):
        """Copies the currently loaded playlist data to create a new one."""
        if not self.current_playlist_name:
            self.show_popup("Info", "Please select a playlist to copy first.")
            return

        self.edit_form.name_input.text = ""
        self.current_playlist_name = None
        self.show_popup("Copied", "Playlist data copied.\nEnter a new name, edit as needed, and click Save.")

    def reset_current_playlist(self, *args):
        """Resets the form fields to the saved state of the current playlist."""
        if not self.current_playlist_name:
            self.show_popup("Info", "No playlist selected to reset.\nClick 'New' to load a template.")
            return
        
        self.load_playlist_into_form(self.current_playlist_name)
        self.show_popup("Reset", f"'{self.current_playlist_name}' has been reset to its saved state.")

    def go_back_to_player(self):
        """Switches back to the main music player screen and forces a reload."""
        self.manager.reload_custom_types()
        self.manager.current = 'player'

    def show_popup(self, title, message):
        """Utility function to show a popup with an OK button."""
        content_layout = BoxLayout(orientation='vertical', spacing=10, padding=10)
        message_label = Label(text=message)
        ok_button = Button(text="OK", size_hint_y=None, height='44dp')
        content_layout.add_widget(message_label)
        content_layout.add_widget(ok_button)
        popup = Popup(title=title,
                      content=content_layout,
                      size_hint=(None, None), size=('400dp', '200dp'))
        ok_button.bind(on_press=popup.dismiss)
        popup.open()


class EditForm(GridLayout):
    """The layout for the playlist editing form fields."""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # All child widgets are defined in the kv string below


# Use a Kivy language string to define the complex layout
from kivy.lang import Builder
Builder.load_string("""
#:kivy 1.11.1

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
            text: 'Playlist Name:'
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
            padding_x: 10

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
            padding_x: 10

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
            padding_x: 10

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
            padding_x: 10

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
            text: "Applies rules from 'Dance Adjustments (JSON)' to change song counts."
            font_size: '11sp'
            color: 0.7, 0.7, 0.7, 1
            size_hint_y: None
            height: self.texture_size[1]
            text_size: self.width, None
            padding_x: 10

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
            Widget: # Spacer to push labels to the top
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
            Widget: # Spacer to push labels to the top
        ScrollView:
            size_hint_x: 0.6
            bar_width: 10
            TextInput:
                id: dance_max_playtimes_input
                size_hint_y: None
                height: self.minimum_height
                font_name: 'RobotoMono-Regular'

<PlaylistEditorScreen>:
    playlist_list_layout: playlist_list_layout
    edit_form: edit_form

    BoxLayout:
        orientation: 'horizontal'

        # Left Panel: List of playlists
        BoxLayout:
            orientation: 'vertical'
            size_hint_x: 0.3

            Label:
                text: "Custom Playlists"
                size_hint_y: None
                height: 40
                font_size: '18sp'

            ScrollView:
                GridLayout:
                    id: playlist_list_layout
                    cols: 1
                    size_hint_y: None
                    height: self.minimum_height

        # Right Panel: Editing Form
        BoxLayout:
            orientation: 'vertical'
            size_hint_x: 0.7

            Label:
                text: "Playlist Editor"
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
                    on_press: root.copy_playlist()
                Button:
                    text: 'Reset'
                    on_press: root.reset_current_playlist()
                Button:
                    text: 'Save'
                    on_press: root.save_current_playlist()
                    background_color: (0.2, 0.8, 0.2, 1) # Green
                Button:
                    text: 'Delete'
                    on_press: root.delete_playlist()
                    background_color: (0.8, 0.2, 0.2, 1) # Red
                Button:
                    text: 'Back to Player'
                    on_press: root.go_back_to_player()
""")
