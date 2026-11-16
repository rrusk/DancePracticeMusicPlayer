#!/usr/bin/env bash
# Install DancePracticeMusicPlayer on Debian or a Debian-based distribution such as Ubuntu.
set -Eeuo pipefail

REPO_URL='https://github.com/rrusk/DancePracticeMusicPlayer.git'
PROJECT_DIR="$HOME/git/DancePracticeMusicPlayer"
VENV_DIR="$PROJECT_DIR/kivy_venv"

log() { printf '\n==> %s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

if [[ "${EUID}" -eq 0 ]]; then
    die 'Run this script as your normal user, not with sudo.'
fi
if ! command -v apt-get >/dev/null 2>&1; then
    die 'This installer requires Debian or a Debian-based distribution with apt-get.'
fi
# A Debian installed with a root password has no sudo, or leaves the first user out of it.
if ! command -v sudo >/dev/null 2>&1; then
    die "sudo is not installed. As root (su -), run:
    apt-get install sudo && adduser $(id -un) sudo
then log out and back in, and rerun this script."
fi

log 'Installing system packages (sudo password may be requested)'
sudo -v || die "sudo did not run. If your account may not use sudo, as root (su -) run:
    adduser $(id -un) sudo
then log out and back in, and rerun this script."
sudo apt-get update
# The Kivy 2.3.1 and ffpyplayer 4.5.3 wheels bundle their media libraries; these
# are the system libraries (beyond glibc) they link against on x86-64 and ARM64.
# GLib's package is libglib2.0-0t64 from Debian 13 and Ubuntu 24.04 on.
glib_pkg=libglib2.0-0
# madison lists available versions; `apt-cache show` also succeeds for a
# name that other packages merely refer to.
if [[ -n "$(apt-cache madison libglib2.0-0t64 2>/dev/null)" ]]; then
    glib_pkg=libglib2.0-0t64
fi
sudo apt-get install -y git ca-certificates python3 python3-venv xsel xclip \
    libgl1 libx11-6 libxrender1 "$glib_pkg" libexpat1 zlib1g libstdc++6 libgcc-s1

# Kivy 2.3.1 and ffpyplayer 4.5.3 publish wheels for Python 3.9-3.13 only; on any
# other Python, pip would try to build them from source and fail.
if ! python3 -c 'import sys; sys.exit(not (3, 9) <= sys.version_info[:2] <= (3, 13))'; then
    die "$(python3 -V) is outside the 3.9-3.13 range that Kivy 2.3.1 and ffpyplayer 4.5.3 support.
Use a release whose python3 is in that range, such as Debian 12 or 13."
fi

# The player's default music directory is ~/Music. Preserve any existing path,
# including a dangling symlink; music elsewhere is selected in Music Settings.
if [[ ! -e "$HOME/Music" && ! -L "$HOME/Music" ]]; then
    mkdir -p "$HOME/Music"
    log 'Created ~/Music for the default music directory'
fi

log 'Installing application source'
mkdir -p "$HOME/git"
if [[ -d "$PROJECT_DIR/.git" ]]; then
    log "Using existing repository: $PROJECT_DIR (no automatic git pull)"
elif [[ -e "$PROJECT_DIR" ]]; then
    die "$PROJECT_DIR exists but is not a Git repository; refusing to overwrite it."
else
    git clone "$REPO_URL" "$PROJECT_DIR"
fi

log 'Preparing Python virtual environment'
if [[ ! -e "$VENV_DIR" ]]; then
    python3 -m venv "$VENV_DIR"
elif ! "$VENV_DIR/bin/python" -m pip --version >/dev/null 2>&1; then
    die "$VENV_DIR exists but its Python or pip does not run (for example after a Python upgrade).
Remove it with:  rm -rf \"$VENV_DIR\"
then rerun this script to rebuild it."
fi
# Use the venv interpreter directly to avoid modifying system-managed Python.
"$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools
"$VENV_DIR/bin/python" -m pip install 'kivy[base,media]==2.3.1' 'kivy_examples==2.3.1' \
    'ffpyplayer==4.5.3' 'tinytag==2.0.0'

log 'Verifying installation'
[[ -f "$PROJECT_DIR/run_music_player.sh" ]] || die 'run_music_player.sh is missing from the repository.'
TEST_CUE="$PROJECT_DIR/cues/gap_10.ogg"
if [[ -f "$TEST_CUE" ]]; then
    # Loads (without playing) a cue through Kivy's audio backend; no window is opened.
    KIVY_NO_ARGS=1 KIVY_NO_CONSOLELOG=1 "$VENV_DIR/bin/python" - "$TEST_CUE" <<'PY' \
        || die 'Kivy could not load the test cue through any audio backend; see the newest log in ~/.kivy/logs.'
import sys
from importlib.metadata import version
import tinytag  # imported, not only looked up, so a broken package fails here
from kivy.core.audio import SoundLoader
sound = SoundLoader.load(sys.argv[1])
if sound is None:
    sys.exit(1)
try:
    if not sound.length:
        sys.exit(1)
    print("Kivy:", version("kivy"))
    print("TinyTag:", version("tinytag"))
    print(f"Audio: {type(sound).__name__} loaded a {sound.length:.1f} s test cue")
finally:
    # ffpyplayer can hang at interpreter exit if its player is not released.
    sound.unload()
PY
else
    warn "$TEST_CUE is not in this checkout; skipping the audio backend check."
    KIVY_NO_ARGS=1 KIVY_NO_CONSOLELOG=1 "$VENV_DIR/bin/python" -c 'import kivy, tinytag' || die 'Kivy or TinyTag does not import in the venv.'
fi

cat <<SUMMARY

Packages installed. The checks above do not open a window or play sound:
launch the player once and play an MP3 and an OGG song to finish checking.

Application: $PROJECT_DIR
Virtual env: $VENV_DIR

Launch with:
    cd "$PROJECT_DIR"
    bash ./run_music_player.sh

In the player, choose the music directory using Music Settings (default ~/Music).

Optional song cache generation (after choosing/setting music directory):
    cd "$PROJECT_DIR"
    "$VENV_DIR/bin/python" utils/build_song_cache.py

Note: Your settings and music are not restored by cloning the Git repository.
Keep backups of application configuration and your music folder.

Optional: start the player from your desktop's application menu instead of a terminal.
Paste these lines into a terminal once, exactly as shown (unindented):

mkdir -p ~/.local/share/applications
cat > ~/.local/share/applications/dance-practice-music-player.desktop <<'EOF'
[Desktop Entry]
Type=Application
Name=Dance Practice Music Player
Exec=bash "$PROJECT_DIR/run_music_player.sh"
Icon=$PROJECT_DIR/icons/play.png
Terminal=false
Categories=AudioVideo;Audio;
EOF

"Dance Practice Music Player" then appears in the application menu of GNOME, KDE
Plasma, Xfce and other freedesktop.org desktops, usually at once, otherwise after
logging out and back in; delete that .desktop file to remove it. A menu start
shows no error output: if the player does not open, start it from the terminal
as above, or read the newest log in ~/.kivy/logs.
SUMMARY
