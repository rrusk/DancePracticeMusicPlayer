# pylint: disable=too-many-lines
"""Dance Practice Music Player

A Kivy-based application for managing and playing playlists for ballroom and line dance practice.
Supports configurable practice types, playlist management, and platform-specific audio handling.
"""
import os
import platform
import pathlib
import random
import json
import sys
import typing
import threading
from functools import partial

# IMPORTANT: Kivy Config.set for graphics must be called BEFORE importing any other Kivy modules.
from kivy.config import Config

# Set Kivy configuration for input and window size
Config.set("input", "mouse", "mouse,multitouch_on_demand")
Config.set('graphics', 'width', '1024')
Config.set('graphics', 'height', '768')

# pylint: disable=wrong-import-position
from kivy.app import App
# pylint: disable=no-name-in-module, no-member
from kivy.properties import (
    NumericProperty,
    StringProperty,
    ObjectProperty,
    ListProperty,
    DictProperty,
    BooleanProperty,
)
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.core.audio import SoundLoader
from kivy.clock import Clock
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.slider import Slider
from kivy.uix.settings import SettingsWithSpinner
from kivy.config import ConfigParser
from tinytag import TinyTag, TinyTagException

# --- Imports for ScreenManager and the editor screen ---
from kivy.uix.screenmanager import ScreenManager, Screen
from playlist_editor import PlaylistEditorScreen # Import the new screen


# Conditional import for Windows-specific functionality
# This ensures ctypes is only imported if on Windows,
# and is then available throughout the module's global scope.
if sys.platform == "win32":
    import ctypes
else:
    # Ensure ctypes is defined for all platforms to suppress PyLint warnings
    ctypes = None  # pylint: disable=invalid-name


# Constants for better readability
class PlayerConstants:
    """Holds constant values for UI colors, labels, and configuration used
    throughout the music player application."""
    INIT_POS_DUR = "0:00 / 0:00"
    INIT_SONG_TITLE = "Click on the Play icon or Select Song Title Above"
    INIT_MUSIC_SELECTION = (
        "A valid dance music directory is needed. Click here or use Music Settings button"
    )
    SONG_BTN_BACKGROUND_COLOR = (0.5, 0.5, 0.5, 1)
    ACTIVE_SONG_BUTTON_COLOR = (0, 1, 1, 1)  # Cyan for active song
    DEFAULT_BUTTON_TEXT_COLOR = (1, 1, 1, 1)
    ERROR_POPUP_TEXT_COLOR = (1, 1, 1, 1)
    ERROR_POPUP_BUTTON_COLOR = (0.7, 0.7, 0.7, 1)
    PROGRESS_BAR_COLOR = (0.3, 0.8, 0.3, 1)
    VOLUME_LABEL_COLOR = (0.3, 0.8, 0.3, 1)
    SONG_TITLE_COLOR = (0, 1, 0, 1)  # Green text

    FADE_TIME = 10  # 10s fade out

    # Icon filenames as constants
    ICON_PLAY = "play.png"
    ICON_PAUSE = "pause.png"
    ICON_STOP = "stop.png"
    ICON_REPLAY = "replay.png"

# --- Root ScreenManager Widget ---
class RootManager(ScreenManager):
    """The root ScreenManager that holds the player and editor screens."""
    def reload_custom_types(self):
        """
        Finds the music player screen and tells it to reload its custom
        playlist definitions.
        """
        player_screen = self.get_screen('player')
        # The MusicPlayer widget is the first child of the Screen
        player_widget = player_screen.children[0]
        player_widget.merge_custom_practice_types()
        player_widget.update_settings_options()
        # Also update the playlist button text in case the practice type was reset
        player_widget.update_playlist_button_text(None, player_widget.practice_type)


