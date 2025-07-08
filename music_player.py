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
import time
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

    Handles the user interface, playlist management, playback controls, and interaction logic.
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
            "title": "Max Playtime",
            "desc": (
                "Set the maximum playtime for a song in seconds. The music fades out and "
                "stops after the maximum playtime.  This setting is ignored for "
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
                "90min",
                "NC 90min",
                "120min",
                "NC 120min",
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

        Returns:
            dict: Dictionary of custom practice types loaded from JSON, or empty dict if none found.
        """
        custom_types = {}
        json_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "custom_practice_types.json")
        if os.path.isfile(json_path):
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    raw_data = json.load(f)
                    # Filter out any keys that start with "__COMMENT__"
                    custom_types = {k: v for k, v in raw_data.items() if not k.startswith("__COMMENT__")}
            except (OSError, json.JSONDecodeError) as e:
                print(f"Failed to load custom practice types: {e}")
        return custom_types

    def merge_custom_practice_types(self) -> None:
        """Merge custom practice types into settings and dances.

        Updates the settings dropdown and internal mappings with user-defined practice types.
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
            )

    def _build_ui(self) -> None:
        """Builds the main user interface layout."""
        self._create_playlist_widgets()
        self._create_control_widgets()

    def _create_playlist_widgets(self) -> None:
        """Creates and adds the scrollable playlist area."""
        self.scrollview = ScrollView(size_hint=(1, 1), size=(self.width, 400))
        self.button_grid = GridLayout(cols=1, size_hint_y=None)
        self.button_grid.bind(minimum_height=self.button_grid.setter("height"))
        self.scrollview.add_widget(self.button_grid)
        self.add_widget(self.scrollview)

    def _create_control_widgets(self) -> None:
        """Creates and adds the volume, progress, and control buttons."""
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
        """Binds Kivy properties to UI updates and other methods."""
        self.volume_slider.bind(value=self.set_volume)
        self.bind(volume=self.update_volume_label)
        self.bind(song_title=self.song_title_label.setter("text"))
        self.bind(progress_max=self.progress_bar.setter("max"))
        self.bind(progress_value=self.progress_bar.setter("value"))
        self.progress_bar.bind(on_touch_up=self.on_slider_move)
        self.bind(progress_text=self.progress_label.setter("text"))
        self.bind(practice_type=self.update_playlist_button_text) # Bind practice_type here

    def _get_icon_path(self, icon_name: str) -> str:
        """Returns the full path to an icon.

        Args:
            icon_name (str): The filename of the icon.

        Returns:
            str: Full path to the icon file.
        """
        return os.path.join(self.script_path, "icons", icon_name)

    def get_dances(self, list_name: str) -> list:
        """Returns a list of dances based on the given list name.

        Args:
            list_name (str): The key for the dance list.

        Returns:
            list: List of dance names.
        """
        return self.practice_dances.get(list_name, self.practice_dances["default"])

    def toggle_play_pause(self, _instance: typing.Any = None) -> None:
        """Toggles between playing and pausing the current sound.

        Args:
            _instance: The button instance (unused).
        """
        if self.sound and self.sound.state == "play":
            self.pause_sound()
        else:
            self.play_sound()

    def play_sound(self) -> None:
        """Loads and plays the current song from the playlist."""
        if not self.playlist or self.playlist_idx >= len(self.playlist):
            self.restart_playlist()
            return

        current_song_path = self.playlist[self.playlist_idx]

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
        """Pauses the current sound."""
        if self.sound and self.sound.state == "play":
            self._playing_position = self.sound.get_pos()
            self.sound.stop()
            # Update the Play/Pause button icon to Play
            self.play_pause_button.background_normal = self._get_icon_path(
                PlayerConstants.ICON_PLAY)

    def stop_sound(self, _instance: typing.Any = None) -> None:
        """Stops the current sound and resets player state.

        Args:
            _instance: The button instance (unused).
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

        Args:
            _instance: The button instance (unused).
        """
        if self.sound:
            self.sound.stop()
            self._playing_position = 0
            self.sound.play()
            self.play_pause_button.background_normal = self._get_icon_path(
                PlayerConstants.ICON_PAUSE)

    def set_volume(self, _slider_instance: typing.Any, volume_value: float) -> None:
        """Sets the volume of the sound.

        Args:
            _slider_instance: The slider instance (unused).
            volume_value (float): The new volume value.
        """
        self.volume = volume_value
        if self.sound:
            self.sound.volume = volume_value

    def update_volume_label(self, _instance: typing.Any, value: float) -> None:
        """Updates the volume label text.

        Args:
            _instance: The property instance (unused).
            value (float): The new volume value.
        """
        self.volume_label.text = f"Vol: {int(value * 100)}%"

    def show_error_popup(self, message: str) -> None:
        """Displays an error popup with the given message.

        Args:
            message (str): The error message to display.
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
        """Handles seeking when the progress bar slider is moved.

        Args:
            instance: The slider instance.
            touch: The touch event.
        """
        if self.sound and instance.collide_point(*touch.pos):
            self._playing_position = self.progress_bar.value
            self.sound.seek(self._playing_position)

    def _unschedule_progress_update(self) -> None:
        """Unschedules the progress update clock event."""
        if self._update_progress_event:
            Clock.unschedule(self._update_progress_event)
            self._update_progress_event = None

    def _schedule_progress_update(self) -> None:
        """Schedules the progress update clock event."""
        self._update_progress_event = Clock.schedule_interval(
            self.update_progress, self._schedule_interval
        )
        self.progress_max = round(self.sound.length) if self.sound.length > 0 else 300

    def _apply_platform_specific_play(self) -> None:
        """Applies platform-specific workarounds for playing sound."""
        if platform.system() == "Windows":
            time.sleep(0.1)  # Hack to prevent losing position in the music
            self.sound.play()
            self.sound.seek(self._playing_position)
        else:
            self.sound.seek(self._playing_position)
            self.sound.play()

    def _update_song_button_highlight(self) -> None:
        """Highlights the current song's button and resets the previous one."""
        if self._current_button:
            self._current_button.background_color = PlayerConstants.SONG_BTN_BACKGROUND_COLOR

        if self._song_buttons:
            self._current_button = self._song_buttons[self.playlist_idx]
            self._current_button.background_color = PlayerConstants.ACTIVE_SONG_BUTTON_COLOR

    def _scroll_to_current_song(self) -> None:
        """Scrolls the playlist to make the current song visible."""
        if self._song_buttons and self.playlist_idx < len(self._song_buttons):
            # Try to scroll a few songs ahead for better visibility
            target_idx = min(self.playlist_idx + 2, len(self._song_buttons) - 1)
            self.scrollview.scroll_to(self._song_buttons[target_idx])

    def update_progress(self, _dt: float) -> None:
        """Updates the playback progress and handles song transitions.

        Args:
            _dt (float): The time delta since the last update.
        """
        if self.sound is None or self.sound.state != "play":
            return

        self._playing_position = self.sound.get_pos()
        self.progress_value = round(self._playing_position)
        current_time_str = self._secs_to_time_str(self._playing_position)
        self.progress_text = f"{current_time_str} / {self._total_time}"

        if not self.play_single_song:
            self._handle_fade_out()
            self._check_and_advance_song()
        elif ( # if play_single_song is True, stop at the end and set icon to play
                self._playing_position >= self.progress_max - 1
            ):
            self.stop_sound()
            self.play_pause_button.background_normal = self._get_icon_path(
                PlayerConstants.ICON_PLAY)

    def _handle_fade_out(self) -> None:
        """Handles fading out the music near the end of the song."""
        if self._playing_position >= self.song_max_playtime and PlayerConstants.FADE_TIME > 0:
            fade_factor = max(
                0,
                1
                + self._schedule_interval
                * (self.song_max_playtime - self._playing_position)
                / PlayerConstants.FADE_TIME,
            )
            self.sound.volume = self.sound.volume * fade_factor

    def _check_and_advance_song(self) -> None:
        """Checks if the song is finished or exceeded max playtime and advances."""
        if (
            self._playing_position >= self.progress_max - 1
            or self._playing_position > self.song_max_playtime + PlayerConstants.FADE_TIME
        ):
            self._advance_playlist()

    def _advance_playlist(self) -> None:
        """Advances to the next song in the playlist."""
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
        """Handles a song button press, playing the selected song.

        Args:
            index (int): The index of the song in the playlist.
        """
        self.stop_sound()  # Stop current sound and reset state
        self._playing_position = 0
        self.playlist_idx = index
        self.sound = None  # Ensure sound is reloaded for the new song
        self.play_sound()

    def _secs_to_time_str(self, time_sec: float) -> str:
        """Converts seconds to a formatted time string (MM:SS or HH:MM:SS)."""
        hours = int(time_sec // 3600)
        minutes = int((time_sec % 3600) // 60)
        seconds = int(time_sec % 60)
        return (
            f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            if hours > 0
            else f"{minutes:02d}:{seconds:02d}"
        )

    def restart_playlist(self, _instance: typing.Any = None) -> None:
        """Resets the playlist playback to the beginning.

        Args:
            _instance: The button instance (unused).
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
        """Resets the background color of all song buttons."""
        for btn in self._song_buttons:
            btn.background_color = PlayerConstants.SONG_BTN_BACKGROUND_COLOR

    def update_playlist(self, directory: str, _instance: typing.Any = None) -> None:
        """Updates the playlist based on the selected music directory and dance types.

        Args:
            directory (str): The directory containing music.
            _instance: The button instance (unused).
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
        """Clears existing song buttons and creates new ones for the current playlist.

        Args:
            playlist (list, optional): Playlist to display. Defaults to None.
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
            for i, song_path in enumerate(playlist_to_display):
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

    def _get_song_duration_str(self, selection: str) -> str:
        """Returns the duration of a song as a formatted string.

        Args:
            selection (str): Path to the song file.

        Returns:
            str: Duration in MM:SS or HH:MM:SS format.
        """
        tag = TinyTag.get(selection)
        duration = tag.duration if tag.duration is not None else 300
        return self._secs_to_time_str(duration)

    def _get_song_label(self, selection: str) -> str:
        """Generates a display label for a song using its metadata.

        Args:
            selection (str): Path to the song file.

        Returns:
            str: Formatted label for the song.
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

    def _get_songs_for_dance(
        self, directory: str, dance: str, num_selections: int, randomize: bool) -> list:
        """Collects songs for a given dance type, either randomized or sorted.

        Args:
            directory (str): The directory containing music.
            dance (str): The specific dance sub-folder.
            num_selections (int): The number of songs to select.
            randomize (bool): True to randomize, False to sort.

        Returns:
            list: A list of selected song paths, potentially including an announcement.
        """
        def get_announce_path(dance):
            announce_path = os.path.join(self.script_path, "announce", f"{dance}.ogg")
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
                    music.append(os.path.join(root, file))

        if not music:
            return []

        num = min(adjusted_num_selections, len(music))
        if randomize:
            selected_songs = random.sample(music, num)
        else:
            selected_songs = sorted(random.sample(music, num))

        announce = get_announce_path(dance)
        if announce:
            selected_songs.insert(0, announce)
        return selected_songs

    def set_practice_type(self, _spinner_instance: typing.Any, text: str) -> None:
        """Sets the practice type and updates the playlist accordingly.

        Args:
            _spinner_instance: The spinner instance (unused).
            text (str): The selected practice type.
        """
        default_adjustments = {
            "PasoDoble": {"1": 0, "2": 1, "3": 1, "default": 2}, "VWSlow": "cap_at_1",
            "JSlow": "cap_at_1", "VienneseWaltz": "n-1", "Jive": "n-1", "WCS": "cap_at_2"
        }
        mapping = {
            "60min": ("default", 2, False, False, True, True, default_adjustments),
            "NC 60min": ("newcomer", 2, False, False, True, True, default_adjustments),
            "90min": ("default", 3, False, False, True, True, default_adjustments),
            "NC 90min": ("newcomer", 3, False, False, True, True, default_adjustments),
            "120min": ("default", 4, False, False, True, True, default_adjustments),
            "NC 120min": ("newcomer", 4, False, False, True, True, default_adjustments),
        }
        # Merge in custom mappings using the union operator (Python 3.9+)
        mapping |= getattr(self, "custom_practice_mapping", {})
        params = mapping.get(text, ("default", 2, True, False, True, False, {}))

        (dance_type, num_selections, auto_update, play_single, randomize, adj_counts,
         adj_dict) = params

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

        self.stop_sound()
        self.update_playlist(self.music_dir)
        # The practice_type property will trigger update_playlist_button_text automatically

    def update_playlist_button_text(self, _instance: typing.Any, practice_type_value: str) -> None:
        """Updates the text of the 'New Playlist' button to include the current practice type.

        Args:
            _instance: The property instance (unused).
            practice_type_value (str): The current value of the practice_type property.
        """
        if self.playlist_button:
            self.playlist_button.text = f"New Playlist ({practice_type_value})"


class MusicApp(App):
    """Kivy application class for the dance practice music player.

    Manages configuration, settings, and application-level startup logic.
    """
    home_dir: str = os.getenv("USERPROFILE") or os.getenv("HOME") or str(pathlib.Path.home())
    DEFAULT_MUSIC_DIR: str = os.path.join(home_dir, "Music")

    def __init__(self, **kwargs) -> None:
        """Initializes the MusicApp and its configuration."""
        super().__init__(**kwargs)
        self.config = ConfigParser()

    def build(self) -> MusicPlayer:
        """Builds and returns the root widget for the application."""
        self.settings_cls = SettingsWithSpinner
        self.root = MusicPlayer()
        return self.root

    def on_start(self) -> None:
        """Configures the application settings and initializes the player on app start."""
        self._load_config_settings()
        self.root.set_practice_type(None, self.root.practice_type)

        # Call platform-specific fixes only if on Windows
        if sys.platform == "win32":
            Clock.schedule_once(self._windows_startup_fixes, 1)

    def _load_config_settings(self) -> None:
        """Loads configuration settings into the MusicPlayer instance."""
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
        """Applies Windows-specific startup fixes.

        Args:
            _dt (float): The time delta since the last update.
        """
        # These methods are only called if sys.platform is 'win32',
        # ensuring ctypes is already imported and available.
        self._hide_console_window()
        self._prime_gstreamer()

    def _hide_console_window(self) -> None:
        """Hides the console window on Windows."""
        # ctypes is available here because of the module-level conditional import.
        ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0) # type: ignore

    def _prime_gstreamer(self) -> None:
        """Workaround to prevent noticeable delay when playing the first selection."""
        try:
            if (
                self.root
                and self.root.playlist
                and self.root.playlist_idx is not None
                and (temp_sound := SoundLoader.load(self.root.playlist[self.root.playlist_idx]))
            ):
                temp_sound.play()
                temp_sound.stop()
                temp_sound.unload()  # Unload immediately after priming
        except (IndexError, OSError, AttributeError) as e:
            print(f"Error during gstreamer priming: {e}")

    def build_config(self, config: ConfigParser) -> None:
        """Sets default configuration values.

        Args:
            config: The Kivy ConfigParser instance.
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
        """Builds the settings panel for the application.

        Args:
            settings: The Kivy settings instance.
        """
        settings.add_json_panel(
            "Music Player Settings", self.config, data=json.dumps(self.root.settings_json)
        )

    def on_config_change(
        self, config: ConfigParser, section: str, key: str, value: typing.Any
    ) -> None:
        """Handles changes in application configuration.

        Args:
            config: The Kivy ConfigParser instance.
            section (str): The section of the config that changed.
            key (str): The key that changed.
            value: The new value.
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
