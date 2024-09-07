# DancePracticeMusicPlayer
Kivy App for playing dance practice music

Git comes with Linux distributions.  For Windows, get Git for Windows at https://git-scm.com/download/win.  Then this repo can be downloaded using 
<pre>
git clone https://github.com/rrusk/DancePracticeMusicPlayer.git
</pre>

Instructions for installing Kivy are at https://kivy.org/doc/stable/gettingstarted/installation.html.  Python and pip need to be installed before installing kivy.

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

Modify config.json to point to the music folder.
For instance, on the VBDS Windows computers, change the music_dir line to read
    "music_dir": "C:\\Users\\vbds_\\Music"

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
be of appropriate length (selections longer than 3m30s will fade out and end by 3m40s regardless of length).
The volume of the musical selections should be normalized.

To run the app, make sure to run the kivy activate script and then use
<pre>
python main.py
</pre>

The GUI should look like this on Linux and MacOS desktops:
![DancePracticeMusicPlayer](https://github.com/user-attachments/assets/6331954b-ee8d-4e10-a224-9ae9f672bb49)

It looks the same on Windows desktops except that the "Pause" button is not present because of seek issues with GstStreamer.

