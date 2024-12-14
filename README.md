# DancePracticeMusicPlayer
Kivy App for playing dance practice music


**Overview**

*DancePracticeMusicPlayer* is a Kivy application written in Python that
creates a music player with features useful for dance practices that use a
predetermined sequence of dances types. It automatically generates a
playlist with an announcement of each dance type before those dance
selections are played.  The dance selections are chosen randomly from
the available selections for each dance type so that each practice
has a different playlist.

The application is designed to play music files (MP3, WAV, OGG) from a
selected directory. It has a user interface with buttons to play, pause,
stop, and restart the music. The application also allows users to select
a music directory, adjust the volume, and choose a practice length
(e.g., 60 minutes, 90 minutes, etc.).

**Installation**

Git comes with Linux distributions.  For Windows, get Git for Windows at https://git-scm.com/download/win.  Then this repo can be downloaded using 
<pre>
git clone https://github.com/rrusk/DancePracticeMusicPlayer.git
</pre>

Instructions for installing Kivy are at https://kivy.org/doc/stable/gettingstarted/installation.html.  Python and pip need to be installed before installing kivy.  For Windows, use Python 3.12.8 until issues with Kivy on 3.13.x are resolved.

Assuming this repo has been installed in $HOME/git/DancePracticeMusicPlayer, change to that directory.

For Ubuntu and MacOS:
<pre>
 python3 -m pip install --upgrade pip setuptools virtualenv
 python3 -m venv kivy_venv
 source kivy_venv/bin/activate
 python -m pip install "kivy[base,media]" kivy_examples
 python -m pip install tinytag # not part of kivy, used to read music ID3v2 tags
</pre>

For Windows:
As above except you don't source the kivy activate script, instead enter on the command-line:
<pre>
 python -m pip install --upgrade pip setuptools virtualenv
 python -m venv kivy_venv
 kivy_venv\Scripts\activate
 python -m pip install "kivy[base,media]" kivy_examples
 python -m pip install tinytag
</pre>

On initial startup, the player creates a default 'music.ini' configuration file.
The "Music Settings" button can be used to modify the configuration file,
including the location of the music directory.

The player assumes the following music organization within the <i>music_dir</i> folder:
<pre>
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
</pre>
For instance, all Jive selections are in the <i>music_dir/Jive</i> folder,
all Waltz selections are in the <i>music_dir/Waltz</i> folder, etc.
The "Select Music" button on the lower right of the display can also but used to select the music folder.

The musical selections are assumed to be at the correct tempo and to
be of appropriate length.
Selections longer than 3m30s will fade out and end by 3m40s (210 seconds) regardless of length
though this can be adjusted by modifying "song_max_playtime" in the music settings.
The volume of the musical selections should be normalized.

To run the app, make sure to run the kivy activate script and then use
<pre>
python main.py
</pre>

The GUI should look similar to this on Linux, MacOS and Windows desktops:
![music_player](https://github.com/user-attachments/assets/0c736912-6fe6-41d4-ac6c-246d9a616087)

## Here\'s a breakdown of the code:

**Classes**

The code defines two main classes: MyFileChooser and MusicPlayer.

1.  MyFileChooser: This class creates a file chooser dialog that allows users to select a music directory. It inherits from Kivy\'s GridLayout class.

2.  MusicPlayer: This class is the main application class, which inherits from Kivy\'s BoxLayout class. It contains the music player\'s user interface and functionality.

**MusicPlayer Class**

The MusicPlayer class has several key features:

-   **Music Directory**: The application loads music files from a selected directory. The directory can be changed using the \"Select Music\" button.

-   **Playlist**: The application creates a randomized playlist of music files from the selected directory. The playlist is displayed as a list of buttons, each representing a song.

-   **Music Player Controls**: The application has buttons to play, pause, stop, and restart the music.

-   **Volume Control**: The application has a volume slider to adjust the music volume.

-   **Practice Length**: The application allows users to choose a practice length (e.g., 60 minutes, 90 minutes, etc.). This feature is used to adjust the number of songs played.

-   **Song Information**: The application displays song information, such as the song title, artist, album, and genre.

**Key Methods**

Some key methods in the MusicPlayer class include:

-   play\_sound: Plays the selected song.

-   pause\_sound: Pauses the music.

-   stop\_sound: Stops the music.

-   restart\_sound: Restarts the music from the beginning.

-   update\_progress: Updates the music progress bar and song information.

-   update\_playlist: Updates the playlist when the music directory changes.

-   display\_playlist: Displays the playlist as a list of buttons.

**Config File**

The application loads configuration data from a JSON file
named 'music.ini'. The configuration data includes the music directory,
volume, maximum song playtime and practice type.

**Practice Dances**

The application has a feature called \"Practice Dances,\" which allows
users to select a practice length and dance style (e.g., Waltz, Tango,
etc.). The application adjusts the number of songs played based on the
selected practice length and dance style.

In summary this code creates a functional music player with various
features, including playlist management, music controls, and practice
length selection.
