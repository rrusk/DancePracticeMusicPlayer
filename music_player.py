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
from tinytag import TinyTag

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

        if not self.playlist and self.music_dir:
            self.update_playlist(self.music_dir)

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
                data.get("auto_update", False),
                data.get("play_single_song", False),
                data.get("randomize_playlist", True),
                data.get("adjust_song_counts", False),
                data.get("dance_adjustments", {}),
                data.get("dance_max_playtimes", {}),
            )

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

        self.play_pause_button.bind(on_press=self.toggle_play_pause)
        stop_button.bind(on_press=self.stop_sound)
        restart_button.bind(on_press=self.restart_sound)
        self.playlist_button.bind(on_press=lambda instance: self.update_playlist(self.music_dir))
        settings_button.bind(on_press=lambda instance: App.get_running_app().open_settings())

        control_buttons.add_widget(self.play_pause_button)
        control_buttons.add_widget(stop_button)
        control_buttons.add_widget(restart_button)
        control_buttons.add_widget(self.playlist_button) # Use the ObjectProperty
        control_buttons.add_widget(settings_button)
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

        current_song_path = self.playlist[self.playlist_idx]['path']
        self.music_file = current_song_path # needed to get song duration

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
        self._total_time = self._get_song_duration_str(current_song_path)
        self.song_title = self._get_song_label(current_song_path)[:90]

        self._update_song_button_highlight()
        self._scroll_to_current_song()

        self._unschedule_progress_update()
        self._schedule_progress_update()

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

    def _schedule_progress_update(self) -> None:
        """Schedules the `update_progress` method to be called periodically.

        This creates a `Clock` event that fires at a regular interval (`_schedule_interval`),
        allowing the progress bar and time display to be updated smoothly during playback.
        It also sets the `progress_max` value based on the song's actual duration.
        """
        self._update_progress_event = Clock.schedule_interval(
            self.update_progress, self._schedule_interval
        )
        # Use TinyTag to get the accurate duration for progress_max
        if self.music_file and os.path.exists(self.music_file):
            tag = TinyTag.get(self.music_file)
            duration = tag.duration if tag.duration is not None else 300
            self.progress_max = round(duration)
        else:
            self.progress_max = 300 # Fallback in case music_file is not set or valid

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

        if self._song_buttons:
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
                    max_playtime = self.progress_max
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
        """Advances to the next song in the playlist.

        This method increments the `playlist_idx`, unloads the completed song, and
        initiates playback of the next song. If the end of the playlist is reached,
        it either regenerates the playlist (if `auto_update_restart_playlist` is True)
        or stops playback.
        """
        if self.sound:
            self.sound.unload()
        self.playlist_idx += 1
        self._playing_position = 0
        self.sound = None  # Force reloading for the next song

        if self.playlist_idx < len(self.playlist):
            self.play_sound()
        elif self.auto_update_restart_playlist:
            self.update_playlist(self.music_dir)
            # Restart with the first song after updating playlist
            self.on_song_button_press(0)
        else:
            self.restart_playlist()

    def on_song_button_press(self, index: int) -> None:
        """Handles a button press on a song in the playlist view.

        This stops any currently playing music, sets the `playlist_idx` to the selected
        song's index, and starts playback of the new song.

        Args:
            index: The index of the song in the `playlist` that was clicked.
        """
        self.stop_sound()  # Stop current sound and reset state
        self._playing_position = 0
        self.playlist_idx = index
        self.sound = None  # Ensure sound is reloaded for the new song
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
        self.stop_sound()  # Use the existing stop_sound to handle unloading and unscheduling
        self.playlist_idx = 0
        self.song_title = PlayerConstants.INIT_SONG_TITLE
        self._reset_song_button_colors()
        if self._song_buttons:
            self._current_button = self._song_buttons[self.playlist_idx]
            self._current_button.background_color = PlayerConstants.ACTIVE_SONG_BUTTON_COLOR
            self.scrollview.scroll_to(self._current_button)

    def _reset_song_button_colors(self) -> None:
        """Resets the background color of all song buttons to the default state."""
        for btn in self._song_buttons:
            btn.background_color = PlayerConstants.SONG_BTN_BACKGROUND_COLOR

    def update_playlist(self, directory: str, _instance: typing.Any = None) -> None:
        """Generates a new playlist based on the current settings.

        This method stops any current playback, clears the existing playlist, and then iterates
        through the `dances` list for the current practice type. For each dance, it fetches
        the specified number of songs from the corresponding subdirectory in the `directory`.
        Finally, it refreshes the UI to display the new playlist.

        Args:
            directory: The root directory containing the music subfolders.
            _instance: The widget instance that triggered the event (unused).
        """
        self.stop_sound()
        self.playlist = []
        for dance in self.dances:
            self.playlist.extend(self._get_songs_for_dance(
                directory, dance, self.num_selections, self.randomize_playlist))
        self.playlist_idx = 0
        self.sound = None
        self._display_playlist_buttons()
        self.restart_playlist()

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
            btn = Button(
                text=PlayerConstants.INIT_MUSIC_SELECTION,
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
                song_path = song_info['path']
                btn = Button(
                    text=self._get_song_label(song_path),
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

    def _get_song_duration_str(self, selection: str) -> str:
        """Retrieves the duration of a media file using TinyTag and formats it.

        Args:
            selection: The file path to the song.

        Returns:
            A formatted duration string (e.g., "03:30").
        """
        tag = TinyTag.get(selection)
        duration = tag.duration if tag.duration is not None else 300
        return self._secs_to_time_str(duration)

    def _get_song_label(self, selection: str) -> str:
        """Generates a descriptive label for a song from its metadata.

        It uses TinyTag to extract title, genre, artist, and album. If no tags are found,
        it falls back to the filename.

        Args:
            selection: The file path to the song.

        Returns:
            A formatted string like "Title / Genre / Artist / Album".
        """
        label = pathlib.Path(selection).stem
        tag = TinyTag.get(selection)

        if all(
            [tag.title is None, tag.genre is None, tag.artist is None, tag.album is None]
        ):
            return label

        title = tag.title if tag.title is not None else "Title Unspecified"
        genre = tag.genre if tag.genre is not None else "Genre Unspecified"
        artist = tag.artist if tag.artist is not None else "Artist Unspecified"
        album = tag.album if tag.album is not None else "Album Unspecified"

        return f"{title} / {genre} / {artist} / {album}"

    def _get_adjusted_song_count(self, dance: str, num_selections: int) -> int:
        """Adjusts the number of songs for a dance based on custom rules.

        This function consults the `current_dance_adjustments` dictionary for the active
        practice type. Rules can be either a dictionary mapping input counts to output counts
        (e.g., {"1": 0, "2": 1}) or a string formula (e.g., "n-1", "cap_at_1").

        Args:
            dance: The name of the dance to check for adjustment rules.
            num_selections: The base number of selections before adjustment.

        Returns:
            The adjusted number of songs. Returns `num_selections` if no rules apply.
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

    def _get_songs_for_dance(
        self, directory: str, dance: str, num_selections: int, randomize: bool) -> list:
        """Retrieves a list of song file paths for a specific dance.

        It scans the subdirectory corresponding to the `dance` name, collects all valid
        music files, and selects a sample based on `num_selections` and the `randomize` flag.
        It can also prepend a spoken announcement file (e.g., "Waltz.ogg") if one exists.

        Args:
            directory: The root music directory.
            dance: The name of the dance (and its subfolder).
            num_selections: The number of songs to retrieve.
            randomize: If True, songs are shuffled; otherwise, they are sorted alphabetically.

        Returns:
            A list of song dictionaries, where each dictionary contains the path and dance type.
        """
        def get_announce_path(dance_name):
            announce_path = os.path.join(self.script_path, "announce", f"{dance_name}.ogg")
            generic_announce_path = os.path.join(self.script_path, "announce", "Generic.ogg")
            if os.path.isfile(announce_path):
                return announce_path
            elif os.path.isfile(generic_announce_path):
                return generic_announce_path
            else:
                return None

        music = []
        adjusted_num_selections = self._get_adjusted_song_count(dance, num_selections)
        subdir = os.path.join(directory, dance)

        if not os.path.exists(subdir):
            return []

        for root, _, files in os.walk(subdir):
            for file in files:
                if file.endswith((".mp3", ".ogg", ".m4a", ".flac", ".wav")):
                    music.append({'path': os.path.join(root, file), 'dance': dance})

        if not music:
            return []

        num = min(adjusted_num_selections, len(music))
        if randomize:
            selected_songs = random.sample(music, num)
        else:
            selected_songs = sorted(random.sample(music, num), key=lambda x: x['path'])

        announce = get_announce_path(dance)
        if announce:
            selected_songs.insert(0, {'path': announce, 'dance': 'announce'})
        return selected_songs

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
            "60min": ("default", 2, False, False, True, True, default_adjustments, {}),
            "NC 60min": ("newcomer", 2, False, False, True, True, default_adjustments, {}),
        }
        # Merge in custom mappings using the union operator (Python 3.9+)
        mapping |= getattr(self, "custom_practice_mapping", {})
        params = mapping.get(text, ("default", 2, True, False, True, False, {}, {}))

        (dance_type, num_selections, auto_update, play_single, randomize, adj_counts,
         adj_dict, max_playtimes_dict) = params

        # Explicitly apply default_adjustments if adj_counts is True and adj_dict is empty
        if adj_counts and not adj_dict:
            adj_dict = default_adjustments

        self.dances = self.get_dances(dance_type)
        self.num_selections = num_selections
        self.auto_update_restart_playlist = auto_update
        self.play_single_song = play_single
        self.randomize_playlist = randomize
        self.adjust_song_counts_for_playlist = adj_counts
        self.current_dance_adjustments = adj_dict
        self.current_dance_max_playtimes = max_playtimes_dict

        self.stop_sound()
        self.update_playlist(self.music_dir)
        # The practice_type property will trigger update_playlist_button_text automatically

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

    def build(self) -> MusicPlayer:
        """Creates and returns the root widget of the application.

        This method is called by Kivy when the app starts. It instantiates the `MusicPlayer`
        widget, which serves as the main interface.

        Returns:
            An instance of the `MusicPlayer` widget.
        """
        self.settings_cls = SettingsWithSpinner
        self.root = MusicPlayer()
        return self.root

    def on_start(self) -> None:
        """Called once the Kivy application event loop is running.

        This method loads settings from the configuration file, applies them to the root
        widget, and performs any platform-specific startup tasks, like the Windows
        GStreamer priming workaround.
        """
        self._load_config_settings()
        self.root.set_practice_type(None, self.root.practice_type)

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
            self.root.volume = self.config.getfloat(user_section, "volume", fallback=0.7)
            self.root.music_dir = self.config.get(
                user_section, "music_dir", fallback=self.DEFAULT_MUSIC_DIR
            )
            self.root.song_max_playtime = self.config.getint(
                user_section, "song_max_playtime", fallback=210
            )
            # Get available practice types from settings_json
            practice_type_options = next(
                (
                    item["options"]
                    for item in self.root.settings_json
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
            self.root.practice_type = loaded_practice_type

    def _windows_startup_fixes(self, _dt: float) -> None:
        """Applies startup fixes specific to the Windows platform.

        Args:
            _dt: The time delta since the schedule (unused).
        """
        # These methods are only called if sys.platform is 'win32',
        # ensuring ctypes is already imported and available.
        self._hide_console_window()
        self._prime_gstreamer()

    def _hide_console_window(self) -> None:
        """Hides the command-line console window that may appear on Windows."""
        # ctypes is available here because of the module-level conditional import.
        ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0) # type: ignore

    def _prime_gstreamer(self) -> None:
        """Workaround for a GStreamer issue on Windows causing a delay on first play.

        This method quickly loads, plays, stops, and unloads the first song in the
        playlist. This "primes" the GStreamer backend, preventing a noticeable lag
        when the user clicks play for the first time.
        """
        try:
            if (
                self.root
                and self.root.playlist
                and self.root.playlist_idx is not None
                and (temp_sound := SoundLoader.load(
                    self.root.playlist[self.root.playlist_idx]['path']))
            ):
                temp_sound.play()
                temp_sound.stop()
                temp_sound.unload()  # Unload immediately after priming
        except (IndexError, OSError, AttributeError) as e:
            print(f"Error during gstreamer priming: {e}")

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
        settings.add_json_panel(
            "Music Player Settings", self.config, data=json.dumps(self.root.settings_json)
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
            match key:
                case "volume":
                    try:
                        volume_value = float(value)
                        self.root.volume = volume_value
                        self.root.set_volume(None, volume_value)
                        # Directly update the slider value to reflect the change from settings
                        self.root.volume_slider.value = volume_value
                    except ValueError:
                        print(f"Error: Invalid volume value '{value}'. Must be a float.")
                case "music_dir":
                    self.root.music_dir = value
                    self.root.update_playlist(value)
                case "song_max_playtime":
                    try:
                        self.root.song_max_playtime = int(value)
                    except ValueError:
                        print(f"Error: Invalid max playtime value '{value}'. Must be an integer.")
                case "practice_type":
                    self.root.practice_type = value
                    self.root.set_practice_type(None, value)

if __name__ == "__main__":
    MusicApp().run()
