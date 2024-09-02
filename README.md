# DancePracticeMusicPlayer
Kivy App for playing dance practice music

Instructions for installing Kivy are at https://kivy.org/doc/stable/gettingstarted/installation.html.  Python and pip need to be installed before installing kivy.

Assuming this repo has been installed in $HOME/git/DancePracticeMusicPlayer, change to that directory.

For Ubuntu:
<pre>
 python3 -m pip install --upgrade pip setuptools virtualenv
 python3 -m venv kivy_venv
 source kivy_venv/bin/activate
 python -m pip install "kivy[base,media]" kivy_examples
</pre>

For Windows:
As above except you don't source the kivy activate script, instead enter on the command-line:
<pre>
kivy_venv\Scripts\activate
</pre>

Modify config.json to point to the music folder.
For instance, on the VBDS Windows computers, change the music_dir line to read
    "music_dir": "C:\\Users\\vbds_\\Music"

The player assumes the following music organization:
<pre>
$HOME/Music/
├── ChaCha
├── Foxtrot
├── Jive
├── LineDance
├── PasoDoble
├── QuickStep
├── Rumba
├── Samba
├── Tango
├── VienneseWaltz
├── Waltz
└── WCS
</pre>

The musical selections are assumed to be at the correct tempo and to
be of appropriate length.  The volume of the musical selections should
be normalized.

To run the app, make sure to run the kivy activate script and then use
<pre>
python main.py
</pre>
