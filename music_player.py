# music_player.py
# pylint: disable=too-many-lines
"""Dance Practice Music Player

A Kivy-based application for managing and playing playlists for ballroom and line dance practice.
Supports configurable practice types, playlist management, and platform-specific audio handling.

Competition rounds
------------------
A practice type may define `segments` instead of relying on the `dances` list.
A segment is either a round of dances or a cue::

    "segments": [
        {"cue": "round_gap", "label": "2:00 break - next: Final #1"},
        {"round": ["Waltz", "Tango", "VienneseWaltz", "Foxtrot", "QuickStep"],
         "count": 1, "clip_seconds": 90, "gap_seconds": 20}
    ]

This models a real competition rather than a practice: each dance is cut off at a
fixed length, optionally fading over the last few seconds of it, there are no
spoken announcements, dances are separated by a short gap, and rounds are
separated by a longer gap carrying a warning tone.

Cues are ordinary audio files in `cues/`, so gaps and warnings need no special
handling during playback -- they are playlist items like any other. Generate them
with `cues/make_cues.sh`.

Timed practice blocks
---------------------
A practice type may define `dance_minutes`, e.g.::

    "dance_minutes": {"Waltz": 13, "Tango": 13, "VienneseWaltz": 8}

A dance listed there is filled to that many minutes of playing time instead of
being given a fixed song count. Songs are drawn until the block budget is met,
then a single uniform trim is spread across every song in the block so the block
lands exactly on its budget. Each song keeps its own natural length minus that
shared trim, so a block is not a run of equal-length clips.

Dances not listed in `dance_minutes` keep using `num_selections` /
`dance_adjustments`, so practice types that do not use the key are unaffected.
"""
import os
import platform
import pathlib
import random
import json
import sys
import time
import typing
import threading
from functools import partial

# Started before the Kivy imports so that startup timing includes them; they are
# the slowest part of launching on an older laptop. Set DPMP_TIMING=1 to report.
_START_TIME = time.perf_counter()
TIMING_ENABLED = bool(os.environ.get("DPMP_TIMING"))

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
from kivy.uix.settings import (
    SettingNumeric,
    SettingOptions,
    SettingPath,
    SettingsWithSpinner,
)
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.config import ConfigParser
from kivy.graphics import Color, RoundedRectangle
from kivy.logger import Logger
from kivy.metrics import dp
from tinytag import TinyTag, TinyTagException

import app_paths
import practice_type_rules
from song_cache import SongCache

# --- Imports for ScreenManager and the editor screen ---
from practice_type_editor import PracticeTypeEditorScreen


# Conditional import for Windows-specific functionality
# This ensures ctypes is only imported if on Windows,
# and is then available throughout the module's global scope.
if sys.platform == "win32":
    import ctypes
else:
    # Ensure ctypes is defined for all platforms to suppress PyLint warnings
    ctypes = None  # pylint: disable=invalid-name


def timing_mark(label: str, since: float = None) -> None:
    """Reports how long startup has taken so far, when DPMP_TIMING is set.

    Written through the Kivy logger rather than print, because the console window
    is hidden on Windows and these measurements are wanted from the practice
    laptops, where the log file is the only way to get them back.

    Args:
        label: What has just finished.
        since: A perf_counter value to report the elapsed time from, for timing a
            single operation rather than everything up to this point.
    """
    if not TIMING_ENABLED:
        return
    if since is None:
        Logger.info(f"Timing: {time.perf_counter() - _START_TIME:7.3f}s total  {label}")
    else:
        Logger.info(f"Timing: {time.perf_counter() - since:7.3f}s         {label}")


timing_mark("kivy and tinytag imported")


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

    # --- Timed practice blocks ---
    # Largest uniform trim applied to each song to make a block fit its budget.
    # If the trim would exceed this, the last song is dropped and the block runs
    # short instead, rather than audibly chopping every song in the block.
    # How long a song may take to actually start playing before the attempt is
    # judged to have failed. Comfortably longer than the 0.1s Windows delay.
    PLAYBACK_START_GRACE = 2.0
    # Consecutive failed starts before giving up rather than walking the playlist.
    MAX_CONSECUTIVE_START_FAILURES = 3

    MAX_TRIM_SECONDS = 45
    MIN_SONG_PLAY_SECONDS = 60  # A song is never trimmed below this.

    # --- Song selection ---
    # Songs shorter than this are passed over when a practice type picks a fixed
    # number of selections per dance, where a very short track would just make the
    # practice end early. Timed blocks are unaffected: a short song there simply
    # means one more song in the block, which still lands on its budget.
    MIN_SONG_LENGTH_SECONDS = 90

    # Icon filenames as constants
    ICON_PLAY = "play.png"
    ICON_PAUSE = "pause.png"
    ICON_STOP = "stop.png"
    ICON_REPLAY = "replay.png"

    # Practice Type Constants
    PRACTICE_TYPE_60_MIN = "60min"
    PRACTICE_TYPE_NC_60_MIN = "NC 60min"
    
    # --- Competition rounds ---
    CUES_DIR = "cues"  # Folder holding gap/warning audio, see cues/make_cues.sh
    ROUND_GAP_CUE = "round_gap"  # 2:00 between rounds, warning tone at 1:40
    # Playback advances this many seconds before an item's natural end. Cues are
    # timing devices, so they get a tighter margin than music does.
    END_MARGIN = 1.0
    CUE_END_MARGIN = 0.2

    # Files
    HISTORY_FILE = "play_history.json"
    SONG_CACHE_FILE = "song_metadata_cache.json"


# --- Root ScreenManager Widget ---
class RootManager(ScreenManager):
    """The root ScreenManager that holds the player and editor screens."""
    def reload_custom_types(self):
        """
        Finds the music player screen, tells it to reload its custom
        playlist definitions, and reapplies the settings for the current
        practice type.
        """
        player_screen = self.get_screen('player')
        # The MusicPlayer widget is the first child of the Screen
        player_widget = player_screen.children[0]
        player_widget.merge_custom_practice_types()
        player_widget.update_settings_options()
        player_widget.set_practice_type(None, player_widget.practice_type)
        App.get_running_app().destroy_settings()


