# DancePracticeMusicPlayer

**Kivy-based desktop application for managing and playing custom dance practice playlists with spoken announcements.**

---

## Screenshots

Main GUI (Linux/macOS/Windows):

![Music_Player_20250706](https://github.com/user-attachments/assets/6b307479-a60a-49b0-8b89-8cfe79a04f2e)

Settings panel:

![Music_Settings-20250706](https://github.com/user-attachments/assets/06be1dd6-fee1-41bb-b971-c81317f595f9)

---

## Overview

**DancePracticeMusicPlayer** is a [Kivy](https://kivy.org) application written in Python that creates a music player with features useful for dance practices that use a predetermined sequence of dance types. It automatically generates a playlist with a spoken announcement of each dance type before those dance selections are played. The dance selections are chosen randomly from the available selections for each dance type so that each practice has a different playlist. The application also supports `customizable practice types` via a separate configuration file, allowing for flexible and tailored practice sessions.

The application is designed to play music files (MP3, WAV, OGG, M4A, FLAC, WAV) from a selected directory. It has a user interface with buttons to play, pause, stop, and restart the music. The application also allows users to select a music directory, adjust the volume, and choose a practice length (e.g., 60 minutes, 90 minutes, etc.).

---

## Features

- **Customizable Playlists:** Generates randomized playlists based on predefined or custom dance types and lengths
- **Spoken Dance Announcements:** Automatically announces the dance type before each selection begins
- **Intuitive UI:** Play, pause, stop, restart controls, and a clickable, scrollable playlist
- **Real-time Progress:** Displays current song title, artist, album, genre, and playback progress with seeking capability
- **Configurable Settings:** Adjust volume, set music directory, and define maximum song playtime via an in-app settings panel
- **Custom Practice Types:** Easily define new practice routines, dance sequences, and song selection rules using `custom_practice_types.json`, including options for randomize_playlist, adjust_song_counts, and specific dance_adjustments.
- **Platform Compatibility:** Designed to run on Linux, macOS, and Windows.

---

## Installation

This application requires Python 3 and Kivy. It's highly recommended to use a virtual environment (as done in the scripts below) to manage dependencies.

### 1. Clone the Repository

- **Windows:** Download Git for Windows from [Git](https://git-scm.com/)
- **Linux/macOS:** Use your system's package manager to install Git.

Then, clone the repository:

```bash
git clone https://github.com/rrusk/DancePracticeMusicPlayer.git
cd DancePracticeMusicPlayer
```

### 2. Set Up Python Environment

Make sure you have Python and `pip` installed.
`Important:` For Windows users, it is recommended to use **Python 3.12.x** due to potential compatibility issues with Kivy on Python 3.13.x.

#### For Linux / macOS

```bash
python3 -m pip install --upgrade pip setuptools virtualenv
python3 -m venv kivy_venv
source kivy_venv/bin/activate
python -m pip install "kivy[base,media]"==2.3.0 kivy_examples==2.3.0
python -m pip install tinytag
```

#### For Windows

```bash
python -m pip install --upgrade pip setuptools virtualenv
python -m venv kivy_venv
kivy_venv\Scripts\activate
python -m pip install "kivy[base,media]" kivy_examples
python -m pip install tinytag
```

To exit the virtual environment, type `deactivate`.

### 3. Music Directory Setup

The player assumes a specific music organization within your chosen `music_dir` folder. This directory should contain sub-folders, each named after a dance type, containing the corresponding music files:

```text
music_dir/
├── ChaCha
├── Foxtrot
├── Jive
├── JSlow
├── LineDance
├── PasoDoble
├── QuickStep
├── Rumba
├── Samba
├── Tango
├── VienneseWaltz
├── VWSlow
├── Waltz
└── WCS
```

For instance, all Jive selections are in the `music_dir/Jive` folder,
all Waltz selections are in the `music_dir/Waltz` folder, etc.
You can set your `music_dir` via the "Music Settings" button in the application.

- Music File Requirements:
  - Musical selections are assumed to be at the correct tempo.
  - Songs longer than 3 minutes 30 seconds (210 seconds) will fade out and end by 3 minutes 40 seconds (adjustable via "Max Playtime" in settings), except when play_single_song is true for the playlist.  This is useful for line dances, in particular, where one wants to play the entire song.
  - It is recommended that the volume of your musical selections be normalized for consistent playback.

### 4. Running the Application

After activating your virtual environment (as shown above), navigate to the `DancePracticeMusicPlayer` directory and run:

```bash
python music_player.py
```

Windows users can run the application by double-clicking on `run_music_player.bat`.

---

## Usage

1. **Initial Setup:** On first run, the application will create a `music.ini` configuration file in the `DancePracticeMusicPlayer` directory.

2. **Set Music Directory:** Click the "Music Settings" button (bottom right) to configure your `Music Directory`. This directory should contain sub-folders for each dance type (e.g., "Waltz", "Tango", etc.) as described in the `Music Directory Setup` section.

3. **Generate Playlist:** The application automatically generates an initial playlist upon startup if a valid music directory is set. You can also click the "New Playlist" button to generate a new playlist based on the currently selected practice type.

4. **Playback Controls:**
    - Use the **Play/Pause**, **Stop**, and **Replay** buttons to control the current song.
    - Click on any song in the **clickable, scrollable playlist** to play it directly.
    - Drag the **progress bar** to seek within the current song.
    - Adjust the **volume slider** to control playback volume.

5. **Change Practice Type:** Use the "Music Settings" button to change the "Practice Type". This will adjust the sequence and number of songs played. The "New Playlist" button will also update to show the current practice type.

6. **Custom Practice Types:** Refer to the `Customizing Practice Types` section to learn how to create your own practice routines.

---

## Customizing Practice Types

The application allows you to define custom dance practice routines by creating a `custom_practice_types.json` file in the same directory as music_player.py. This file extends the built-in practice types available in the "Music Settings".

### custom_practice_types.json Structure

The JSON file should be a dictionary where each key is the name of your custom practice type, and the value is an object containing:

- `dances` (list of strings): The sequence of dance sub-folder names to include in the playlist
- `num_selections` (integer): The default number of songs to select for each dance type in the dances list
- `auto_update (boolean):` If true, the playlist will automatically generate a new set of songs and restart when it reaches the end
- `play_single_song (boolean):` If true, the player will stop after playing the entirety of a single song from the current selection
- `randomize_playlist (boolean):` If true, songs for each dance type will be randomly selected. If false, they will be displayed in a fixed order after selection
- `adjust_song_counts (boolean):` If true, the num_selections for certain dances will be adjusted based on predefined rules or dance_adjustments
- `dance_adjustments (object, optional):` A dictionary specifying custom rules for adjusting num_selections for individual dances. If adjust_song_counts is true but dance_adjustments is not specified, a default set of adjustments will be applied (e.g., to reduce the number of songs for specific dances like Paso Doble, Viennese Waltz, Jive, WCS, JSlow, and VWSlow). These rules can be direct mappings (e.g., {"1": 0, "2": 1, "default": 2}) or string formulas (e.g., "n-1", "cap_at_1").

**Example** `custom_practice_types.json`

```json
{
  "Beginner": {
    "dances": ["Waltz", "JSlow", "Rumba", "Foxtrot", "ChaCha", "Tango"],
    "num_selections": 1,
    "auto_update": true,
    "play_single_song": false,
    "randomize_playlist": true,
    "adjust_song_counts": false
  },
  "Intermediate": {
    "dances": ["Waltz", "JSlow", "Rumba", "Foxtrot", "ChaCha", "Tango", "Samba", "QuickStep"],
    "num_selections": 1,
    "auto_update": true,
    "play_single_song": false,
    "randomize_playlist": true,
    "adjust_song_counts": false
  },
  "Competition": {
    "dances": ["Waltz", "Tango", "VWSlow", "VienneseWaltz", "Foxtrot", "QuickStep", "WCS", "Samba", "ChaCha", "Rumba", "PasoDoble", "JSlow", "Jive"],
    "num_selections": 3,
    "auto_update": false,
    "play_single_song": false,
    "randomize_playlist": true,
    "adjust_song_counts": true,
    "dance_adjustments": {
      "PasoDoble": {
        "1": 0,
        "2": 1,
        "3": 1,
        "default": 2
      },
      "VWSlow": "cap_at_1",
      "JSlow": "cap_at_1",
      "VienneseWaltz": "n-1",
      "Jive": "n-1",
      "WCS": "cap_at_2"
    }
  },
  "Misc": {
    "dances": [
      "AmericanRumba",
      "ArgentineTango",
      "Bolero",
      "DiscoFox",
      "Hustle",
      "LindyHop",
      "Mambo",
      "Merengue",
      "NC2Step",
      "Polka",
      "Salsa"
    ],
    "num_selections": 100,
    "auto_update": false,
    "play_single_song": false,
    "randomize_playlist": true,
    "adjust_song_counts": false
  }
}
```

### How to Use Custom Types

1. Create or modify the `custom_practice_types.json` file in the root directory of the application.
2. The new practice types (e.g., "Beginner", "Intermediate") will appear in the "Practice Type" dropdown within the "Music Settings" panel.

---

## Code Architecture

The application's core logic is primarily contained within two main classes: `MusicApp` and `MusicPlayer`.

1 `MusicApp` **(kivy.app.App)**:

- The entry point of the Kivy application.
- Manages application-level configurations, settings loading, and initial setup.
- Handles default configuration values and changes to user settings.
- Applies platform-specific fixes (e.g., for Windows console visibility and GStreamer priming).

2 `MusicPlayer` **(kivy.uix.boxlayout.BoxLayout):**

- The main UI widget responsible for all music player functionality.
- **UI Management:** Builds and manages the layout, including the scrollable playlist, control buttons, volume slider, and progress bar.
- **Playlist Logic:** Generates, updates, and manages the playback of randomized playlists based on selected dance types.
- **Sound Control:** Handles loading, playing, pausing, stopping, and seeking within audio files using `kivy.core.audio.SoundLoader`.
- **Settings Integration:** Interacts with the application settings to configure music directory, volume, max playtime, and practice type.
- **Custom Practice Types:** Loads and integrates custom practice definitions from `custom_practice_types.json`.

### Key Methods Overview

Some critical methods within the MusicPlayer class include:

- `play_sound():` Loads and plays the current song, handling sound state and progress updates.
- `pause_sound():` Pauses the music and updates the play/pause icon.
- `stop_sound():` Stops playback, unloads the sound, and resets player state.
- `restart_sound():` Restarts the current song from the beginning.
- `update_progress():` Called periodically to update the UI progress bar and manage song transitions (fade out, next song).
- `update_playlist(directory):` Regenerates the entire playlist based on the current music directory and selected dance types.
- `_display_playlist_buttons():` Renders the current playlist as clickable buttons in the UI.
- `set_practice_type(text):` Updates the internal dance lists and playlist generation logic based on the chosen practice type, including applying randomize_playlist, adjust_song_counts, and dance_adjustments.
- `load_custom_practice_types():` Reads custom practice types from `custom_practice_types.json`.
- `merge_custom_practice_types():` Integrates loaded custom practice types into the application's settings and dance mappings.

### Configuration

The application uses a `music.ini` file for persistent configuration (music directory, volume, maximum song playtime, and practice type). This file is automatically created on first run and can be modified via the "Music Settings" button.

### Practice Dances

The `practice_dances` property within MusicPlayer defines the default dance sequences for different practice lengths (e.g., "60min", "90min", "LineDance"). This data is extended by the `custom_practice_types.json` file, allowing users to define their own dance lists and associated song selection rules.

## License

This project is licensed under the MIT License. See `LICENSE` for details.

## Contributing

Feel free to fork the repository and submit pull requests for new features or bug fixes.
