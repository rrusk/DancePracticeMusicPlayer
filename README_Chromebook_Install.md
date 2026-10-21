# Installing on a Chromebook

The player runs in the Chromebook's Linux development environment.
`install_dance_practice_chromebook.sh` sets it up there. It installs the system packages
the player needs, connects a shared music folder, and creates the player's Python
environment.

---

## Before You Start

You need:

- **Linux turned on.** Open **Settings → About ChromeOS → Developers → Linux development
  environment → Set up**. Setup takes a few minutes and ends by opening a Terminal window.
  On a Chromebook managed by a school or workplace, the administrator may have turned
  this option off.
- **An internet connection.** The installer downloads system packages from Debian and
  Python packages from PyPI.
- **Git, to download the player.** The installer is part of the player's repository, so
  Git must be installed before you can get the installer. In the Terminal:

  ```bash
  sudo apt-get update
  sudo apt-get install -y git
  ```

- **A shared music folder (optional).** Share a folder with Linux if you want your music
  to stay in the Chromebook's own storage (**My files**) rather than inside Linux:
  1. In the **Files** app, open **My files** and create a folder named `LinuxData`.
  2. Put your music in it, for example in `LinuxData/Music`, with one folder per dance
     inside (see [Music Directory Setup](README.md#3-music-directory-setup)).
  3. Right-click `LinuxData` and choose **Share with Linux**.

  The location inside Linux depends on its shared-folder layout:

  | Layout | Shared folder inside Linux |
  | --- | --- |
  | With the `shared` directory | `/mnt/chromeos/shared/MyFiles/LinuxData` |
  | Classic Crostini | `/mnt/chromeos/MyFiles/LinuxData` |

  `My files` is the name shown in the ChromeOS Files app; the Linux path uses `MyFiles`.

  The installer finds the shared folder at either path and links `~/LinuxData` to it.
  `~/LinuxData` is a shortcut to the shared folder, not another copy of your music. To
  see where it points:

  ```bash
  readlink -f ~/LinuxData
  ```

  You can also share the folder after installing and run the installer again to create
  the link. The installer never replaces an existing `~/LinuxData`. If it points to a
  folder that no longer exists, the installer warns and leaves it alone; remove it with
  `rm ~/LinuxData` (this removes only the shortcut) and run the installer again.

  Without a shared folder, put your music in the Linux `Music` folder. The installer
  creates it, and the Files app shows it under **Linux files**.

---

## Installing

In the Terminal, run:

```bash
mkdir -p ~/git
git clone https://github.com/rrusk/DancePracticeMusicPlayer.git ~/git/DancePracticeMusicPlayer
bash ~/git/DancePracticeMusicPlayer/install_dance_practice_chromebook.sh
```

Clone into `~/git/DancePracticeMusicPlayer` exactly. The installer works on that
location. If the repository is anywhere else, the installer downloads a second copy
there and sets up that copy instead.

Run the installer as your normal user, not with `sudo`. It uses `sudo` itself for the
system packages.

The installer:

- installs Python, the libraries Kivy needs, and the `pactl` sound tool;
- attempts to set the Linux sound output to 100% and reports whether it succeeded;
  the Chromebook's own volume control still sets how loud the player is;
- keeps an existing working `~/LinuxData` shortcut, or creates one to the shared folder
  at whichever of the two paths it finds, and creates `~/Music`, the player's default
  music folder;
- creates the Python environment `kivy_venv` with Kivy, ffpyplayer, and TinyTag;
- checks that Kivy can load one of the player's sound cues.

That check does not open a window or play sound. To finish checking, start the player
and play an MP3 song and an OGG song.

---

## Starting the Player

```bash
bash ~/git/DancePracticeMusicPlayer/run_music_player.sh
```

On first start, open **Music Settings** and choose your music folder: for music in a
shared folder, a folder under `~/LinuxData` such as `~/LinuxData/Music`; for music
stored inside Linux, `~/Music`.

The installer's closing message ends with optional lines that add the player to the
ChromeOS launcher. Paste them into the Terminal once. After that you can start the player
from the launcher, or pin it to the shelf, without opening the Terminal. A launcher start
shows no error messages. If the player does not open, start it from the Terminal to see
why.

With a large music library, building the song cache makes the player start faster; see
[Song Metadata Cache](README.md#song-metadata-cache).

---

## Good to Know

- **Quiet playback.** If the player becomes quiet, the Linux sound output may have been
  turned down. Check it with `pactl get-sink-volume @DEFAULT_SINK@` and set it back with
  `pactl set-sink-volume @DEFAULT_SINK@ 100%`.
- **Running the installer again** keeps the repository, your settings, and the
  `~/LinuxData` link. It reinstalls the Python packages at the versions the installer
  names and attempts to set the Linux sound output back to 100%. Check the final
  audio status; an unavailable audio server or failed command leaves it unchanged.
- **Updating the player.** The installer does not download updates. To update, run
  `git -C ~/git/DancePracticeMusicPlayer pull`, then run the installer again.
- **Your settings live with the player.** `music.ini`, `custom_practice_types.json`, and
  `play_history.json` are kept in `~/git/DancePracticeMusicPlayer`. Removing the Linux
  development environment deletes them along with the player, so copy them somewhere safe
  first. Music in a shared **My files** folder is not affected.