class EditableSettingMixin:
    """Makes a Kivy setting value look like an interactive control."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.content.padding = (dp(8), 0)
        with self.content.canvas.before:
            Color(47 / 255, 167 / 255, 212 / 255, 0.18)
            self._value_background = RoundedRectangle(radius=[dp(4)])
        self.content.bind(pos=self._position_value_background,
                          size=self._position_value_background)
        self._position_value_background()
        self.content.add_widget(Label(
            text="›", size_hint_x=None, width=dp(28),
            font_size="24sp", color=(47 / 255, 167 / 255, 212 / 255, 1)))

    def _position_value_background(self, *_args) -> None:
        self._value_background.pos = self.content.pos
        self._value_background.size = self.content.size


class EditableSettingNumeric(EditableSettingMixin, SettingNumeric):
    """Numeric setting with an explicit visual affordance."""


class EditableSettingPath(EditableSettingMixin, SettingPath):
    """Path setting with an explicit visual affordance."""


class EditableSettingOptions(EditableSettingMixin, SettingOptions):
    """Options setting with an explicit visual affordance."""


class MusicSettings(SettingsWithSpinner):
    """Settings panel whose editable values and exit action look actionable."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.register_type("editable_numeric", EditableSettingNumeric)
        self.register_type("editable_path", EditableSettingPath)
        self.register_type("editable_options", EditableSettingOptions)

        close_button = self.interface.menu.close_button
        close_button.text = "Done — Return to Player"
        close_button.background_normal = ""
        close_button.background_color = (0.2, 0.6, 0.8, 1)


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
        current_dance_minutes (DictProperty): Per-dance block budgets in minutes for the
            active practice type. A dance listed here is filled to that many minutes
            instead of being given a fixed song count.
        current_segments (ListProperty): Competition rounds and cues for the active
            practice type. When non-empty the playlist is built from these instead
            of from the `dances` list.
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
    current_dance_minutes = DictProperty({})
    current_dance_intros = DictProperty({})
    current_segments = ListProperty([])

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
    practice_type = StringProperty(PlayerConstants.PRACTICE_TYPE_60_MIN)
    num_selections = NumericProperty(2)

    settings_json = [
        {
            "type": "title",
            "title": "Click any setting below to change it",
        },
        {
            "type": "editable_numeric",
            "title": "Volume",
            "desc": "Set the music volume; range is 0.0 to 1.0.",
            "section": "user",
            "key": "volume",
        },
        {
            "type": "editable_path",
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
            "type": "editable_numeric",
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
            "type": "editable_options",
            "title": "Practice Type",
            "desc": (
                "Choose the practice type/length. Un-prefixed times are dances played in "
                "competition order. The prefix NC (for newcomer) modifies the order of dances. "
                "Use Manage Practice Types in the player to add or edit custom types; "
                "their dances are played in the order listed. Types based on song counts have "
                "an approximate duration; Auto Update/Restart can keep generating music until "
                "the practice is stopped. Timed blocks and competition rounds use their "
                "configured timings instead."
            ),
            "section": "user",
            "key": "practice_type",
            "options": [
                PlayerConstants.PRACTICE_TYPE_60_MIN,
                PlayerConstants.PRACTICE_TYPE_NC_60_MIN,
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
    _song_cache = None  # Lazily created SongCache, shared by all reads
    # Settings frozen for the duration of one background generation, so that
    # changing practice type mid-generation cannot produce a hybrid playlist.
    _generation_config = None
    _regeneration_pending = False
    _regeneration_start_playback = False
    _pending_play_event = None  # Scheduled delayed play on Windows, if any
    # True once the backend has been seen actually playing the current item, so
    # that a later stop can be told apart from one the user asked for.
    _playback_observed = False
    # When playback was last asked to start. A decoder that fails within the
    # first tick never sets _playback_observed, so a start that has not produced
    # playing state by PLAYBACK_START_GRACE is treated as a failed start.
    _playback_requested_at = None
    _consecutive_start_failures = 0
    # Names of the songs that failed to start, reported together rather than one
    # modal popup at a time. A tuple so the class-level default cannot be shared.
    _failed_start_songs = ()


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

        timing_mark("player widget built")

        if self.music_dir:
            self.update_playlist()
        else:
            self._display_playlist_buttons()

    def load_custom_practice_types(self) -> dict:
        """
        Loads practice types from both the built-in JSON (distributed via git)
        and the user's local custom JSON.
        """
        builtin_path = app_paths.app_path("builtin_practice_types.json")
        custom_path = app_paths.user_path("custom_practice_types.json")

        def load_json(path):
            data = {}
            if os.path.isfile(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        raw = json.load(f)
                except (OSError, json.JSONDecodeError) as e:
                    print(f"Failed to load {path}: {e}")
                    return data

                # Valid JSON is not necessarily a practice type file. This runs
                # while the widget is being constructed, so an AttributeError
                # here stops the application from starting at all, and no amount
                # of restarting helps until the file is fixed.
                if not isinstance(raw, dict):
                    print(f"Ignoring {os.path.basename(path)}: it must contain a JSON "
                          f"object, not {type(raw).__name__}.")
                    return data

                # Filter comments
                data = {k: v for k, v in raw.items() if not k.startswith("__COMMENT__")}
            return data

        # Load both
        builtin_data = load_json(builtin_path)
        custom_data = load_json(custom_path)

        # Merge: Custom data overrides Built-in data
        merged_data = builtin_data.copy()
        merged_data.update(custom_data)

        return merged_data

    def merge_custom_practice_types(self) -> None:
        """
        Merge all practice types (built-in + custom) into settings and internal mappings.
        """
        all_types = self._valid_practice_types()
        if not all_types:
            return

        # 1. Update the 'Practice Type' dropdown options
        if (practice_type_setting := next(
            (item for item in self.settings_json if item.get("key") == "practice_type"), None
        )):
            # Ensure we don't duplicate options that are already there
            for name in all_types:
                if name not in practice_type_setting["options"]:
                    practice_type_setting["options"].append(name)

        # 2. Update internal mappings and practice_dances
        if not hasattr(self, "custom_practice_mapping"):
            self.custom_practice_mapping = {}
            
        for name, data in self._ordered_practice_types(all_types).items():
            # Update the list of dances for this practice type
            self.practice_dances[name] = data.get("dances", [])
            
            # Update the rules/adjustments mapping. The validated definition is
            # stored as-is: this was a positional tuple, which had grown to
            # eleven fields and one transposition away from a silent bug.
            self.custom_practice_mapping[name] = dict(data, dance_type=name)

    @staticmethod
    def _normalize_practice_type(name: str, data: typing.Any) -> typing.Optional[dict]:
        """Checks and repairs one practice type definition.

        See `practice_type_rules.normalize_practice_type`, which the editor uses
        too so that it cannot save something the player would have to repair.
        """
        return practice_type_rules.normalize_practice_type(name, data)

    def _valid_practice_types(self) -> dict:
        """Loads the practice types, keeping only the definitions that are usable.

        Names are taken from this rather than from the raw file, so a definition
        that had to be skipped cannot appear in the settings list as something
        selectable that then falls back to default behaviour.
        """
        valid = {}
        for name, data in self.load_custom_practice_types().items():
            if (clean := self._normalize_practice_type(name, data)) is not None:
                valid[name] = clean
        return valid

    @staticmethod
    def _ordered_practice_types(all_types: dict) -> dict:
        """Returns the practice types in the order they should be offered.

        File order otherwise, which puts every custom type after every built-in
        one -- so the types actually in use could not be kept together at the
        end of the list. An `order` of 0, which is the default, leaves a type
        where it was.
        """
        ordered = sorted(enumerate(all_types.items()),
                         key=lambda item: (item[1][1].get("order", 0), item[0]))
        return {name: data for _, (name, data) in ordered}

    def update_settings_options(self):
        """
        Dynamically updates the options in the settings JSON. 
        Crucial for ensuring the settings panel reflects changes after a Reload.
        """
        all_types = self._valid_practice_types()

        if (practice_type_setting := next(
            (item for item in self.settings_json if item.get("key") == "practice_type"), None
        )):
            # Start with the hardcoded base options
            options = [PlayerConstants.PRACTICE_TYPE_60_MIN, PlayerConstants.PRACTICE_TYPE_NC_60_MIN]
            
            # Append loaded types ONLY if they aren't already in the list.
            # This prevents "60min" from appearing twice (once as hardcoded base, once from JSON).
            for name in self._ordered_practice_types(all_types):
                if name not in options:
                    options.append(name)
            
            practice_type_setting["options"] = options

            # If current practice type is no longer valid (e.g. was deleted), reset it
            if self.practice_type not in practice_type_setting["options"]:
                self.practice_type = PlayerConstants.PRACTICE_TYPE_60_MIN

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

        self.playlist_button = Button(
            text=f"New Playlist\n({self.practice_type})",
            background_color=(0.2, 0.6, 0.8, 1),
            color=PlayerConstants.DEFAULT_BUTTON_TEXT_COLOR,
            halign="center",
            valign="middle"
        )
        # This callback updates the text_size whenever the button's size changes.
        def update_button_text_size(button, size):
            button.text_size = (size[0], None)
        # Bind the callback to the button's size property.
        self.playlist_button.bind(size=update_button_text_size)

        settings_button = Button(
            text="Music Settings",
            background_color=(0.2, 0.6, 0.8, 1),
            color=PlayerConstants.DEFAULT_BUTTON_TEXT_COLOR,
        )

        manage_practice_types_button = Button(
            text="Manage Practice Types",
            background_color=(0.2, 0.6, 0.8, 1),
            color=PlayerConstants.DEFAULT_BUTTON_TEXT_COLOR,
        )
        manage_practice_types_button.bind(on_press=self.switch_to_editor)


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
        control_buttons.add_widget(manage_practice_types_button)
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
        self.bind(practice_type=self.update_playlist_button_text)
        self.bind(practice_type=self.on_practice_type_change)
        self.bind(_playlist_generation_in_progress=self.on_playlist_generation_status_change)

    def on_practice_type_change(self, _instance, value: str):
        """
        When the practice_type property changes, update and save the app's config
        and apply the new practice type settings to the player.
        """
        app = App.get_running_app()
        # Update the config only if the value is different to avoid unnecessary writes
        if app.config.get('user', 'practice_type') != value:
            app.config.set('user', 'practice_type', value)
            app.config.write()

        # Apply the new practice type settings to the player
        self.set_practice_type(None, value)

    def switch_to_editor(self, _instance: typing.Any = None):
        """Switches the screen to the practice type editor."""
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
        if self.sound and self._sound_state() == "play":
            self.pause_sound()
        else:
            self.play_sound()

    def _load_sound(self, path: str) -> typing.Any:
        """Loads a sound file, returning None if the backend cannot handle it."""
        try:
            load_started = time.perf_counter()
            sound = SoundLoader.load(path)
            if self._is_first_load:
                # The first load pays for initialising the audio backend, which on
                # some machines costs more than everything else in startup.
                timing_mark("first SoundLoader.load (audio backend init)", load_started)
            return sound
        except Exception as error:  # pylint: disable=broad-except
            Logger.warning(f"MusicPlayer: could not load {path}: {error}")
            return None

    def _skip_unplayable_songs(self) -> list:
        """Advances past songs that are missing or cannot be loaded.

        Leaves `playlist_idx` on the first playable song with `self.sound` loaded,
        or past the end of the playlist if there is none.

        Returns:
            A list of (path, reason) for everything skipped.
        """
        skipped = []
        while self.playlist_idx < len(self.playlist):
            path = self.playlist[self.playlist_idx]['path']

            if not os.path.exists(path):
                skipped.append((path, "not found"))
            else:
                if self.sound is None:
                    self.sound = self._load_sound(path)
                if self.sound:
                    return skipped
                skipped.append((path, "could not be loaded"))

            # Move on without recursing back into play_sound.
            self.sound = None
            self._playing_position = 0
            self.playlist_idx += 1

        return skipped

    def _report_skipped_songs(self, skipped: list) -> None:
        """Reports skipped songs in a single popup rather than one popup each."""
        for path, reason in skipped:
            Logger.warning(f"MusicPlayer: skipped {path} ({reason})")

        shown = skipped[:5]
        lines = "\n".join(f"{os.path.basename(path)} - {reason}" for path, reason in shown)
        if len(skipped) > len(shown):
            lines += f"\n...and {len(skipped) - len(shown)} more"
        self.show_error_popup(
            f"Skipped {len(skipped)} unplayable "
            f"{'song' if len(skipped) == 1 else 'songs'}:\n{lines}")

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

        # Skip over anything unplayable in one pass. Recursing through
        # _advance_playlist instead would stack one modal popup per bad file,
        # which is what a missing codec looks like: every song in the playlist.
        self._playback_observed = False
        skipped = self._skip_unplayable_songs()
        if skipped:
            self._report_skipped_songs(skipped)
        if self.playlist_idx >= len(self.playlist):
            self.restart_playlist()
            return

        current_song = self.playlist[self.playlist_idx]
        current_song_path = current_song['path']
        self.music_file = current_song_path # Keep for reference if needed

        if self._sound_state() == "play":
            self._playing_position = self._sound_position()
        if self._sound_state() != "stop":
            self._sound_stop()

        self._sound_set_volume(self.volume)
        self._total_time = self._get_song_duration_str(current_song['duration'])
        self.song_title = self._get_song_label(current_song)[:120]  # Limit to 120 characters

        self._update_song_button_highlight()
        self._scroll_to_current_song()

        self._unschedule_progress_update()
        self._schedule_progress_update(current_song['duration'])

        self._playback_requested_at = time.perf_counter()
        self._apply_platform_specific_play()

        # Update the Play/Pause button icon to Pause
        self.play_pause_button.background_normal = self._get_icon_path(PlayerConstants.ICON_PAUSE)

    def pause_sound(self) -> None:
        """Pauses the currently playing sound.

        It stores the current playback position and stops the sound. The play/pause button
        icon is updated to show 'Play', indicating that playback can be resumed.
        """
        self._cancel_pending_play()
        self._playback_observed = False
        self._playback_requested_at = None
        if self.sound and self._sound_state() == "play":
            self._playing_position = self._sound_position()
            self._sound_stop()
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
        self._cancel_pending_play()
        self._playback_observed = False
        self._playback_requested_at = None
        self._reset_start_failures()
        if self.sound:
            self._sound_stop()
            self._sound_unload()
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
            self._sound_stop()
            self._playing_position = 0
            self._playback_observed = False
            self._playback_requested_at = time.perf_counter()
            if not self._start_sound(self.sound, 0):
                self._handle_failed_start()
                return
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
        self._sound_set_volume(volume_value)

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
            self._sound_seek(self._playing_position)

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

    @staticmethod
    def _safe_sound_call(description: str, function, *args, default=None):
        """Calls into the audio backend, containing any exception it raises.

        stop, unload, seek and get_pos can all raise from GStreamer or SDL. An
        exception escaping into Kivy's event loop is invisible on Windows, where
        the console is hidden, and can leave the player in a half-stopped state.

        Args:
            description: What was being attempted, for the log.
            function: The backend call.
            *args: Arguments for it.
            default: Returned if the call fails.

        Returns:
            The call's result, or `default` if it raised.
        """
        try:
            return function(*args)
        except Exception as error:  # pylint: disable=broad-except
            Logger.warning(f"MusicPlayer: {description} failed: {error}")
            return default

    def _sound_stop(self, sound=None) -> bool:
        """Stops a sound, tolerating a backend failure. True if it succeeded."""
        if (sound := sound or self.sound) is None:
            return False

        def stop():
            sound.stop()
            return True

        return bool(self._safe_sound_call("stopping playback", stop, default=False))

    def _sound_unload(self, sound=None) -> bool:
        """Unloads a sound, tolerating a backend failure. True if it succeeded."""
        if (sound := sound or self.sound) is None:
            return False

        def unload():
            sound.unload()
            return True

        return bool(self._safe_sound_call("unloading the song", unload, default=False))

    def _sound_state(self, sound=None, default: str = "stop") -> str:
        """Reads a sound's state, tolerating a backend failure.

        Normally a plain Kivy attribute rather than a backend call, so this is
        the least likely of these to raise; it is wrapped so that no interaction
        with a sound object is left unguarded.
        """
        if (sound := sound or self.sound) is None:
            return default
        return self._safe_sound_call(
            "reading the playback state", lambda: sound.state, default=default)

    def _sound_position(self) -> float:
        """Returns the current playback position, or the last known one."""
        if self.sound is None:
            return self._playing_position
        return self._safe_sound_call(
            "reading the playback position", self.sound.get_pos,
            default=self._playing_position)

    def _sound_volume(self, sound=None, default: float = 1.0) -> float:
        """Reads a sound's volume, tolerating a backend failure."""
        if (sound := sound or self.sound) is None:
            return default
        return self._safe_sound_call(
            "reading the volume", lambda: sound.volume, default=default)

    def _sound_set_volume(self, value: float, sound=None) -> None:
        """Sets a sound's volume, tolerating a backend failure."""
        if (sound := sound or self.sound) is None:
            return

        def assign():
            sound.volume = value

        self._safe_sound_call(f"setting the volume to {value:.2f}", assign)

    def _sound_seek(self, position: float) -> None:
        """Seeks, tolerating a backend failure."""
        if self.sound is not None:
            self._safe_sound_call(f"seeking to {position:.0f}s", self.sound.seek, position)

    def _cancel_pending_play(self) -> None:
        """Cancels a delayed play that has not fired yet.

        Called by anything that changes what should be playing, so that a start
        scheduled 100ms ago cannot arrive after the user has already stopped,
        paused, or chosen a different song.
        """
        if self._pending_play_event is not None:
            self._pending_play_event.cancel()
            self._pending_play_event = None

    def _start_sound(self, sound: typing.Any, position: float) -> bool:
        """Starts `sound`, seeking to `position` first if needed.

        Backend calls are isolated here: a failure inside GStreamer or SDL would
        otherwise escape into Kivy's event loop, where on Windows the traceback
        goes to a console that has been hidden.

        Returns:
            True if playback was started.
        """
        try:
            if position > 0:
                sound.seek(position)
            sound.play()
            if position > 0:
                # Some backends ignore a seek made before playback has begun.
                sound.seek(position)
            return True
        except Exception as error:  # pylint: disable=broad-except
            # Logged only: the caller decides whether this is one bad song or a
            # broken audio backend, and reports once rather than per song.
            Logger.warning(f"MusicPlayer: could not start playback: {error}")
            return False

    def _apply_platform_specific_play(self) -> None:
        """Applies platform-specific workarounds for sound playback.

        On Windows, there can be a delay before `sound.play()` takes effect, which can
        cause a subsequent `sound.seek()` to fail, so the play command is scheduled
        with a slight delay; other platforms play immediately.

        The delayed call captures the sound and playlist position it was scheduled
        for and does nothing if either has changed in the meantime. Without that, a
        stop during the delay starts a sound that has been unloaded, and choosing
        another song during the delay starts the wrong one.
        """
        sound = self.sound
        index = self.playlist_idx
        position = self._playing_position

        if platform.system() != "Windows":
            if not self._start_sound(sound, position):
                self._handle_failed_start()
            return

        def play_after_delay(_dt):
            self._pending_play_event = None
            if self.sound is not sound or self.playlist_idx != index:
                # Superseded while waiting; whatever replaced it starts itself.
                return
            if not self._start_sound(sound, position):
                self._handle_failed_start()

        # Use Kivy's Clock to wait 0.1s without blocking
        self._cancel_pending_play()
        self._pending_play_event = Clock.schedule_once(play_after_delay, 0.1)

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
        if self.sound is None:
            return

        if self._sound_state() != "play":
            if self._playback_observed:
                # The backend stopped on its own: the stream ended or failed to
                # decode. Nothing else advances the playlist, so without this the
                # player sits on a stopped song indefinitely.
                self._handle_unexpected_stop()
            elif (self._playback_requested_at is not None
                  and time.perf_counter() - self._playback_requested_at
                  > PlayerConstants.PLAYBACK_START_GRACE):
                # Asked to play, never played. A decoder that gives up inside the
                # first tick never sets _playback_observed, so the unexpected-stop
                # path above would never run for it.
                Logger.warning("MusicPlayer: playback never started; skipping this song")
                self._handle_failed_start()
            return

        self._playback_observed = True
        self._playback_requested_at = None
        self._reset_start_failures()
        self._playing_position = self._sound_position()
        self.progress_value = round(self._playing_position)
        current_time_str = self._secs_to_time_str(self._playing_position)
        self.progress_text = f"{current_time_str} / {self._total_time}"

        if not self.play_single_song:
            try:
                song_info = self.playlist[self.playlist_idx]
                current_dance = song_info.get('dance', 'unknown')

                # 'max_playtime' is stamped on each song when the playlist is built, so
                # a timed block can shorten individual songs. Fall back to the old
                # per-dance lookup for any song dict that predates that.
                if (max_playtime := song_info.get('max_playtime')) is None:
                    if current_dance in ('announce', 'cue'):
                        max_playtime = song_info.get('duration', self.song_max_playtime)
                    else:
                        max_playtime = self.current_dance_max_playtimes.get(
                            current_dance, self.song_max_playtime
                        )

                # The fade length belongs to the item rather than being a
                # global constant: a competition round clip fades for as long
                # as its segment asks, or stops dead when that is zero.
                fade = song_info.get('fade_seconds', PlayerConstants.FADE_TIME)
                margin = (PlayerConstants.CUE_END_MARGIN
                          if current_dance in ('announce', 'cue')
                          else PlayerConstants.END_MARGIN)
            except (IndexError, AttributeError):
                # Fallback if playlist structure is unexpected or index is out of bounds
                max_playtime = self.song_max_playtime
                fade = PlayerConstants.FADE_TIME
                margin = PlayerConstants.END_MARGIN

            self._handle_fade_out(max_playtime, fade)
            self._check_and_advance_song(max_playtime, fade, margin)

        elif ( # if play_single_song is True, stop at the end and set icon to play
                self._playing_position >= self.progress_max - 1
            ):
            self.stop_sound()
            self.play_pause_button.background_normal = self._get_icon_path(
                PlayerConstants.ICON_PLAY)

    def _reset_start_failures(self) -> None:
        """Forgets the run of failed starts.

        Called on a successful start and whenever the user intervenes, so that
        "consecutive" means what it says: stopping, or building a new playlist,
        breaks the run rather than carrying two failures into the next attempt.
        """
        self._consecutive_start_failures = 0
        self._failed_start_songs = ()

    def _handle_failed_start(self) -> None:
        """Recovers after a song fails to start playing.

        Leaving the Pause icon showing on a song that never started is the state
        the user has to work out for themselves; and since playback was never
        observed, the unexpected-stop path will not fire either. Move on, but
        stop after a few failures in a row rather than walking the whole playlist
        when the backend itself is broken.
        """
        self._playback_observed = False
        self._playback_requested_at = None
        self._consecutive_start_failures += 1

        if 0 <= self.playlist_idx < len(self.playlist):
            song = self.playlist[self.playlist_idx]
            self._failed_start_songs = tuple(self._failed_start_songs) + (
                os.path.basename(song.get('path', song.get('title', 'unknown'))),)

        self._sound_stop()
        self._sound_unload()
        self.sound = None
        self.play_pause_button.background_normal = self._get_icon_path(
            PlayerConstants.ICON_PLAY)

        if self._consecutive_start_failures >= PlayerConstants.MAX_CONSECUTIVE_START_FAILURES:
            Logger.warning("MusicPlayer: too many songs failed to start; stopping")
            names = "\n".join(self._failed_start_songs)
            self._reset_start_failures()
            self._unschedule_progress_update()
            self.show_error_popup(
                f"{PlayerConstants.MAX_CONSECUTIVE_START_FAILURES} songs in a row "
                f"failed to play:\n{names}\n\nPlayback has stopped. This usually "
                "means an audio problem rather than a problem with the songs.")
            return

        self._advance_playlist()

    def _handle_unexpected_stop(self) -> None:
        """Handles the backend stopping without being asked to.

        Reached when a song ends before the position reaches the end the metadata
        claimed -- a duration tag that is slightly too long, a VBR file the
        backend measures differently, or a decoding failure part way through.
        """
        Logger.info("MusicPlayer: playback stopped before the expected end; advancing")
        self._playback_observed = False

        if self.play_single_song:
            self.stop_sound()
            self.play_pause_button.background_normal = self._get_icon_path(
                PlayerConstants.ICON_PLAY)
            return

        self._advance_playlist()

    def _handle_fade_out(self, max_playtime: float,
                         fade: float = PlayerConstants.FADE_TIME) -> None:
        """Reduces the volume gradually when a song nears its max playtime.

        If the current playback position is beyond the `max_playtime`, this method calculates
        a fade factor and applies it to the sound's volume, creating a smooth fade-out effect
        over `fade` seconds.

        A `fade` of 0 means the item stops dead instead of fading. A competition
        round clip sets its own length here, and that time is taken out of the
        clip rather than added to it -- the round is timed against a stopwatch,
        so fading must not make the clip longer than it is meant to be.

        Args:
            max_playtime: The time in seconds at which the fade-out should begin.
            fade: Length of the fade in seconds; 0 for a hard cut.
        """
        if self._playing_position >= max_playtime and fade > 0:
            fade_factor = max(
                0,
                1
                + self._schedule_interval
                * (max_playtime - self._playing_position)
                / fade,
            )
            self._sound_set_volume(self._sound_volume() * fade_factor)

    def _check_and_advance_song(self, max_playtime: float,
                                fade: float = PlayerConstants.FADE_TIME,
                                margin: float = PlayerConstants.END_MARGIN) -> None:
        """Checks if the song should be advanced to the next one.

        A song is advanced if it reaches its natural end or if its playback time exceeds
        the `max_playtime` plus the fade-out duration.

        Args:
            max_playtime: The maximum configured playtime for the song.
            fade: Length of the fade in seconds; 0 for a hard cut.
            margin: How far before the natural end to advance. Cues are timing
                devices, so they use a tighter margin than music does.
        """
        if (
            self._playing_position >= self.progress_max - margin
            or self._playing_position >= max_playtime + fade
        ):
            self._advance_playlist()

    def _advance_playlist(self) -> None:
        """Advances to the next song in the playlist."""
        self._cancel_pending_play()
        self._playback_observed = False
        if self.sound:
            self._sound_unload()
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

    # Settings the background worker reads. They are frozen for the duration of a
    # generation because a practice type change rewrites all of them at once, and
    # a worker reading some old and some new values would build a playlist that
    # matches no practice type at all.
    GENERATION_SETTINGS = (
        "music_dir",
        "dances",
        "num_selections",
        "randomize_playlist",
        "practice_type",
        "play_all_songs",
        "play_single_song",
        "adjust_song_counts_for_playlist",
        "current_dance_adjustments",
        "current_dance_max_playtimes",
        "current_dance_minutes",
        "current_dance_intros",
        "current_segments",
        "song_max_playtime",
    )

    def _snapshot_generation_settings(self) -> dict:
        """Copies the settings a playlist generation depends on.

        Lists and dicts are copied so that comparing two snapshots compares
        values rather than the same object with itself.
        """
        snapshot = {}
        for name in self.GENERATION_SETTINGS:
            value = getattr(self, name)
            if isinstance(value, dict):
                snapshot[name] = dict(value)
            elif isinstance(value, list):
                snapshot[name] = list(value)
            else:
                snapshot[name] = value
        return snapshot

    def _setting(self, name: str) -> typing.Any:
        """Reads a generation setting.

        While a playlist is being built this returns the value frozen when the
        generation started; otherwise the live property. Code outside generation,
        and tests that set properties directly, are unaffected.

        Args:
            name: One of `GENERATION_SETTINGS`.

        Returns:
            The frozen value if a generation is in flight, else the current one.
        """
        config = self._generation_config
        if config is not None and name in config:
            return config[name]
        return getattr(self, name)

    def update_playlist(self, _instance: typing.Any = None, start_playback: bool = False) -> None:
        """Triggers the generation of a new playlist in a background thread.

        A request that arrives while a generation is already running is queued,
        so a settings change made during a slow generation still takes effect.
        A request whose settings match the generation already running is dropped
        instead: startup applies the practice type twice, and regenerating for
        that would double the work on exactly the slow machines this avoids.
        """
        if self._playlist_generation_in_progress:
            if (not start_playback
                    and self._snapshot_generation_settings() == self._generation_config):
                return  # Nothing changed; the playlist being built is still correct.
            self._regeneration_pending = True
            self._regeneration_start_playback = (
                self._regeneration_start_playback or start_playback)
            return

        self.stop_sound()
        self._playlist_generation_in_progress = True
        self._generation_config = self._snapshot_generation_settings()

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
        """Performs the blocking I/O of scanning files and reading metadata.

        Any failure here is caught and reported rather than killing the worker
        thread. An uncaught exception would leave the generating flag set, which
        disables the New Playlist button, play/pause and song selection, and on
        Windows the traceback goes to a hidden console -- the player would look
        simply frozen, with restarting the only way out.
        """
        try:
            self._build_playlist_in_background(
                directory, dances, num_selections, randomize, start_playback)
        except Exception as error:  # pylint: disable=broad-except
            Logger.exception(f"MusicPlayer: playlist generation failed: {error}")
            Clock.schedule_once(partial(self._abort_playlist_generation, error))

    def _abort_playlist_generation(self, error: Exception, _dt: float) -> None:
        """Recovers the UI after a failed generation, keeping the old playlist.

        Runs on the Kivy thread. The previous playlist is still intact because
        nothing is assigned until generation succeeds, so the practice can carry
        on with it.
        """
        self._playlist_generation_in_progress = False
        self._generation_config = None
        self._regeneration_pending = False
        self._regeneration_start_playback = False

        self._display_playlist_buttons()
        self.show_error_popup(
            f"Could not build the playlist:\n{type(error).__name__}: {error}\n\n"
            "The previous playlist is still loaded.")

    def _build_playlist_in_background(
        self, directory: str, dances: list, num_selections: int,
        randomize: bool, start_playback: bool
    ) -> None:
        """Builds the playlist. See `_generate_playlist_in_background`."""
        started = time.perf_counter()

        # A practice type with segments is a competition round sequence, built
        # from those instead of from the dances list.
        segments = self._setting('current_segments')
        if segments:
            new_playlist = self._build_segment_playlist(
                directory, segments, randomize)
            self._finish_background_generation(new_playlist, start_playback, started)
            return

        timed = bool(self._setting('current_dance_minutes'))
        if timed:
            print(f"Building timed playlist for '{self._setting('practice_type')}':")

        new_playlist = []
        for dance in dances:
            new_playlist.extend(self._get_songs_for_dance(
                directory, dance, num_selections, randomize))

        if timed:
            total = sum(
                min(song.get('duration', 0),
                    song.get('max_playtime', self._setting('song_max_playtime'))
                    + PlayerConstants.FADE_TIME)
                for song in new_playlist
            )
            print(f"  Total: {self._secs_to_time_str(total)}")

        self._finish_background_generation(new_playlist, start_playback, started)

    def _finish_background_generation(self, new_playlist: list, start_playback: bool,
                                      started: float) -> None:
        """Persists the metadata cache and hands the playlist to the UI thread.

        The cache is written here rather than per song so that one generation
        costs at most one file write, and nothing at all if every song was
        already cached.
        """
        if MusicPlayer._song_cache is not None:
            MusicPlayer._song_cache.save()
            timing_mark(f"playlist generated ({len(new_playlist)} items, "
                        f"song cache: {MusicPlayer._song_cache.stats()})", started)
        else:
            timing_mark(f"playlist generated ({len(new_playlist)} items)", started)

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
        timing_mark("playlist displayed")
        self.restart_playlist()
        self._playlist_generation_in_progress = False
        self._generation_config = None

        if self._regeneration_pending:
            # Settings changed while this playlist was being built; it is already
            # out of date, so rebuild it with the current settings.
            self._regeneration_pending = False
            queued_start_playback = self._regeneration_start_playback
            self._regeneration_start_playback = False
            self.update_playlist(start_playback=queued_start_playback or start_playback)
            return

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
                self._sound_set_volume(0, temp_sound)
                self._safe_sound_call("priming the audio backend", temp_sound.play)

                # Let it play for a tiny fraction of a second then stop and unload
                def silent_stop(_dt):
                    # Runs after the enclosing try has returned, so it needs its
                    # own guard; otherwise a cleanup failure reaches Kivy's loop.
                    stopped = self._sound_stop(temp_sound)
                    unloaded = self._sound_unload(temp_sound)
                    print("GStreamer priming successful." if stopped and unloaded
                          else "GStreamer priming finished, but cleanup failed.")

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

        # Cues (gaps, warnings) carry their own descriptive label.
        if song_info.get('dance') == 'cue':
            return song_info.get('cue_label', song_info.get('title', "Cue"))

        # Otherwise, build the full label for a regular song.
        title = song_info.get('title', "Title Unspecified")
        genre = song_info.get('genre', "Genre Unspecified")
        artist = song_info.get('artist', "Artist Unspecified")
        album = song_info.get('album', "Album Unspecified")

        label = f"{title} / {genre} / {artist} / {album}"

        # Round songs have no announcement before them, so the dance and the clip
        # length go on the button instead.
        if prefix := song_info.get('label_prefix'):
            return f"{prefix}  |  {label}"
        return label

    def _get_adjusted_song_count(self, dance: str, num_selections: int) -> int:
        """
        Adjusts the number of songs for a dance based on rules defined in the
        current practice type's 'dance_adjustments' dictionary.
        """
        adjustments = self._setting('current_dance_adjustments')
        if not self._setting('adjust_song_counts_for_playlist') or dance not in adjustments:
            return num_selections

        rule = adjustments[dance]

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

    def _get_song_cache(self) -> SongCache:
        """Returns the shared metadata cache, creating it on first use."""
        if MusicPlayer._song_cache is None:
            MusicPlayer._song_cache = SongCache(
                app_paths.user_path(PlayerConstants.SONG_CACHE_FILE))
        return MusicPlayer._song_cache

    def _read_tags(self, path: str) -> dict:
        """Returns a song's tag fields, from the cache when possible.

        This is the only place the player opens a music file for metadata, so it
        is the only place that needs to know a cache exists. A miss reads the file
        and stores the result; the cache is written once per playlist generation.

        Args:
            path: The full path to the music file.

        Returns:
            A dict with duration, title, artist, album and genre.

        Raises:
            TinyTagException, OSError: Propagated from the read, and handled by
                the caller exactly as before.
        """
        cache = self._get_song_cache()
        if (entry := cache.get(path)) is not None:
            return entry

        tag = TinyTag.get(path)
        fields = {
            'duration': tag.duration,
            'title': tag.title,
            'artist': tag.artist,
            'album': tag.album,
            'genre': tag.genre,
        }
        cache.put(path, fields)
        return fields

    def _create_song_info(self, path: str, dance: str) -> typing.Optional[dict]:
        """Reads metadata from a music file and returns it as a dictionary.

        The returned dictionary carries its own 'max_playtime', resolved here at
        playlist-generation time rather than being looked up per-dance during
        playback. Timed blocks then override it per song so that individual songs
        can be faded early to make a block fit its budget.

        Args:
            path: The full path to the music file.
            dance: The dance type associated with this song ('announce' for announcements).

        Returns:
            A dictionary containing song metadata, or None if reading fails.
        """
        try:
            tag = self._read_tags(path)

            # A file whose duration cannot be determined is usually not decodable
            # audio at all. Substituting a nominal duration puts it in the
            # playlist, and playing it can take the whole player down: the audio
            # backend loads such a file happily and then segfaults on play(),
            # which no amount of Python error handling can catch. Skip it.
            if not tag['duration']:
                Logger.warning(
                    f"MusicPlayer: no readable duration for {path}; skipping it. "
                    "The file is probably corrupt or not audio.")
                return None

            if dance in ('announce', 'cue'):
                duration = tag['duration']
                return {
                    'path': path,
                    'dance': dance,
                    'title': pathlib.Path(path).stem,
                    'artist': 'Announcement' if dance == 'announce' else 'Cue',
                    'album': '', 'genre': '',
                    'duration': duration,
                    # These play out in full; their duration is their max playtime,
                    # and they are never faded.
                    'max_playtime': duration,
                    'fade_seconds': 0,
                }
            return {
                'path': path,
                'dance': dance,
                'title': tag['title'] or pathlib.Path(path).stem,
                'artist': tag['artist'] or "Artist Unspecified",
                'album': tag['album'] or "Album Unspecified",
                'genre': tag['genre'] or "Genre Unspecified",
                'duration': tag['duration'],
                'max_playtime': self._cap_for_dance(dance),
                'fade_seconds': PlayerConstants.FADE_TIME,
            }
        except (TinyTagException, OSError) as e:
            print(f"Could not read metadata for {path}: {e}")
            return None

    def _intro_cue_label(self, dance: str, cue_name: str) -> typing.Optional[str]:
        """Playlist text for a silence cue standing in for an announcement.

        The dance is not being read out any more, so the row that replaces the
        announcement has to say which dance is about to start -- otherwise the
        playlist shows a run of identical separators and the only way to tell
        what is coming is to read the song titles.

        Returns:
            The label, or None to let the cue describe itself.
        """
        if (duration := self._cue_duration(cue_name)) is None:
            return None
        if duration < 60:
            return f"--- {dance} in {int(round(duration))} seconds ---"
        return f"--- {dance} in {self._secs_to_time_str(duration)} ---"

    def _cue_duration(self, cue_name: str) -> typing.Optional[float]:
        """How long a cue lasts, or None if it cannot be read."""
        if (path := self._get_cue_path(cue_name)) is None:
            return None
        if (info := self._create_song_info(path, 'cue')) is None:
            return None
        return float(info['duration'])

    def _intro_for_dance(self, dance: str) -> str:
        """What should precede this dance's block.

        Returns "announce" for the spoken announcement, "none" for nothing, or
        the name of a cue in cues/. A practice type says so with `dance_intros`,
        where a "default" key covers every dance not named individually. With no
        `dance_intros` at all the announcement is used, as it always has been.
        """
        intros = self._setting('current_dance_intros')
        return intros.get(dance, intros.get("default", practice_type_rules.INTRO_ANNOUNCE))

    def _block_intro(self, dance: str) -> typing.Optional[dict]:
        """Builds the item that introduces a dance's block, if there is one.

        A cue is used in place of the announcement rather than as well as it: a
        practice that has asked for silence does not want the name read out
        first. The item counts towards a timed block's budget either way, so
        swapping a nine second announcement for ten seconds of silence does not
        change how long the practice runs.

        Args:
            dance: The dance whose block is starting.

        Returns:
            A playlist item, or None if nothing should precede the block.
        """
        intro = self._intro_for_dance(dance)

        if intro == practice_type_rules.INTRO_NONE:
            return None

        if intro == practice_type_rules.INTRO_ANNOUNCE:
            if announce_path := self._get_announce_path(dance):
                return self._create_song_info(announce_path, 'announce')
            return None

        if (cue := self._get_cue_info(intro, self._intro_cue_label(dance, intro))) is None:
            Logger.warning(
                f"MusicPlayer: '{dance}' asks for the cue '{intro}', which is not in "
                f"{PlayerConstants.CUES_DIR}/. Starting the dance without it.")
        return cue

    def _get_announce_path(self, dance_name: str) -> typing.Optional[str]:
        """Constructs the path for a dance announcement audio file.

        It first looks for a specific announcement file (e.g., 'Waltz.ogg') and
        falls back to a generic one ('Generic.ogg') if the specific one is not found.

        Args:
            dance_name: The name of the dance.

        Returns:
            The file path to the announcement audio, or None if not found.
        """
        announce_dir = app_paths.app_path("announce")
        if specific := self._entry_ignoring_case(
                announce_dir, f"{dance_name}.ogg", want_dir=False):
            return specific
        return self._entry_ignoring_case(announce_dir, "Generic.ogg", want_dir=False)

    @staticmethod
    def _entry_ignoring_case(folder: str, name: str, want_dir: bool) -> typing.Optional[str]:
        """Finds `name` in `folder`, ignoring case, as Windows and macOS would.

        Windows and macOS match file and folder names without regard to case;
        Linux does not. A library built on one and used on the other would
        otherwise silently lose a whole dance -- the historical "QuickStep"
        spelling against a "Quickstep" folder being exactly that case.

        Args:
            folder: The folder to look in.
            name: The name being looked for, in whatever case.
            want_dir: True to match a directory, False to match a file.

        Returns:
            The full path as it exists on disk, or None if there is no match.
        """
        exact = os.path.join(folder, name)
        check = os.path.isdir if want_dir else os.path.isfile
        if check(exact):
            return exact

        try:
            entries = os.listdir(folder)
        except OSError:
            return None

        # casefold rather than lower: the stronger form for comparing names,
        # identical for the ASCII names in use and correct if that ever changes.
        wanted = name.casefold()
        matches = sorted(entry for entry in entries
                         if entry.casefold() == wanted and check(os.path.join(folder, entry)))
        if not matches:
            return None
        if len(matches) > 1:
            # Only reachable on a case-sensitive filesystem. Picking the first
            # keeps the choice stable rather than depending on directory order.
            Logger.warning(
                f"MusicPlayer: {folder} contains {len(matches)} entries named "
                f"'{name}' differing only in case: {', '.join(matches)}. "
                f"Using '{matches[0]}'.")
        return os.path.join(folder, matches[0])

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
        subdir = self._entry_ignoring_case(directory, dance, want_dir=True)
        if subdir is None:
            return []

        music_paths = []
        for root, _, files in os.walk(subdir):
            music_paths.extend(
                [os.path.join(root, file) for file in files if file.lower().endswith((
                    ".mp3", ".ogg", ".m4a", ".flac", ".wav"))])
        return music_paths

    def _get_history_path(self) -> str:
        """Returns the full path to the history JSON file."""
        return app_paths.user_path(PlayerConstants.HISTORY_FILE)

    def _load_play_history(self) -> dict:
        """Loads the play history from disk.

        Returns:
            dict: A dictionary mapping dance names to lists of played file paths.
        """
        history_path = self._get_history_path()
        if not os.path.exists(history_path):
            return {}

        try:
            with open(history_path, 'r', encoding='utf-8') as f:
                history = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"Warning: Could not load play history: {e}")
            return {}

        # Valid JSON is not necessarily a usable history. Anything else here
        # would raise inside the generation worker, where until recently the
        # failure left the whole player disabled.
        if not isinstance(history, dict):
            print("Warning: play history is not a JSON object; ignoring it.")
            return {}

        # The members matter as much as the shape: history entries go into a set,
        # so a dict or list among them raises "unhashable type" inside the
        # generation worker, and would do so on every attempt until the file was
        # deleted by hand.
        clean = {}
        for dance, paths in history.items():
            if not isinstance(dance, str) or not isinstance(paths, list):
                continue
            songs = [path for path in paths if isinstance(path, str)]
            if len(songs) != len(paths):
                print(f"Warning: play history for '{dance}' contained entries that "
                      "are not song paths; they were dropped.")
            clean[dance] = songs
        return clean

    def _save_play_history(self, history: dict) -> None:
        """Saves the updated play history to disk.

        Written to a temporary file and renamed, so a laptop losing power or
        being forced off mid-write cannot leave a truncated file behind.
        """
        path = self._get_history_path()
        try:
            temporary = f"{path}.tmp"
            with open(temporary, 'w', encoding='utf-8') as f:
                json.dump(history, f, indent=2)
            os.replace(temporary, path)
        except OSError as e:
            print(f"Warning: Could not save play history: {e}")

    def _select_songs_with_history(
        self,
        all_paths: list[str],
        dance: str,
        count: int,
        history: dict
    ) -> list[str]:
        """Selects songs ensuring no repeats until all have been played.

        If the pool of unplayed songs is exhausted, it resets the history
        for that dance type.
        """
        # 1. Identify what has already been played
        played_set = set(history.get(dance, []))

        # 2. Determine what is currently available (Set Subtraction)
        # We assume file paths are unique identifiers
        unplayed_paths = [p for p in all_paths if p not in played_set]

        selected_paths = []

        # 3. Check if we need to reshuffle
        if len(unplayed_paths) < count:
            # Case A: Not enough songs left.
            # Take what is left, reset history, and fill the rest.

            # Step 3a: Take all remaining unplayed songs
            selected_paths.extend(unplayed_paths)
            needed = count - len(selected_paths)

            # Step 3b: Reset history for this dance (reshuffle)
            # We explicitly clear it so 'all_paths' are now valid candidates again
            history[dance] = []

            # Step 3c: Fill the remaining slots from the full list
            # Note: We must exclude the songs we just picked in Step 3a to avoid
            # immediate repetition in the same playlist.
            available_for_refill = [p for p in all_paths if p not in selected_paths]

            # Handle edge case: Requesting more songs than exist in total directory
            needed = min(needed, len(available_for_refill))

            refill_selection = random.sample(available_for_refill, needed)
            selected_paths.extend(refill_selection)

        else:
            # Case B: Plenty of unplayed songs. Standard random sample.
            selected_paths = random.sample(unplayed_paths, count)

        # 4. Update History
        # We append the newly selected songs to the history
        current_history = history.get(dance, [])
        # If we just reset (Case A), current_history is empty, which is correct.
        # If we didn't reset (Case B), we append to existing.
        history[dance] = current_history + selected_paths

        return selected_paths

    # ------------------------------------------------------------------
    # Competition rounds
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_segments(raw: typing.Any) -> list:
        """Validates a practice type's `segments` list.

        See `practice_type_rules.validate_segments`.
        """
        return practice_type_rules.validate_segments(raw, print)

    def _get_cue_path(self, name: str) -> typing.Optional[str]:
        """Finds the audio file for a cue, trying .ogg then .mp3.

        Args:
            name: The cue name, e.g. "round_gap" or "gap_20".

        Returns:
            The path to the cue audio, or None if it is missing.
        """
        cue_dir = app_paths.app_path(PlayerConstants.CUES_DIR)
        for extension in (".ogg", ".mp3", ".wav", ".flac", ".m4a"):
            if found := self._entry_ignoring_case(
                    cue_dir, f"{name}{extension}", want_dir=False):
                return found
        return None

    def _get_cue_info(self, name: str, label: typing.Optional[str] = None) -> typing.Optional[dict]:
        """Builds a playlist item for a cue.

        Cues are ordinary audio files played to their natural length, so a gap or a
        warning tone needs no special handling during playback.

        Args:
            name: The cue name, e.g. "round_gap" or "gap_20".
            label: Text for the playlist button; a readable default is derived
                from the cue name when this is None.

        Returns:
            A playlist item, or None if the cue audio is missing.
        """
        path = self._get_cue_path(name)
        if path is None:
            print(f"Warning: cue '{name}' not found in {PlayerConstants.CUES_DIR}/. "
                  "Run cues/make_cues.sh to generate it. Skipping it.")
            return None

        info = self._create_song_info(path, 'cue')
        if info is None:
            return None

        info['cue_label'] = label or self._default_cue_label(name, info['duration'])
        return info

    @staticmethod
    def _default_cue_label(name: str, duration: float) -> str:
        """A readable playlist label for a cue that was not given one."""
        if name.startswith("gap_"):
            return f"--- {int(round(duration))} second gap ---"
        if name == PlayerConstants.ROUND_GAP_CUE:
            return "--- break between rounds, warning tone before the music ---"
        return f"--- {name.replace('_', ' ')} ---"

    def _pick_songs(self, dance: str, all_music_paths: list, wanted: int,
                    min_seconds: typing.Optional[float], randomize: bool) -> list:
        """Chooses songs for one dance, passing over ones that are too short.

        Used both for a fixed number of selections, where `min_seconds` is
        `MIN_SONG_LENGTH_SECONDS`, and for a competition round, where it is the
        clip length -- a round is timed against a stopwatch, so a track shorter
        than the clip leaves the round short and every following heat drifts.

        Candidates are considered in history-aware order and the first ones long
        enough are taken; only if there are too few does it fall back to the
        longest of the short ones, with a warning.

        Metadata is read lazily as candidates are considered, so a folder of
        normal-length songs costs no more reads than picking blind would.

        Args:
            dance: The dance being picked for.
            all_music_paths: Every music file available for the dance.
            wanted: How many songs are needed.
            min_seconds: Shortest acceptable song, or None to accept any.
            randomize: If True, draw history-aware at random; else sorted order.

        Returns:
            A list of song dictionaries.
        """
        history = self._load_play_history() if randomize else {}
        candidates = (self._draw_candidates(all_music_paths, dance, history)
                      if randomize else sorted(all_music_paths))

        chosen: list[dict] = []
        too_short: list[dict] = []
        for path in candidates:
            if (song_info := self._create_song_info(path, dance)) is None:
                continue
            if not min_seconds or song_info['duration'] >= min_seconds:
                chosen.append(song_info)
                if len(chosen) == wanted:
                    break
            else:
                too_short.append(song_info)

        if len(chosen) < wanted and too_short:
            # Not enough full-length tracks: use the longest of what is left.
            too_short.sort(key=lambda info: -info['duration'])
            shortfall = wanted - len(chosen)
            chosen.extend(too_short[:shortfall])
            print(f"    Warning: '{dance}' has too few songs of at least "
                  f"{self._secs_to_time_str(min_seconds)}; using the "
                  f"{shortfall} longest of the shorter ones.")

        if randomize and chosen:
            self._commit_history(history, dance, [info['path'] for info in chosen],
                                 all_music_paths)
            self._save_play_history(history)

        return chosen

    def _get_round_songs(self, directory: str, segment: dict, randomize: bool) -> list:
        """Builds one competition round.

        Each dance is played `count` times at `clip_seconds`, ending with the
        segment's `fade_seconds` (or stopping dead when that is zero), separated
        by a short gap. There are no spoken announcements, so the dance name and
        clip length go on the playlist button instead.

        Args:
            directory: The root music directory.
            segment: A validated round segment.
            randomize: If True, songs are chosen history-aware at random.

        Returns:
            A list of playlist items for the round.
        """
        items: list[dict] = []
        clip_seconds = segment["clip_seconds"]
        gap_seconds = segment["gap_seconds"]
        fade_seconds = segment.get("fade_seconds", 0)

        # Build the list of picks first so the trailing gap can be left off the end.
        picks: list[tuple[str, dict]] = []
        for dance in segment["round"]:
            all_music_paths = self._collect_music_files(directory, dance)
            if not all_music_paths:
                print(f"Warning: no music found for '{dance}'. Skipping it in this round.")
                continue

            wanted = min(segment["count"], len(all_music_paths))
            if wanted < segment["count"]:
                print(f"Warning: '{dance}' has only {len(all_music_paths)} songs; "
                      f"the round asked for {segment['count']}.")

            picks.extend(
                (dance, song_info) for song_info in self._pick_songs(
                    dance, all_music_paths, wanted, clip_seconds, randomize))

        for position, (dance, song_info) in enumerate(picks):
            if segment["announce"] and (announce_path := self._get_announce_path(dance)):
                if announce_info := self._create_song_info(announce_path, 'announce'):
                    items.append(announce_info)

            if clip_seconds:
                # The fade is taken out of the clip, not added to it: the song
                # plays at full volume until clip_seconds - fade_seconds, then
                # fades down until clip_seconds, when playback stops. A round
                # therefore keeps the length it was timed for. With no fade this
                # is the original hard cut.
                song_info['max_playtime'] = clip_seconds - fade_seconds
                song_info['fade_seconds'] = fade_seconds
                song_info['label_prefix'] = (
                    f"{dance} {self._secs_to_time_str(clip_seconds)}")
            else:
                song_info['label_prefix'] = dance

            items.append(song_info)

            # Gaps separate dances; there is no gap after the last one, because the
            # break between rounds follows immediately.
            if gap_seconds and position < len(picks) - 1:
                if gap_info := self._get_cue_info(f"gap_{gap_seconds}"):
                    items.append(gap_info)

        return items

    def _build_segment_playlist(self, directory: str, segments: list, randomize: bool) -> list:
        """Builds a whole playlist from a practice type's `segments`.

        Args:
            directory: The root music directory.
            segments: Validated segments.
            randomize: If True, songs are chosen history-aware at random.

        Returns:
            The complete playlist.
        """
        print(f"Building rounds playlist for '{self._setting('practice_type')}':")
        playlist: list[dict] = []

        for segment in segments:
            if cue := segment.get("cue"):
                if cue_info := self._get_cue_info(cue, segment.get("label")):
                    playlist.append(cue_info)
                    print(f"  {cue}: {self._secs_to_time_str(cue_info['duration'])}")
                continue

            round_items = self._get_round_songs(directory, segment, randomize)
            playlist.extend(round_items)

            songs = [item for item in round_items if item['dance'] not in ('cue', 'announce')]
            print(f"  {segment.get('label') or 'round'}: {len(songs)} dances, "
                  f"{self._secs_to_time_str(self._playlist_length(round_items))}")

        print(f"  Total: {self._secs_to_time_str(self._playlist_length(playlist))}")
        return playlist

    @staticmethod
    def _playlist_length(items: list) -> float:
        """Total playing time of a list of playlist items, in seconds."""
        return sum(
            min(item.get('duration', 0),
                item.get('max_playtime', 0) + item.get('fade_seconds', 0))
            for item in items
        )

    # ------------------------------------------------------------------
    # Timed practice blocks
    # ------------------------------------------------------------------

    def _cap_for_dance(self, dance: str) -> float:
        """Returns the maximum playtime in seconds for a single song of `dance`.

        This is the per-dance override if one is configured, otherwise the global
        default. It is an anomaly guard: it stops one unusually long track from
        dominating a block, and it is applied before any block budgeting so that a
        six-minute track is accounted for at its capped length, not its real one.
        """
        return float(self._setting('current_dance_max_playtimes').get(
            dance, self._setting('song_max_playtime')))

    @staticmethod
    def _effective_length(duration: float, cap: float) -> float:
        """How much playlist time a song occupies when played normally.

        A song shorter than the cap plays out in full. A longer one is cut off at
        the cap and then fades, so it occupies `cap + FADE_TIME`.
        """
        return min(float(duration), cap + PlayerConstants.FADE_TIME)

    @staticmethod
    def _validate_dance_minutes(raw: typing.Any, dances: list) -> dict:
        """Validates a practice type's `dance_minutes` mapping.

        Bad entries are dropped with a warning rather than raising, so a typo in a
        JSON file degrades to the old count-based behaviour for that dance instead
        of breaking playlist generation.

        Args:
            raw: The value of the practice type's "dance_minutes" key.
            dances: The dances actually included in the practice type.

        Returns:
            A dict of {dance: minutes} containing only valid, positive entries.
        """
        if not raw:
            return {}
        if not isinstance(raw, dict):
            print(f"Warning: 'dance_minutes' must be a JSON object, got {type(raw).__name__}. "
                  "Ignoring it.")
            return {}

        validated = {}
        for dance, value in raw.items():
            if dance not in dances:
                print(f"Warning: 'dance_minutes' lists '{dance}', which is not in this "
                      "practice type's dances. Ignoring it.")
                continue
            minutes = practice_type_rules.strict_number(
                value, f"'dance_minutes' value for '{dance}'")
            if minutes is None:
                print(f"Warning: 'dance_minutes' value for '{dance}' is not an "
                      f"ordinary number ({value!r}). Ignoring it.")
                continue
            if minutes <= 0:
                print(f"Warning: 'dance_minutes' value for '{dance}' must be positive "
                      f"({value!r}). Ignoring it.")
                continue
            validated[dance] = minutes
        return validated

    def _draw_candidates(self, all_paths: list[str], dance: str, history: dict) -> list[str]:
        """Returns paths in the order they should be considered for a timed block.

        Unplayed songs come first (shuffled), then previously played ones (also
        shuffled) for the case where the block is long enough to exhaust the pool.

        Unlike `_select_songs_with_history`, this mutates nothing: a timed block
        does not know how many songs it needs until the running total crosses the
        budget, so history must not be written until the block is settled.
        Otherwise songs that were considered but never played would be burned.
        """
        played = set(history.get(dance, []))
        unplayed = [p for p in all_paths if p not in played]
        replayed = [p for p in all_paths if p in played]
        random.shuffle(unplayed)
        random.shuffle(replayed)
        return unplayed + replayed

    @staticmethod
    def _commit_history(history: dict, dance: str, used_paths: list[str],
                        all_paths: typing.Optional[list[str]] = None) -> None:
        """Records the songs a block actually used.

        The cycle restarts only when the pool is genuinely exhausted, mirroring the
        reshuffle in `_select_songs_with_history`. A replay while unplayed songs
        remain -- which happens when the ones left are all too short -- keeps the
        cycle intact, so one unavoidable repeat does not discard the record of
        everything else already played.

        Args:
            history: The play history, modified in place.
            dance: The dance these songs belong to.
            used_paths: The songs actually played, in order.
            all_paths: Every song available for the dance. Without it, any replay
                is treated as exhaustion.
        """
        if not used_paths:
            return

        played = history.get(dance, [])
        played_set = set(played)
        if not any(path in played_set for path in used_paths):
            history[dance] = played + list(used_paths)
            return

        # Something was replayed. Is anything still unplayed?
        used_set = set(used_paths)
        unplayed_remain = any(
            path not in played_set and path not in used_set for path in (all_paths or []))

        if unplayed_remain:
            # Keep the cycle; just record the new songs, without duplicating entries.
            history[dance] = list(dict.fromkeys(played + list(used_paths)))
        else:
            history[dance] = list(used_paths)

    @staticmethod
    def _apply_uniform_trim(lengths: list[float], total_trim: float,
                            min_play: float) -> list[float]:
        """Spreads `total_trim` seconds evenly across `lengths`.

        Every song gives up the same number of seconds, so songs keep their
        relative lengths -- a block is not a run of identical clips. A song is
        never taken below `min_play`; whatever it cannot absorb is redistributed
        over the songs that still have headroom.

        Args:
            lengths: Planned play length of each song, in seconds.
            total_trim: Total seconds that must come out of the block.
            min_play: Floor below which no song may be trimmed.

        Returns:
            The trimmed lengths. If the block cannot absorb the whole trim, the
            result sums to more than the budget and the caller reports it.
        """
        planned = [float(length) for length in lengths]
        remaining = float(total_trim)
        active = [i for i, length in enumerate(planned) if length > min_play]

        while remaining > 0.5 and active:
            share = remaining / len(active)
            still_active = []
            for i in active:
                take = min(share, planned[i] - min_play)
                planned[i] -= take
                remaining -= take
                if planned[i] > min_play + 0.5:
                    still_active.append(i)
            active = still_active

        return planned

    @staticmethod
    def _plan_timed_block(lengths: list[float], budget: float,
                          max_trim: float, min_play: float) -> list[float]:
        """Decides how long each song in a timed block should play.

        `lengths` are the effective (cap-limited) lengths of the songs drawn for
        the block, in play order, drawn until their total reached `budget`. The
        overshoot is shared evenly across all of them so the block ends exactly on
        budget. If that share would be a bigger cut than `max_trim`, the last song
        is dropped and the block runs short instead.

        Returns:
            Planned play lengths for the songs that are kept -- always a prefix of
            `lengths`, possibly empty.
        """
        kept = [float(length) for length in lengths]

        while kept:
            overshoot = sum(kept) - budget
            if overshoot <= 0:
                # Songs ran out before the budget was met: play them untrimmed.
                return kept
            if overshoot / len(kept) <= max_trim or len(kept) == 1:
                return MusicPlayer._apply_uniform_trim(kept, overshoot, min_play)
            kept.pop()

        return []

    def _get_timed_songs_for_dance(
        self, dance: str, all_music_paths: list[str], minutes: float, randomize: bool
    ) -> list:
        """Builds a block of songs that fills `minutes` minutes of playing time.

        Any announcement or cue before the dance counts against the budget, so
        a 13 minute Waltz block remains 13 minutes including its introduction.

        Args:
            dance: The dance for this block.
            all_music_paths: Every music file available for the dance.
            minutes: The block's budget in minutes.
            randomize: If True, songs are drawn history-aware at random; if False,
                they are taken in sorted order.

        Returns:
            A list of song dictionaries, optional introduction first, each carrying the
            'max_playtime' that makes the block land on its budget.
        """
        budget = float(minutes) * 60.0

        announce_info = self._block_intro(dance)
        if announce_info is not None:
            budget -= float(announce_info['duration'])

        if budget <= 0:
            print(f"Warning: '{dance}' block of {minutes:g} min is too short to hold "
                  "its announcement. Playing the announcement only.")
            return [announce_info] if announce_info else []

        cap = self._cap_for_dance(dance)

        history = self._load_play_history() if randomize else {}
        candidates = (self._draw_candidates(all_music_paths, dance, history)
                      if randomize else sorted(all_music_paths))

        # Draw songs one at a time, reading metadata only for the ones considered,
        # until the running total reaches the budget.
        drawn: list[dict] = []
        lengths: list[float] = []
        total = 0.0
        for path in candidates:
            if (song_info := self._create_song_info(path, dance)) is None:
                continue
            length = self._effective_length(song_info['duration'], cap)
            drawn.append(song_info)
            lengths.append(length)
            total += length
            if total >= budget:
                break

        planned = self._plan_timed_block(
            lengths, budget,
            PlayerConstants.MAX_TRIM_SECONDS,
            PlayerConstants.MIN_SONG_PLAY_SECONDS,
        )
        kept = drawn[:len(planned)]

        for song_info, full_length, play_length in zip(kept, lengths, planned):
            if play_length < full_length - 0.5:
                # Trimmed: fade so that playback ends exactly at play_length.
                song_info['max_playtime'] = max(play_length - PlayerConstants.FADE_TIME, 1.0)
            else:
                # Untrimmed: leave the normal cap so a short song is not faded early.
                song_info['max_playtime'] = cap

        if randomize and kept:
            self._commit_history(history, dance, [info['path'] for info in kept])
            self._save_play_history(history)

        # A shorter plan than the songs drawn means the planner dropped one
        # rather than trim the block too hard; anything else means the folder
        # ran out.
        self._report_timed_block(dance, minutes, announce_info, planned,
                                 dropped=len(planned) < len(lengths))

        return ([announce_info] if announce_info else []) + kept

    def _report_timed_block(self, dance: str, minutes: float,
                            intro_info: typing.Optional[dict],
                            planned: list[float], dropped: bool = False) -> None:
        """Prints what a timed block came out to, and warns if it fell short.

        A block that quietly runs short is the failure a DJ would only notice
        mid-practice, so it is called out on the console at generation time.

        Args:
            dance: The dance this block is for.
            minutes: The budget it was given.
            intro_info: The announcement or cue before the block, if any.
            planned: Play length of each song kept.
            dropped: True if the planner left a song out because trimming the
                block to fit would have cut more than MAX_TRIM_SECONDS from
                every song. That is a different problem from running out of
                music, and pointing at the wrong one sends the DJ looking for
                songs in a folder that has plenty.
        """
        target = float(minutes) * 60.0
        intro_len = float(intro_info['duration']) if intro_info else 0.0
        actual = intro_len + sum(planned)
        shortfall = target - actual

        if intro_info is None:
            intro = "no intro"
        elif intro_info['dance'] == 'announce':
            intro = f"announcement {intro_len:.0f}s"
        else:
            intro = f"{intro_info['title']} {intro_len:.0f}s"

        print(f"  {dance}: {len(planned)} songs, "
              f"{self._secs_to_time_str(actual)} of {self._secs_to_time_str(target)} "
              f"({intro})")
        if shortfall > 1.0:
            if dropped:
                print(f"    Warning: {dance} block is {shortfall:.0f}s short. One more "
                      f"song would have meant trimming more than "
                      f"{PlayerConstants.MAX_TRIM_SECONDS}s from every song in the "
                      "block, so it was left out.")
            else:
                print(f"    Warning: {dance} block is {shortfall:.0f}s short. Not "
                      "enough music in the folder, or the songs are unusually short.")
        elif shortfall < -1.0:
            print(f"    Warning: {dance} block is {-shortfall:.0f}s over. "
                  "Songs could not be trimmed further without going below "
                  f"{PlayerConstants.MIN_SONG_PLAY_SECONDS}s.")

    def _get_songs_for_dance(
        self, directory: str, dance: str, num_selections: int, randomize: bool
    ) -> list:
        """Retrieves a list of song dictionaries for a specific dance.

        This method coordinates collecting music files, applying selection logic,
        reading metadata, and prepending the configured block introduction.

        If the active practice type gives this dance a `dance_minutes` budget, the
        block is filled by playing time instead of by song count.

        Args:
            directory: The root music directory.
            dance: The name of the dance (and its subfolder).
            num_selections: The number of songs to retrieve (ignored if play_all_songs is True).
            randomize: If True, songs are shuffled; otherwise, they are sorted alphabetically.

        Returns:
            A list of song dictionaries with pre-fetched metadata, potentially
            including an optional announcement or cue at the beginning.
        """
        all_music_paths = self._collect_music_files(directory, dance)
        if not all_music_paths:
            return []

        # Timed block: fill by playing time rather than by song count. play_all_songs
        # and play_single_song are deliberate "play the whole thing" modes, so a
        # budget does not apply to them.
        minutes = self._setting('current_dance_minutes').get(dance)
        if minutes and not self._setting('play_all_songs') \
                and not self._setting('play_single_song'):
            return self._get_timed_songs_for_dance(dance, all_music_paths, minutes, randomize)

        if self._setting('play_all_songs'):
            # "Play everything" means everything: no minimum length is applied,
            # and history is only used to order what is already a full sweep.
            num_to_sample = len(all_music_paths)
            if randomize:
                history = self._load_play_history()
                sampled_paths = self._select_songs_with_history(
                    all_music_paths, dance, num_to_sample, history
                )
                self._save_play_history(history)
            else:
                sampled_paths = sorted(all_music_paths)[:num_to_sample]

            playlist = [
                song_info for path in sampled_paths
                if (song_info := self._create_song_info(path, dance)) is not None
            ]
        else:
            adjusted_num_selections = self._get_adjusted_song_count(dance, num_selections)
            if adjusted_num_selections == 0:
                return []
            num_to_sample = min(adjusted_num_selections, len(all_music_paths))

            # A fixed number of selections sets the length of the practice, so a
            # very short track just makes the practice end early. Pass those over.
            playlist = self._pick_songs(
                dance, all_music_paths, num_to_sample,
                PlayerConstants.MIN_SONG_LENGTH_SECONDS, randomize)

        if (intro := self._block_intro(dance)) is not None:
            playlist.insert(0, intro)

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
        builtin = {
            "num_selections": 2, "adjust_song_counts": True,
            "dance_adjustments": default_adjustments,
            "dance_max_playtimes": {"VienneseWaltz": 150},
        }
        mapping = {
            PlayerConstants.PRACTICE_TYPE_60_MIN: dict(builtin, dance_type="default"),
            PlayerConstants.PRACTICE_TYPE_NC_60_MIN: dict(builtin, dance_type="newcomer"),
        }

        mapping |= getattr(self, "custom_practice_mapping", {})
        definition = mapping.get(text, {"dance_type": "default", "auto_update": True})

        adj_counts = definition.get("adjust_song_counts", False)
        adj_dict = definition.get("dance_adjustments", {})
        if adj_counts and not adj_dict:
            adj_dict = default_adjustments

        self.dances = self.get_dances(definition.get("dance_type", "default"))
        self.num_selections = definition.get("num_selections", 2)
        self.play_all_songs = definition.get("play_all_songs", False)
        self.auto_update_restart_playlist = definition.get("auto_update", False)
        self.play_single_song = definition.get("play_single_song", False)
        self.randomize_playlist = definition.get("randomize_playlist", True)
        self.adjust_song_counts_for_playlist = adj_counts
        self.current_dance_adjustments = adj_dict
        self.current_dance_max_playtimes = definition.get("dance_max_playtimes", {})
        self.current_dance_minutes = self._validate_dance_minutes(
            definition.get("dance_minutes", {}), self.dances)
        self.current_segments = self._validate_segments(definition.get("segments", []))
        self.current_dance_intros = practice_type_rules.validate_dance_intros(
            definition.get("dance_intros", {}), print)

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
            self.playlist_button.text = f"New Playlist\n({practice_type_value})"
            # Manually trigger a layout update if the button's size might change
            self.playlist_button.text_size = (self.playlist_button.width, None)


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

    def get_application_config(self, **kwargs) -> str:
        """Returns the path of music.ini.

        Kivy defaults to writing it beside the main script, which fails for an
        installation the user cannot write to. Follows the same rule as every
        other file the player writes, so source deployments are unaffected.
        """
        return app_paths.user_path(f"{self.name}.ini")

    def build(self) -> ScreenManager:
        """Creates and returns the root widget of the application."""
        self.settings_cls = MusicSettings

        # Create the screen manager
        self.manager = RootManager()

        # Create the MusicPlayer screen
        self.player_widget = MusicPlayer()
        player_screen = Screen(name='player')
        player_screen.add_widget(self.player_widget)
        self.manager.add_widget(player_screen)

        # Create and add the editor screen
        self.editor_screen = PracticeTypeEditorScreen(name='editor')
        self.manager.add_widget(self.editor_screen)

        timing_mark("app.build() complete")
        return self.manager

    def open_settings(self, *largs, **kwargs):
        """
        Force the settings panel to be destroyed and rebuilt every time it's opened.
        This ensures that any changes to the available options (like renamed
        practice types) are reflected immediately.
        """
        self.destroy_settings()
        super().open_settings(*largs, **kwargs)

    def on_start(self) -> None:
        """Called once the Kivy application event loop is running.

        This method loads settings from the configuration file, applies them to the root
        widget, and performs any platform-specific startup tasks, like the Windows
        GStreamer priming workaround.
        """
        self._load_config_settings()
        self.player_widget.set_practice_type(None, self.player_widget.practice_type)
        timing_mark("on_start complete (playlist generating in background)")

        if sys.platform == "win32":
            Clock.schedule_once(self._windows_startup_fixes, 1)

    def _config_number(self, section: str, key: str, kind: type, default):
        """Reads a numeric setting, repairing the file if the value is unusable.

        ConfigParser's `fallback` only covers a missing option, not a malformed
        one: `getint` on "abc" raises even with a fallback given. That exception
        would escape `on_start` and abort startup every time, which is the one
        failure here that restarting the player cannot clear.

        Args:
            section: Config section name.
            key: Option name.
            kind: `int` or `float`.
            default: Value to use, and to write back, if the stored one is bad.

        Returns:
            The stored value, or `default` if it could not be read.
        """
        try:
            return kind(self.config.get(section, key, fallback=default))
        except (ValueError, TypeError):
            Logger.warning(
                f"MusicPlayer: {key} in the settings file is not a valid "
                f"{kind.__name__}; using {default}.")
            try:
                self.config.set(section, key, default)
                self.config.write()
            except (OSError, KeyError) as error:
                Logger.warning(f"MusicPlayer: could not repair {key}: {error}")
            return default

    def _load_config_settings(self) -> None:
        """Loads settings from the .ini config file and applies them to the player.

        It reads values for volume, music directory, max playtime, and practice type
        from the 'user' section of the config file. It uses sensible defaults if a
        setting is missing and validates the loaded practice type against the available options.
        """
        user_section = "user"
        if self.config.has_section(user_section):
            self.player_widget.volume = self._config_number(
                user_section, "volume", float, 0.7)
            self.player_widget.music_dir = self.config.get(
                user_section, "music_dir", fallback=""
            )
            self.player_widget.song_max_playtime = self._config_number(
                user_section, "song_max_playtime", int, 210)

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
                user_section, "practice_type", fallback=PlayerConstants.PRACTICE_TYPE_60_MIN
            )

            if loaded_practice_type not in practice_type_options:
                loaded_practice_type = PlayerConstants.PRACTICE_TYPE_60_MIN
                self.config.set(user_section, "practice_type", loaded_practice_type)
                self.config.write()
            self.player_widget.practice_type = loaded_practice_type

    def _windows_startup_fixes(self, _dt: float) -> None:
        """Applies startup fixes specific to the Windows platform."""
        self._hide_console_window()

    def _hide_console_window(self) -> None:
        """Hides the command-line console window that may appear on Windows."""
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
                "practice_type": PlayerConstants.PRACTICE_TYPE_60_MIN,
            },
        )

    def build_settings(self, settings: typing.Any) -> None:
        """Constructs the settings panel for the application.

        It creates a JSON panel using the structure defined in `MusicPlayer.settings_json`.

        Args:
            settings: The Kivy settings object to which the panel is added.
        """
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
                    player.set_practice_type(None, value)

                case _:
                    # Optional: handle any keys that don't match the cases above
                    print(f"Warning: Unrecognized key '{key}'")

if __name__ == "__main__":
    MusicApp().run()