class MusicPlayer(BoxLayout):
    """Main widget for the dance practice music player.

    This class encapsulates the entire user interface and the core logic for music playback,
    playlist generation, and settings management. It handles user interactions with controls
    like play, pause, volume, and playlist navigation.

    Attributes:
        sound (ObjectProperty): The currently loaded Kivy Sound object.
        music_file (StringProperty): The file path of the currently playing song.
        volume (NumericProperty): The master volume for playback, from 0.0 to 1.0.
        music_dir (StringProperty): The root directory where dance music subfolders are located.
        progress_max (NumericProperty): The total duration of the current song in seconds.
        progress_value (NumericProperty): The current playback position in seconds.
        progress_text (StringProperty): A formatted string showing "current_time / total_time".
        song_title (StringProperty): The display title of the currently playing song.
        play_single_song (BooleanProperty): If True, the player stops after the current song.
        play_all_songs (BooleanProperty): If True, all songs in a dance subfolder are played.
        song_max_playtime (NumericProperty): Default maximum time in seconds a song will play.
        auto_update_restart_playlist (BooleanProperty): If True, a new playlist is generated
            when the current one ends.
        randomize_playlist (BooleanProperty): If True, songs within each dance are shuffled.
        adjust_song_counts_for_playlist (BooleanProperty): If True, applies rules to adjust
            the number of songs per dance.
        current_dance_adjustments (DictProperty): Rules for adjusting song counts for the
            active practice type.
        current_dance_max_playtimes (DictProperty): Per-dance overrides for maximum playtime.
        playlist (ListProperty): The current list of songs to be played.
        playlist_idx (NumericProperty): The index of the current song in the playlist.
        dances (ListProperty): The ordered list of dances for the current practice type.
        practice_type (StringProperty): The name of the selected practice type (e.g., "60min").
        num_selections (NumericProperty): The number of songs to select for each dance.
        playlist_button (ObjectProperty): A reference to the 'New Playlist' button widget.
    """
    # Kivy Properties
    sound = ObjectProperty(None, allownone=True)
    music_file = StringProperty(None)
    volume = NumericProperty(0.7)
    music_dir = StringProperty("")
    progress_max = NumericProperty(100)
    progress_value = NumericProperty(0)
    progress_text = StringProperty(PlayerConstants.INIT_POS_DUR)
    song_title = StringProperty(PlayerConstants.INIT_SONG_TITLE)
    play_single_song = BooleanProperty(False)
    play_all_songs = BooleanProperty(False)
    song_max_playtime = NumericProperty(210)
    auto_update_restart_playlist = BooleanProperty(False)
    randomize_playlist = BooleanProperty(True)
    adjust_song_counts_for_playlist = BooleanProperty(False)
    current_dance_adjustments = DictProperty({})
    current_dance_max_playtimes = DictProperty({})

    practice_dances = DictProperty(
        {
            "default": [
                "Waltz",
                "Tango",
                "VWSlow",
                "VienneseWaltz",
                "Foxtrot",
                "QuickStep",
                "WCS",
                "Samba",
                "ChaCha",
                "Rumba",
                "PasoDoble",
                "JSlow",
                "Jive",
            ],
            "newcomer": [
                "Waltz",
                "JSlow",
                "Jive",
                "Rumba",
                "Foxtrot",
                "ChaCha",
                "Tango",
                "Samba",
                "QuickStep",
                "VWSlow",
                "VienneseWaltz",
                "WCS",
            ],
        }
    )

    playlist = ListProperty([])
    playlist_idx = NumericProperty(0)
    dances = ListProperty([])
    practice_type = StringProperty("60min")
    num_selections = NumericProperty(2)

    settings_json = [
        {
            "type": "numeric",
            "title": "Volume",
            "desc": "Set the music volume; range is 0.0 to 1.0.",
            "section": "user",
            "key": "volume",
        },
        {
            "type": "path",
            "title": "Music Directory",
            "desc": (
                "Set the music directory. The directory must have sub-folders containing "
                "the music for each dance included in the playlist. For example, musical "
                "selections for the Waltz will be randomly selected from the Waltz sub-folder."
            ),
            "section": "user",
            "key": "music_dir",
        },
        {
            "type": "numeric",
            "title": "Max Playtime (Default)",
            "desc": (
                "Set the default maximum playtime for a song in seconds. This can be "
                "overridden for specific dances in custom practice types. The music fades "
                "out and stops after the maximum playtime. This setting is ignored for "
                "custom practice types with play_single_song set to true."
            ),
            "section": "user",
            "key": "song_max_playtime",
        },
        {
            "type": "options",
            "title": "Practice Type",
            "desc": (
                "Choose the practice type/length. Un-prefixed times are dances played in "
                "competition order. The prefix NC (for newcomer) modifies the order of dances. "
                "Custom practice types can be added in the custom_practice_types.json file, "
                "with dances played in the order listed.  For custom practice types, the "
                "practice length can't be pre-determined very accurately so it is best to "
                "set auto_update to true and just stop the music player at the end of the practice."
            ),
            "section": "user",
            "key": "practice_type",
            "options": [
                "60min",
                "NC 60min",
            ],
        },
    ]

    script_path = os.path.dirname(os.path.abspath(__file__))

    _current_button = None  # Internal variable for tracking active song button
    _song_buttons = []  # Internal list to store song buttons
    _playing_position = 0
    _total_time = 0
    _schedule_interval = 0.1
    _update_progress_event = None  # To hold the scheduled Clock event

    # New ObjectProperty for the playlist button
    playlist_button = ObjectProperty(None)
    _playlist_generation_in_progress = BooleanProperty(False)
    _is_first_load = BooleanProperty(True)


    def __init__(self, **kwargs):
        """Initializes the MusicPlayer widget.

        This constructor sets up the widget's orientation, loads custom practice types from JSON,
        builds the user interface, binds properties to their respective handlers, and triggers
        an initial playlist update if a music directory is already configured.

        Args:
            **kwargs: Keyword arguments passed to the parent `BoxLayout` constructor.
        """
        super().__init__(**kwargs)
        self.orientation = "vertical"
        # Initialize all UI-related attributes to None
        self.scrollview = None
        self.button_grid = None
        self.volume_slider = None
        self.volume_label = None
        self.song_title_label = None
        self.progress_bar = None
        self.progress_label = None
        self.play_pause_button = None

        # Initialize other internal attributes
        self._current_button = None
        self._song_buttons = []
        self._playing_position = 0
        self._total_time = 0
        self._schedule_interval = 0.1
        self._update_progress_event = None

        self.custom_practice_mapping = {}
        self.merge_custom_practice_types()

        self._build_ui()
        self._bind_properties()

        if self.music_dir:
            self.update_playlist()
        else:
            self._display_playlist_buttons()

    def load_custom_practice_types(self) -> dict:
        """Load custom practice types from a JSON file in the application directory.

        This method looks for 'custom_practice_types.json' in the script's directory.
        It parses the JSON, filtering out any keys that start with "__COMMENT__",
        which allows for comments within the JSON file.

        Returns:
            A dictionary of custom practice types loaded from the JSON file. Returns an
            empty dictionary if the file is not found or if a parsing error occurs.
        """
        custom_types = {}
        json_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "custom_practice_types.json")
        if os.path.isfile(json_path):
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    raw_data = json.load(f)
                    # Filter out any keys that start with "__COMMENT__"
                    custom_types = {
                        k: v for k, v in raw_data.items()
                        if not k.startswith("__COMMENT__")
                    }
            except (OSError, json.JSONDecodeError) as e:
                print(f"Failed to load custom practice types: {e}")
        return custom_types

    def merge_custom_practice_types(self) -> None:
        """Merge custom practice types into settings and internal dance mappings.

        This method loads custom types from JSON and dynamically updates the 'Practice Type'
        dropdown in the settings panel. It also populates the `practice_dances` and
        `custom_practice_mapping` dictionaries, which are used to configure player behavior
        when a custom practice type is selected.
        """
        custom_types = self.load_custom_practice_types()
        if not custom_types:
            return

        # Use named expression for practice_type_setting
        if (practice_type_setting := next(
            (item for item in self.settings_json if item.get("key") == "practice_type"), None
        )):
            for custom_name in custom_types:
                if custom_name not in practice_type_setting["options"]:
                    practice_type_setting["options"].append(custom_name)

        # Add to practice_dances and mapping
        if not hasattr(self, "custom_practice_mapping"):
            self.custom_practice_mapping = {}
        for name, data in custom_types.items():
            self.practice_dances[name] = data.get("dances", [])
            self.custom_practice_mapping[name] = (
                name,
                data.get("num_selections", 2),
                data.get("play_all_songs", False),
                data.get("auto_update", False),
                data.get("play_single_song", False),
                data.get("randomize_playlist", True),
                data.get("adjust_song_counts", False),
                data.get("dance_adjustments", {}),
                data.get("dance_max_playtimes", {}),
            )
    
    def update_settings_options(self):
        """
        Dynamically updates the options in the settings JSON. Call this
        after practice types have been modified externally.
        """
        custom_types = self.load_custom_practice_types()
        if (practice_type_setting := next(
            (item for item in self.settings_json if item.get("key") == "practice_type"), None
        )):
            # Reset options to default before adding custom ones
            base_options = ["60min", "NC 60min"]
            custom_options = list(custom_types.keys())
            practice_type_setting["options"] = base_options + custom_options

            # If current practice type is no longer valid, reset it
            if self.practice_type not in practice_type_setting["options"]:
                self.practice_type = "60min"

    def _build_ui(self) -> None:
        """Constructs the main user interface by creating and arranging all widgets.

        This method orchestrates the creation of the two main UI sections: the scrollable
        playlist area and the bottom panel containing playback and volume controls.
        """
        self._create_playlist_widgets()
        self._create_control_widgets()

    def _create_playlist_widgets(self) -> None:
        """Creates the scrollable view for the playlist buttons.

        This sets up a `ScrollView` containing a `GridLayout`. The grid's height is dynamically
        managed to ensure its content is always aligned to the top, even if there are not enough
        songs to fill the entire view. This is achieved by binding the grid's height to its
        `minimum_height` and the scroll view's height.
        """
        self.scrollview = ScrollView(size_hint=(1, 1))
        self.button_grid = GridLayout(
            cols=1,
            size_hint_y=None, # Important: Let height be determined by children
            row_force_default=False, # Ensure rows respect their height property
            row_default_height=40,   # Explicitly set height for each row, matching button heights
        )
        # This bind ensures button_grid.height grows to fit its content
        self.button_grid.bind(minimum_height=self.button_grid.setter("height"))

        # Binding for top allignment
        def ensure_grid_fills_scrollview_height(_instance, _value):
            # This function ensures the button_grid's height is at least the scrollview's height.
            # If the content (minimum_height) is less than the scrollview's height,
            # we force the button_grid's height to match the scrollview's height.
            # This makes the Label(size_hint_y=1), at the bottom of _displaylist_playlist_buttons(),
            # expand and push content to the top.
            if self.button_grid.minimum_height < self.scrollview.height:
                self.button_grid.height = self.scrollview.height
            else:
                # If content is larger, allow it to be its minimum_height
                # (which the setter("height") already handles)
                self.button_grid.height = self.button_grid.minimum_height

        # Bind this function to changes in both button_grid's minimum_height (content changes)
        # and scrollview's height (window resize or layout changes).
        self.button_grid.bind(minimum_height=ensure_grid_fills_scrollview_height)
        self.scrollview.bind(height=ensure_grid_fills_scrollview_height)

        self.scrollview.add_widget(self.button_grid)
        self.add_widget(self.scrollview)

    def _create_control_widgets(self) -> None:
        """Creates the bottom panel with volume, progress, and control buttons.

        This method assembles the fixed-size bottom portion of the UI. It consists of a
        horizontal layout containing two main parts: the vertical volume slider on the left,
        and a vertical layout on the right that holds the song title, progress bar,
        and playback control buttons (Play/Pause, Stop, etc.).
        """
        volume_and_controls = BoxLayout(
            orientation="horizontal", height="125dp", size_hint_y=None
        )

        # Volume Slider
        volume_layout = BoxLayout(orientation="horizontal", size_hint_x=0.20, padding=(10, 0))
        self.volume_slider = Slider(
            min=0.0,
            max=1.0,
            value=self.volume,
            orientation="vertical",
            size_hint_y=1,
            height=125,
            value_track=True,
            value_track_color=PlayerConstants.PROGRESS_BAR_COLOR,
        )
        self.volume_label = Label(
            text=f"Vol: {int(100 * self.volume)}%",
            size_hint_x=1,
            width=30,
            color=PlayerConstants.VOLUME_LABEL_COLOR,
        )
        volume_layout.add_widget(self.volume_label)
        volume_layout.add_widget(self.volume_slider)

        # Controls (includes progress bar and control buttons)
        controls = BoxLayout(orientation="vertical", height="100dp", padding=2)

        # Progress bar with song title and position in song
        self.song_title_label = Label(
            text=self.song_title, color=PlayerConstants.SONG_TITLE_COLOR
        )
        controls.add_widget(self.song_title_label)
        self.progress_bar = Slider(
            min=0,
            max=self.progress_max,
            value=self.progress_value,
            step=1,
            cursor_size=(0, 0),
            value_track=True,
            value_track_width=4,
            size_hint_x=1,
            value_track_color=PlayerConstants.PROGRESS_BAR_COLOR,
        )
        self.progress_label = Label(
            text=self.progress_text, color=PlayerConstants.SONG_TITLE_COLOR
        )
        controls.add_widget(self.progress_bar)
        controls.add_widget(self.progress_label)

        # Control buttons: play, pause, stop, restart, new playlist, settings
        control_buttons = BoxLayout(size_hint_y=None, height=50, spacing=3)

        self.play_pause_button = Button(
            background_normal=self._get_icon_path(PlayerConstants.ICON_PLAY),
            size_hint=(None, None),
            size=(50, 50),
        )
        stop_button = Button(
            background_normal=self._get_icon_path(PlayerConstants.ICON_STOP),
            size_hint=(None, None),
            size=(50, 50),
        )
        restart_button = Button(
            background_normal=self._get_icon_path(PlayerConstants.ICON_REPLAY),
            size_hint=(None, None),
            size=(50, 50),
        )
        # Assign the playlist_button to the ObjectProperty here
        self.playlist_button = Button(
            text=f"New Playlist ({self.practice_type})", # Initial text
            background_color=(0.2, 0.6, 0.8, 1),
            color=PlayerConstants.DEFAULT_BUTTON_TEXT_COLOR,
        )
        settings_button = Button(
            text="Music Settings",
            background_color=(0.2, 0.6, 0.8, 1),
            color=PlayerConstants.DEFAULT_BUTTON_TEXT_COLOR,
        )
        # Add the "Edit Playlists" button
        edit_playlists_button = Button(
            text="Edit Playlists",
            background_color=(0.2, 0.6, 0.8, 1),
            color=PlayerConstants.DEFAULT_BUTTON_TEXT_COLOR,
        )
        # --- FIX: Bind the button to the new method ---
        edit_playlists_button.bind(on_press=self.switch_to_editor)


        self.play_pause_button.bind(on_press=self.toggle_play_pause)
        stop_button.bind(on_press=self.stop_sound)
        restart_button.bind(on_press=self.restart_sound)
        self.playlist_button.bind(on_press=self.update_playlist)
        settings_button.bind(on_press=lambda instance: App.get_running_app().open_settings())

        control_buttons.add_widget(self.play_pause_button)
        control_buttons.add_widget(stop_button)
        control_buttons.add_widget(restart_button)
        control_buttons.add_widget(self.playlist_button)
        control_buttons.add_widget(settings_button)
        # Add the new button to the layout
        control_buttons.add_widget(edit_playlists_button)
        controls.add_widget(control_buttons)

        volume_and_controls.add_widget(volume_layout)
        volume_and_controls.add_widget(controls)
        self.add_widget(volume_and_controls)

    def _bind_properties(self) -> None:
        """Binds Kivy properties to their corresponding UI update methods.

        This method sets up listeners that automatically update the UI when a Kivy
        property changes. For example, changing `self.volume` will trigger `update_volume_label`,
        and changing `self.song_title` will update the text of the title label.
        """
        self.volume_slider.bind(value=self.set_volume)
        self.bind(volume=self.update_volume_label)
        self.bind(song_title=self.song_title_label.setter("text"))
        self.bind(progress_max=self.progress_bar.setter("max"))
        self.bind(progress_value=self.progress_bar.setter("value"))
        self.progress_bar.bind(on_touch_up=self.on_slider_move)
        self.bind(progress_text=self.progress_label.setter("text"))
        self.bind(practice_type=self.update_playlist_button_text) # Bind practice_type here
        self.bind(_playlist_generation_in_progress=self.on_playlist_generation_status_change)
        
    # --- FIX: Add a new method to handle switching to the editor screen ---
    def switch_to_editor(self, _instance: typing.Any = None):
        """Switches the screen to the playlist editor."""
        App.get_running_app().manager.current = 'editor'


    def _get_icon_path(self, icon_name: str) -> str:
        """Constructs the full, absolute path to an icon file.

        Args:
            icon_name: The filename of the icon (e.g., "play.png").

        Returns:
            The absolute path to the icon, located in the 'icons' subdirectory
            of the script's path.
        """
        return os.path.join(self.script_path, "icons", icon_name)

    def get_dances(self, list_name: str) -> list:
        """Retrieves a list of dances for a given practice type name.

        If the `list_name` is not found in the `practice_dances` dictionary, it falls
        back to the "default" list.

        Args:
            list_name: The key for the desired dance list (e.g., "newcomer", "60min").

        Returns:
            A list of dance names.
        """
        return self.practice_dances.get(list_name, self.practice_dances["default"])

    def toggle_play_pause(self, _instance: typing.Any = None) -> None:
        """Toggles the current song between playing and paused states.

        If a song is currently playing, it will be paused. If it's paused or stopped,
        playback will start (or resume).

        Args:
            _instance: The widget instance that triggered the event (unused).
        """
        if self._playlist_generation_in_progress:
            return # Don't allow play/pause while playlist is generating
        if self.sound and self.sound.state == "play":
            self.pause_sound()
        else:
            self.play_sound()

    def play_sound(self) -> None:
        """Handles the logic for playing a song.

        This method loads the song specified by the current `playlist_idx`, updates the UI
        with the song's title and duration, highlights the song in the playlist, schedules
        the progress bar update, and starts playback. It includes error handling for
        missing files or loading failures.
        """
        if not self.playlist or self.playlist_idx >= len(self.playlist):
            self.restart_playlist()
            return

        current_song = self.playlist[self.playlist_idx]
        current_song_path = current_song['path']
        self.music_file = current_song_path # Keep for reference if needed

        if not os.path.exists(current_song_path):
            self.show_error_popup(f"Song file not found: {current_song_path}")
            self._advance_playlist()
            return

        if self.sound is None:
            self.sound = SoundLoader.load(current_song_path)

        if not self.sound:
            self.show_error_popup(f"Could not load song: {current_song_path}")
            self._advance_playlist()
            return

        if self.sound.state == "play":
            self._playing_position = self.sound.get_pos()
        if self.sound.state != "stop":
            self.sound.stop()

        self.sound.volume = self.volume
        self._total_time = self._get_song_duration_str(current_song['duration'])
        self.song_title = self._get_song_label(current_song)[:120]  # Limit to 120 characters

        self._update_song_button_highlight()
        self._scroll_to_current_song()

        self._unschedule_progress_update()
        self._schedule_progress_update(current_song['duration'])

        self._apply_platform_specific_play()

        # Update the Play/Pause button icon to Pause
        self.play_pause_button.background_normal = self._get_icon_path(PlayerConstants.ICON_PAUSE)

    def pause_sound(self) -> None:
        """Pauses the currently playing sound.

        It stores the current playback position and stops the sound. The play/pause button
        icon is updated to show 'Play', indicating that playback can be resumed.
        """
        if self.sound and self.sound.state == "play":
            self._playing_position = self.sound.get_pos()
            self.sound.stop()
            # Update the Play/Pause button icon to Play
            self.play_pause_button.background_normal = self._get_icon_path(
                PlayerConstants.ICON_PLAY)

    def stop_sound(self, _instance: typing.Any = None) -> None:
        """Stops playback completely and resets the player state.

        This method unloads the current sound, unschedules the progress updates, resets
        the progress bar and playback position, and sets the play/pause button icon
        back to 'Play'.

        Args:
            _instance: The widget instance that triggered the event (unused).
        """
        if self.sound:
            self.sound.stop()
            self.sound.unload()
        self._unschedule_progress_update()
        self.progress_value = 0
        self._playing_position = 0
        self.progress_text = PlayerConstants.INIT_POS_DUR
        self.sound = None
        self.play_pause_button.background_normal = self._get_icon_path(PlayerConstants.ICON_PLAY)

    def restart_sound(self, _instance: typing.Any = None) -> None:
        """Restarts the current song from the beginning.

        If a sound is loaded, it stops it, resets the playback position to zero, and
        immediately starts playing it again.

        Args:
            _instance: The widget instance that triggered the event (unused).
        """
        if self.sound:
            self.sound.stop()
            self._playing_position = 0
            self.sound.play()
            self.play_pause_button.background_normal = self._get_icon_path(
                PlayerConstants.ICON_PAUSE)

    def set_volume(self, _slider_instance: typing.Any, volume_value: float) -> None:
        """Sets the playback volume.

        This method is typically called by the volume slider's `on_value` event. It updates
        the `volume` property and applies the new volume to the currently loaded sound.

        Args:
            _slider_instance: The slider instance that triggered the event (unused).
            volume_value: The new volume, a float between 0.0 and 1.0.
        """
        self.volume = volume_value
        if self.sound:
            self.sound.volume = volume_value

    def update_volume_label(self, _instance: typing.Any, value: float) -> None:
        """Updates the text of the volume label to reflect the current volume.

        This is bound to the `volume` property and formats the value as a percentage.

        Args:
            _instance: The property instance that changed (unused).
            value: The new volume value (0.0 to 1.0).
        """
        self.volume_label.text = f"Vol: {int(value * 100)}%"

    def show_error_popup(self, message: str) -> None:
        """Displays a modal error popup with a specified message.

        The popup contains the error message and a 'Close' button.

        Args:
            message: The error message string to display in the popup.
        """
        label = Label(
            text=message,
            text_size=(380, None),
            size_hint_y=None,
            color=PlayerConstants.ERROR_POPUP_TEXT_COLOR,
        )
        label.bind(texture_size=label.setter("size"))

        close_button = Button(
            text="Close",
            background_color=PlayerConstants.ERROR_POPUP_BUTTON_COLOR,
            color=(0, 0, 0, 1),  # Black text for close button
        )

        layout = BoxLayout(orientation="vertical", padding=10, spacing=10)
        layout.add_widget(label)
        layout.add_widget(close_button)

        popup = Popup(
            title="Error", content=layout, size_hint=(None, None), size=(400, 200)
        )
        close_button.bind(on_press=popup.dismiss)
        popup.open()

    def on_slider_move(self, instance: typing.Any, touch: typing.Any) -> None:
        """Handles user interaction with the progress bar to seek to a new position.

        When the user releases their touch on the progress bar, this method calculates
        the new playback position and tells the sound object to seek to that point.

        Args:
            instance: The progress bar slider instance.
            touch: The touch event object.
        """
        if self.sound and instance.collide_point(*touch.pos):
            self._playing_position = self.progress_bar.value
            self.sound.seek(self._playing_position)

    def _unschedule_progress_update(self) -> None:
        """Cancels the scheduled `update_progress` clock event, if it exists.

        This is called when playback is stopped or paused to prevent unnecessary updates.
        """
        if self._update_progress_event:
            Clock.unschedule(self._update_progress_event)
            self._update_progress_event = None

    def _schedule_progress_update(self, duration: float) -> None:
        """Schedules the `update_progress` method to be called periodically.

        This creates a `Clock` event that fires at a regular interval (`_schedule_interval`),
        allowing the progress bar and time display to be updated smoothly during playback.
        It also sets the `progress_max` value based on the song's actual duration.

        Args:
            duration: The duration of the song in seconds.
        """
        self._update_progress_event = Clock.schedule_interval(
            self.update_progress, self._schedule_interval
        )
        self.progress_max = round(duration)

    def _apply_platform_specific_play(self) -> None:
        """Applies platform-specific workarounds for sound playback.

        On Windows, there can be a delay before `sound.play()` takes effect, which can
        cause a subsequent `sound.seek()` to fail. This method schedules the play
        command with a slight delay on Windows to avoid this issue, while on other
        platforms it plays immediately.
        """
        def play_after_delay(_dt):
            self.sound.play()
            if self._playing_position > 0:
                self.sound.seek(self._playing_position)

        if platform.system() == "Windows":
            # Use Kivy's Clock to wait 0.1s without blocking
            Clock.schedule_once(play_after_delay, 0.1)
        else:
            # For other systems, play immediately
            self.sound.seek(self._playing_position)
            self.sound.play()

    def _update_song_button_highlight(self) -> None:
        """Updates the visual highlight for the currently playing song in the playlist.

        It resets the color of the previously highlighted button and sets the active
        color for the button corresponding to the current `playlist_idx`.
        """
        if self._current_button:
            self._current_button.background_color = PlayerConstants.SONG_BTN_BACKGROUND_COLOR

        if self._song_buttons and self.playlist_idx < len(self._song_buttons):
            self._current_button = self._song_buttons[self.playlist_idx]
            self._current_button.background_color = PlayerConstants.ACTIVE_SONG_BUTTON_COLOR

    def _scroll_to_current_song(self) -> None:
        """Automatically scrolls the playlist view to make the current song visible.

        This improves user experience by ensuring the currently playing item is always
        in view. It attempts to scroll slightly ahead of the current song for context.
        """
        if self._song_buttons and self.playlist_idx < len(self._song_buttons):
            # Try to scroll a few songs ahead for better visibility
            target_idx = min(self.playlist_idx + 2, len(self._song_buttons) - 1)
            self.scrollview.scroll_to(self._song_buttons[target_idx])

    def update_progress(self, _dt: float) -> None:
        """Periodically updates playback progress and handles automatic song transitions.

        This method is called by a `Clock` schedule. It updates the progress bar's value
        and time label. It also checks if the song has exceeded its maximum playtime to
        initiate a fade-out and advance to the next song.

        Args:
            _dt: The time delta in seconds since the last call (unused).
        """
        if self.sound is None or self.sound.state != "play":
            return

        self._playing_position = self.sound.get_pos()
        self.progress_value = round(self._playing_position)
        current_time_str = self._secs_to_time_str(self._playing_position)
        self.progress_text = f"{current_time_str} / {self._total_time}"

        if not self.play_single_song:
            try:
                song_info = self.playlist[self.playlist_idx]
                current_dance = song_info.get('dance', 'unknown')

                # Announcements should just play out; their natural duration is their max playtime.
                if current_dance == 'announce':
                    max_playtime = song_info.get('duration', self.song_max_playtime)
                else:
                    max_playtime = self.current_dance_max_playtimes.get(
                        current_dance, self.song_max_playtime
                    )
            except (IndexError, AttributeError):
                # Fallback if playlist structure is unexpected or index is out of bounds
                max_playtime = self.song_max_playtime

            self._handle_fade_out(max_playtime)
            self._check_and_advance_song(max_playtime)

        elif ( # if play_single_song is True, stop at the end and set icon to play
                self._playing_position >= self.progress_max - 1
            ):
            self.stop_sound()
            self.play_pause_button.background_normal = self._get_icon_path(
                PlayerConstants.ICON_PLAY)

    def _handle_fade_out(self, max_playtime: float) -> None:
        """Reduces the volume gradually when a song nears its max playtime.

        If the current playback position is beyond the `max_playtime`, this method calculates
        a fade factor and applies it to the sound's volume, creating a smooth fade-out effect
        over the duration defined by `PlayerConstants.FADE_TIME`.

        Args:
            max_playtime: The time in seconds at which the fade-out should begin.
        """
        if self._playing_position >= max_playtime and PlayerConstants.FADE_TIME > 0:
            fade_factor = max(
                0,
                1
                + self._schedule_interval
                * (max_playtime - self._playing_position)
                / PlayerConstants.FADE_TIME,
            )
            self.sound.volume = self.sound.volume * fade_factor

    def _check_and_advance_song(self, max_playtime: float) -> None:
        """Checks if the song should be advanced to the next one.

        A song is advanced if it reaches its natural end or if its playback time exceeds
        the `max_playtime` plus the fade-out duration.

        Args:
            max_playtime: The maximum configured playtime for the song.
        """
        if (
            self._playing_position >= self.progress_max - 1
            or self._playing_position > max_playtime + PlayerConstants.FADE_TIME
        ):
            self._advance_playlist()

    def _advance_playlist(self) -> None:
        """Advances to the next song in the playlist."""
        if self.sound:
            self.sound.unload()
        self.playlist_idx += 1
        self._playing_position = 0
        self.sound = None

        if self.playlist_idx < len(self.playlist):
            self.play_sound()
        elif self.auto_update_restart_playlist:
            # Call update_playlist with the flag to auto-start playback.
            self.update_playlist(start_playback=True)
        else:
            self.restart_playlist()

    def on_song_button_press(self, index: int) -> None:
        """Handles a button press on a song in the playlist view.

        This stops any currently playing music, sets the `playlist_idx` to the selected
        song's index, and starts playback of the new song.

        Args:
            index: The index of the song in the `playlist` that was clicked.
        """
        if self._playlist_generation_in_progress:
            return # Don't allow song selection while playlist is generating
        self.stop_sound()
        self._playing_position = 0
        self.playlist_idx = index
        self.sound = None
        self.play_sound()

    def _secs_to_time_str(self, time_sec: float) -> str:
        """Converts a duration in seconds to a formatted time string (e.g., "MM:SS").

        Args:
            time_sec: The time in seconds to format.

        Returns:
            A string formatted as "MM:SS" or "HH:MM:SS" if the duration is an hour or longer.
        """
        hours = int(time_sec // 3600)
        minutes = int((time_sec % 3600) // 60)
        seconds = int(time_sec % 60)
        return (
            f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            if hours > 0
            else f"{minutes:02d}:{seconds:02d}"
        )

    def restart_playlist(self, _instance: typing.Any = None) -> None:
        """Resets playback to the beginning of the current playlist.

        Stops any current playback, resets the `playlist_idx` to 0, updates the UI,
        and highlights the first song in the list without starting playback.

        Args:
            _instance: The widget instance that triggered the event (unused).
        """
        self.stop_sound()
        self.playlist_idx = 0
        self.song_title = PlayerConstants.INIT_SONG_TITLE
        self._reset_song_button_colors()
        if self._song_buttons and len(self._song_buttons) > 0:
            self._current_button = self._song_buttons[self.playlist_idx]
            self._current_button.background_color = PlayerConstants.ACTIVE_SONG_BUTTON_COLOR
            self.scrollview.scroll_to(self._current_button)

    def _reset_song_button_colors(self) -> None:
        """Resets the background color of all song buttons to the default state."""
        for btn in self._song_buttons:
            btn.background_color = PlayerConstants.SONG_BTN_BACKGROUND_COLOR

    def on_playlist_generation_status_change(
        self, _instance: typing.Any, is_generating: bool) -> None:
        """Provides user feedback when playlist generation starts or stops."""
        if is_generating:
            self.playlist_button.disabled = True
            self.button_grid.clear_widgets()
            loading_label = Label(
                text="Generating new playlist, please wait...", size_hint_y=None, height=40)
            self.button_grid.add_widget(loading_label)
        else:
            self.playlist_button.disabled = False

    def update_playlist(self, _instance: typing.Any = None, start_playback: bool = False) -> None:
        """Triggers the generation of a new playlist in a background thread."""
        if self._playlist_generation_in_progress:
            return

        self.stop_sound()
        self._playlist_generation_in_progress = True

        thread = threading.Thread(
            target=self._generate_playlist_in_background,
            args=(
                self.music_dir,
                self.dances,
                self.num_selections,
                self.randomize_playlist,
                start_playback
            ),
            daemon=True
        )
        thread.start()

    def _generate_playlist_in_background(
        self, directory: str, dances: list, num_selections: int,
        randomize: bool, start_playback: bool
    ) -> None:
        """Performs the blocking I/O of scanning files and reading metadata."""
        new_playlist = []
        for dance in dances:
            new_playlist.extend(self._get_songs_for_dance(
                directory, dance, num_selections, randomize))

        # Schedule the UI update to run on the main Kivy thread
        Clock.schedule_once(partial(
            self._finish_playlist_generation, new_playlist, start_playback
        ))

    def _finish_playlist_generation(
        self, new_playlist: list, start_playback: bool, _dt: float) -> None:
        """Updates the UI with the newly generated playlist."""
        self.playlist = new_playlist
        self.playlist_idx = 0
        self.sound = None
        self._display_playlist_buttons()
        self.restart_playlist()
        self._playlist_generation_in_progress = False

        # If triggered by an auto-update, start playing the first song.
        if start_playback and self.playlist:
            self.play_sound()

        # Prime GStreamer on Windows after the very first playlist is loaded
        if self._is_first_load and sys.platform == "win32":
            self._prime_gstreamer()
            self._is_first_load = False

    def _prime_gstreamer(self) -> None:
        """Workaround for GStreamer delay on Windows, called after first playlist is loaded."""
        try:
            if not self.playlist:
                return

            print("Priming GStreamer audio backend silently...")
            if (temp_sound := SoundLoader.load(self.playlist[0]['path'])):
                # Set volume to 0 to make the priming inaudible
                temp_sound.volume = 0
                temp_sound.play()

                # Let it play for a tiny fraction of a second then stop and unload
                def silent_stop(_dt):
                    temp_sound.stop()
                    temp_sound.unload()
                    print("GStreamer priming successful.")

                Clock.schedule_once(silent_stop, 0.1)

        except (IndexError, OSError, AttributeError, TypeError) as e:
            print(f"Non-critical error during GStreamer priming: {e}")

    def _display_playlist_buttons(self, playlist: typing.Optional[list] = None) -> None:
        """Renders the buttons for each song in the playlist view.

        It clears any existing buttons and creates a new button for each song in the provided
        playlist (or the instance's current playlist). If the playlist is empty, it displays
        a single button prompting the user to configure a music directory.

        Args:
            playlist: The list of song dictionaries to display. If None, uses `self.playlist`.
        """
        playlist_to_display = playlist if playlist is not None else self.playlist
        self.button_grid.clear_widgets()
        self._song_buttons = []

        if not playlist_to_display:
            # This handles both an empty playlist and the initial state before a music_dir is set
            if not self.music_dir:
                message = PlayerConstants.INIT_MUSIC_SELECTION
            else:
                message = "No songs found for the selected practice type. Check music sub-folders."

            btn = Button(
                text=message,
                size_hint_y=None,
                height=40,
                background_color=(1, 0, 0, 1),  # Red background for error
                color=PlayerConstants.DEFAULT_BUTTON_TEXT_COLOR,
            )
            btn.bind(on_press=lambda instance: App.get_running_app().open_settings())
            self._song_buttons.append(btn)
            self.button_grid.add_widget(btn)
        else:
            for i, song_info in enumerate(playlist_to_display):
                btn = Button(
                    text=self._get_song_label(song_info),
                    size_hint_y=None,
                    height=40,
                    background_color=PlayerConstants.SONG_BTN_BACKGROUND_COLOR,
                    color=PlayerConstants.DEFAULT_BUTTON_TEXT_COLOR,
                )
                btn.bind(on_press=lambda instance, idx=i: self.on_song_button_press(idx))
                self._song_buttons.append(btn)
                self.button_grid.add_widget(btn)

        # IMPORTANT: Add this spacer *after* all other buttons.
        # This Label will expand to fill available vertical space if the content doesn't,
        # pushing all previous content to the top.
        self.button_grid.add_widget(Label(size_hint_y=1))

    def _get_song_duration_str(self, duration_sec: float) -> str:
        """Returns the duration of a song as a formatted string from seconds.

        Args:
            duration_sec: The duration in seconds.

        Returns:
            A formatted duration string (e.g., "03:30").
        """
        return self._secs_to_time_str(duration_sec)

    def _get_song_label(self, song_info: dict) -> str:
        """Generates a descriptive label for a song from its pre-fetched metadata.
        
        For announcements, it only shows the title (e.g. 'Waltz'). For all
        other songs, it returns a label with title, genre, artist, and album.

        Args:
            song_info: The dictionary for the song containing its metadata.

        Returns:
            A formatted string to be used as the song's label.
        """
        # If the song is an announcement, just return its title.
        if song_info.get('dance') == 'announce':
            return song_info.get('title', "Announcement")

        # Otherwise, build the full label for a regular song.
        title = song_info.get('title', "Title Unspecified")
        genre = song_info.get('genre', "Genre Unspecified")
        artist = song_info.get('artist', "Artist Unspecified")
        album = song_info.get('album', "Album Unspecified")

        return f"{title} / {genre} / {artist} / {album}"

    # This method interprets the adjustment rules from the JSON file.
    def _get_adjusted_song_count(self, dance: str, num_selections: int) -> int:
        """
        Adjusts the number of songs for a dance based on rules defined in the
        current practice type's 'dance_adjustments' dictionary.
        """
        if not self.adjust_song_counts_for_playlist or dance not in self.current_dance_adjustments:
            return num_selections

        rule = self.current_dance_adjustments[dance]

        # Rule is a direct mapping (e.g., {"1": 0, "2": 1, "default": 2})
        if isinstance(rule, dict):
            num_selections_str = str(num_selections)
            if num_selections_str in rule:
                return rule[num_selections_str]
            return rule.get("default", num_selections)

        # Rule is a string formula (e.g., "n-1", "cap_at_1")
        if isinstance(rule, str):
            if rule == "n-1" and num_selections > 1:
                return num_selections - 1
            if rule == "cap_at_1" and num_selections > 1:
                return 1
            if rule == "cap_at_2" and num_selections > 2:
                return 2

        return num_selections

    def _create_song_info(self, path: str, dance: str) -> typing.Optional[dict]:
        """Reads metadata from a music file and returns it as a dictionary.

        Args:
            path: The full path to the music file.
            dance: The dance type associated with this song ('announce' for announcements).

        Returns:
            A dictionary containing song metadata, or None if reading fails.
        """
        try:
            tag = TinyTag.get(path)
            if dance == 'announce':
                return {
                    'path': path,
                    'dance': 'announce',
                    'title': pathlib.Path(path).stem,
                    'artist': 'Announcement', 'album': '', 'genre': '',
                    'duration': tag.duration if tag.duration is not None else 5,
                }
            return {
                'path': path,
                'dance': dance,
                'title': tag.title or pathlib.Path(path).stem,
                'artist': tag.artist or "Artist Unspecified",
                'album': tag.album or "Album Unspecified",
                'genre': tag.genre or "Genre Unspecified",
                'duration': tag.duration if tag.duration is not None else 300,
            }
        except (TinyTagException, OSError) as e:
            print(f"Could not read metadata for {path}: {e}")
            return None

    def _get_announce_path(self, dance_name: str) -> typing.Optional[str]:
        """Constructs the path for a dance announcement audio file.

        It first looks for a specific announcement file (e.g., 'Waltz.ogg') and
        falls back to a generic one ('Generic.ogg') if the specific one is not found.

        Args:
            dance_name: The name of the dance.

        Returns:
            The file path to the announcement audio, or None if not found.
        """
        announce_dir = os.path.join(self.script_path, "announce")
        specific_announce_path = os.path.join(announce_dir, f"{dance_name}.ogg")
        generic_announce_path = os.path.join(announce_dir, "Generic.ogg")

        if os.path.isfile(specific_announce_path):
            return specific_announce_path
        elif os.path.isfile(generic_announce_path):
            return generic_announce_path
        else:
            return None

    def _collect_music_files(self, directory: str, dance: str) -> list[str]:
        """Scans a directory for all valid music files.

        Args:
            directory: The root music directory.
            dance: The name of the dance subfolder.

        Returns:
            A list of full paths to all found music files.
        """
        if not directory or not os.path.isdir(directory):
            return []
        subdir = os.path.join(directory, dance)
        if not os.path.isdir(subdir):
            return []

        music_paths = []
        for root, _, files in os.walk(subdir):
            music_paths.extend(
                [os.path.join(root, file) for file in files if file.lower().endswith((
                    ".mp3", ".ogg", ".m4a", ".flac", ".wav"))])
        return music_paths

    def _get_songs_for_dance(
        self, directory: str, dance: str, num_selections: int, randomize: bool
    ) -> list:
        """Retrieves a list of song dictionaries for a specific dance.

        This method coordinates collecting music files, applying selection logic,
        reading metadata, and prepending a spoken announcement.

        Args:
            directory: The root music directory.
            dance: The name of the dance (and its subfolder).
            num_selections: The number of songs to retrieve (ignored if play_all_songs is True).
            randomize: If True, songs are shuffled; otherwise, they are sorted alphabetically.

        Returns:
            A list of song dictionaries with pre-fetched metadata, potentially
            including an announcement at the beginning.
        """
        # 1. Get the list of all available music files
        all_music_paths = self._collect_music_files(directory, dance)
        if not all_music_paths:
            return []

        # 2. Determine how many songs to select based on the practice type settings
        if self.play_all_songs:
            # If play_all_songs is true, we ignore num_selections and select all available songs
            num_to_sample = len(all_music_paths)
        else:
            # Otherwise, use the existing logic with num_selections and adjustments
            adjusted_num_selections = self._get_adjusted_song_count(dance, num_selections)
            if adjusted_num_selections == 0:
                return []
            num_to_sample = min(adjusted_num_selections, len(all_music_paths))

        # 3. Select the song paths (either by sampling or sorting)
        if randomize:
            # random.sample handles both selecting a subset and shuffling the whole list
            sampled_paths = random.sample(all_music_paths, k=num_to_sample)
        else:
            # Sorting and slicing works for both selecting a subset and getting the whole list
            sampled_paths = sorted(all_music_paths)[:num_to_sample]

        # 4. Create the song info dictionaries for the selected paths
        playlist = [
            song_info for path in sampled_paths
            if (song_info := self._create_song_info(path, dance)) is not None
        ]

        # 5. Get the announcement and prepend it to the playlist
        if (announce_path := self._get_announce_path(dance)) and \
        (announce_info := self._create_song_info(announce_path, 'announce')):
            playlist.insert(0, announce_info)

        return playlist

    def set_practice_type(self, _spinner_instance: typing.Any, text: str) -> None:
        """Configures player behavior based on the selected practice type.

        This powerful method acts as the central controller for switching between different
        practice modes. It looks up the `text` (e.g., "NC 60min", "Custom Latin") in a
        mapping dictionary and unpacks a tuple of parameters that define the behavior for
        that mode. It then updates all relevant Kivy properties, such as the dance list,
        randomization, and song count adjustments, before triggering a playlist update.

        Args:
            _spinner_instance: The spinner widget that triggered the change (unused).
            text: The name of the selected practice type.
        """
        default_adjustments = {
            "PasoDoble": {"1": 0, "2": 1, "3": 1, "default": 2}, "VWSlow": "cap_at_1",
            "JSlow": "cap_at_1", "VienneseWaltz": "n-1", "Jive": "n-1", "WCS": "cap_at_2"
        }
        mapping = {
            "60min": ("default", 2, False, False, False, True, True, default_adjustments, {"VienneseWaltz": 150}),
            "NC 60min": ("newcomer", 2, False, False, False, True, True, default_adjustments, {"VienneseWaltz": 150}),
        }
        # Merge in custom mappings using the union operator (Python 3.9+)
        mapping |= getattr(self, "custom_practice_mapping", {})
        params = mapping.get(text, ("default", 2, False, True, False, True, False, {}, {}))

        (dance_type, num_selections, play_all, auto_update, play_single, randomize,
         adj_counts, adj_dict, max_playtimes_dict) = params

        # Explicitly apply default_adjustments if adj_counts is True and adj_dict is empty
        if adj_counts and not adj_dict:
            adj_dict = default_adjustments

        self.dances = self.get_dances(dance_type)
        self.num_selections = num_selections
        self.play_all_songs = play_all
        self.auto_update_restart_playlist = auto_update
        self.play_single_song = play_single
        self.randomize_playlist = randomize
        self.adjust_song_counts_for_playlist = adj_counts
        self.current_dance_adjustments = adj_dict
        self.current_dance_max_playtimes = max_playtimes_dict

        if self.music_dir:
            self.update_playlist()


    def update_playlist_button_text(self, _instance: typing.Any, practice_type_value: str) -> None:
        """Updates the text of the 'New Playlist' button to show the current practice type.

        This method is bound to the `practice_type` property, ensuring the button label
        is always in sync with the current selection.

        Args:
            _instance: The property instance that changed (unused).
            practice_type_value: The new value of the `practice_type` property.
        """
        if self.playlist_button:
            self.playlist_button.text = f"New Playlist ({practice_type_value})"


class MusicApp(App):
    """The main Kivy application class.

    This class is the entry point for the application. It manages the app's lifecycle,
    handles configuration loading and saving, builds the settings panel, and initializes
    the main `MusicPlayer` widget.
    """
    home_dir: str = os.getenv("USERPROFILE") or os.getenv("HOME") or str(pathlib.Path.home())
    DEFAULT_MUSIC_DIR: str = os.path.join(home_dir, "Music")

    def __init__(self, **kwargs) -> None:
        """Initializes the MusicApp.

        Args:
            **kwargs: Keyword arguments for the parent `App` class.
        """
        super().__init__(**kwargs)
        self.config = ConfigParser()
        self.manager = None
        self.editor_screen = None
        self.player_widget = None

    def build(self) -> ScreenManager:
        """Creates and returns the root widget of the application."""
        self.settings_cls = SettingsWithSpinner
        
        # Create the screen manager
        self.manager = RootManager()

        # Create the MusicPlayer screen
        self.player_widget = MusicPlayer()
        player_screen = Screen(name='player')
        player_screen.add_widget(self.player_widget)
        self.manager.add_widget(player_screen)
        
        # Create and add the editor screen
        self.editor_screen = PlaylistEditorScreen(name='editor')
        self.manager.add_widget(self.editor_screen)

        return self.manager


    def on_start(self) -> None:
        """Called once the Kivy application event loop is running.

        This method loads settings from the configuration file, applies them to the root
        widget, and performs any platform-specific startup tasks, like the Windows
        GStreamer priming workaround.
        """
        self._load_config_settings()
        self.player_widget.set_practice_type(None, self.player_widget.practice_type)

        # Call platform-specific fixes only if on Windows
        if sys.platform == "win32":
            Clock.schedule_once(self._windows_startup_fixes, 1)

    def _load_config_settings(self) -> None:
        """Loads settings from the .ini config file and applies them to the player.

        It reads values for volume, music directory, max playtime, and practice type
        from the 'user' section of the config file. It uses sensible defaults if a
        setting is missing and validates the loaded practice type against the available options.
        """
        user_section = "user"
        if self.config.has_section(user_section):
            self.player_widget.volume = self.config.getfloat(user_section, "volume", fallback=0.7)
            self.player_widget.music_dir = self.config.get(
                user_section, "music_dir", fallback="" # Default to empty string
            )
            self.player_widget.song_max_playtime = self.config.getint(
                user_section, "song_max_playtime", fallback=210
            )
            # Get available practice types from settings_json
            self.player_widget.update_settings_options()
            practice_type_options = next(
                (
                    item["options"]
                    for item in self.player_widget.settings_json
                    if item.get("key") == "practice_type"
                ),
                []
            )
            loaded_practice_type = self.config.get(
                user_section, "practice_type", fallback="60min"
            )
            # If the loaded practice_type is not valid, reset to default
            if loaded_practice_type not in practice_type_options:
                loaded_practice_type = "60min"
                self.config.set(user_section, "practice_type", loaded_practice_type)
                self.config.write()
            self.player_widget.practice_type = loaded_practice_type

    def _windows_startup_fixes(self, _dt: float) -> None:
        """Applies startup fixes specific to the Windows platform."""
        self._hide_console_window()

    def _hide_console_window(self) -> None:
        """Hides the command-line console window that may appear on Windows."""
        # ctypes is available here because of the module-level conditional import.
        ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0) # type: ignore

    def build_config(self, config: ConfigParser) -> None:
        """Sets the default values for the application's configuration file.

        This method is called by Kivy the first time the application is run or when
        the config file is missing.

        Args:
            config: The `ConfigParser` instance to which default values are added.
        """
        config.setdefaults(
            "user",
            {
                "volume": 0.7,
                "music_dir": self.DEFAULT_MUSIC_DIR,
                "song_max_playtime": 210,
                "practice_type": "60min",
            },
        )

    def build_settings(self, settings: typing.Any) -> None:
        """Constructs the settings panel for the application.

        It creates a JSON panel using the structure defined in `MusicPlayer.settings_json`.

        Args:
            settings: The Kivy settings object to which the panel is added.
        """
        # Update settings options before showing them
        self.player_widget.update_settings_options()
        settings.add_json_panel(
            "Music Player Settings", self.config, data=json.dumps(self.player_widget.settings_json)
        )

    def on_config_change(
        self, config: ConfigParser, section: str, key: str, value: typing.Any
    ) -> None:
        """Callback that is fired when a setting is changed in the settings panel.

        This method listens for changes to the 'user' section of the configuration
        and updates the corresponding properties in the `MusicPlayer` instance in real-time.

        Args:
            config: The `ConfigParser` instance.
            section: The configuration section that was changed (e.g., "user").
            key: The key of the setting that was changed (e.g., "volume").
            value: The new value of the setting.
        """
        if section == "user":
            player = self.player_widget
            match key:
                case "volume":
                    try:
                        volume_value = float(value)
                        player.volume = volume_value
                        player.set_volume(None, volume_value)
                        # Directly update the slider value to reflect the change from settings
                        player.volume_slider.value = volume_value
                    except ValueError:
                        print(f"Error: Invalid volume value '{value}'. Must be a float.")
                case "music_dir":
                    player.music_dir = value
                    player.update_playlist()
                case "song_max_playtime":
                    try:
                        player.song_max_playtime = int(value)
                    except ValueError:
                        print(f"Error: Invalid max playtime value '{value}'. Must be an integer.")
                case "practice_type":
                    player.practice_type = value
                    # set_practice_type will trigger its own playlist update
                    player.set_practice_type(None, value)

if __name__ == "__main__":
    MusicApp().run()
