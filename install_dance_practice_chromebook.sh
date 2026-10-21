#!/usr/bin/env bash
# Install DancePracticeMusicPlayer in a Chromebook Linux (Crostini) container.
set -Eeuo pipefail

REPO_URL='https://github.com/rrusk/DancePracticeMusicPlayer.git'
PROJECT_DIR="$HOME/git/DancePracticeMusicPlayer"
VENV_DIR="$PROJECT_DIR/kivy_venv"
# Where Linux sees My files/LinuxData once it is shared; which one exists depends on
# the Linux environment's shared-folder layout.
CHROMEOS_DATA_PATHS=(
    '/mnt/chromeos/shared/MyFiles/LinuxData'
    '/mnt/chromeos/MyFiles/LinuxData'
)
LINUX_DATA_LINK="$HOME/LinuxData"

log() { printf '\n==> %s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

if [[ "${EUID}" -eq 0 ]]; then
    die 'Run this script as your normal Linux user, not with sudo.'
fi
if ! command -v apt-get >/dev/null 2>&1; then
    die 'This installer requires the Debian/Ubuntu-based Chromebook Linux container.'
fi

log 'Installing system packages (sudo password may be requested)'
sudo apt-get update
# The Kivy 2.3.1 and ffpyplayer 4.5.3 wheels bundle their media libraries; these
# are the system libraries (beyond glibc) they link against on x86-64 and ARM64.
# GLib's package is libglib2.0-0t64 from Debian 13 on.
glib_pkg=libglib2.0-0
# madison lists available versions; `apt-cache show` also succeeds for a
# name that other packages merely refer to.
if [[ -n "$(apt-cache madison libglib2.0-0t64 2>/dev/null)" ]]; then
    glib_pkg=libglib2.0-0t64
fi
sudo apt-get install -y git ca-certificates python3 python3-venv \
    libgl1 libx11-6 libxrender1 "$glib_pkg" libexpat1 zlib1g libstdc++6 libgcc-s1 \
    pulseaudio-utils

log 'Setting default Linux audio output to 100%'
# This sets the shared Linux output, not just the player's own volume.
# Use the user's audio session, without sudo, and never boost above 100%.
linux_volume_status='Not changed: the Linux audio server is unavailable.'
if pactl info >/dev/null 2>&1; then
    if pactl set-sink-volume @DEFAULT_SINK@ 100%; then
        linux_volume_status='Default Linux audio output set to 100%.'
        pactl get-sink-volume @DEFAULT_SINK@ || true
    else
        linux_volume_status='Not changed: could not set the default Linux audio output to 100%.'
        warn "$linux_volume_status"
    fi
else
    warn "$linux_volume_status Start the Linux audio session and retry the command printed below."
fi

log 'Connecting ChromeOS-shared storage'
CHROMEOS_DATA=''
for candidate in "${CHROMEOS_DATA_PATHS[@]}"; do
    if [[ -d "$candidate" ]]; then
        CHROMEOS_DATA="$candidate"
        break
    fi
done
if [[ -L "$LINUX_DATA_LINK" && -d "$LINUX_DATA_LINK" ]]; then
    CHROMEOS_DATA="$(readlink -f "$LINUX_DATA_LINK")"
    log "Existing ~/LinuxData link works: $CHROMEOS_DATA"
elif [[ -n "$CHROMEOS_DATA" ]]; then
    if [[ -L "$LINUX_DATA_LINK" ]]; then
        warn "~/LinuxData is a symlink to $(readlink "$LINUX_DATA_LINK"); leaving it unchanged."
        warn "To link $CHROMEOS_DATA instead, run rm ~/LinuxData (it removes only the link) and rerun this script."
    elif [[ -e "$LINUX_DATA_LINK" ]]; then
        warn '~/LinuxData already exists and is not a symlink; leaving it unchanged.'
    else
        ln -s "$CHROMEOS_DATA" "$LINUX_DATA_LINK"
        log "Created ~/LinuxData -> $CHROMEOS_DATA"
    fi
else
    looked=$(printf '%s, ' "${CHROMEOS_DATA_PATHS[@]}")
    warn "No shared LinuxData folder found (looked for ${looked%, })."
    warn 'In ChromeOS Files, create My files/LinuxData if necessary, select Share with Linux, then rerun this script.'
    warn 'The application can install without it, but music in ChromeOS storage will not yet be accessible.'
fi

# The player's default music directory is ~/Music. Preserve any existing path,
# including a dangling symlink; shared music is selected in Music Settings.
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

Linux audio: $linux_volume_status
To set the default Linux output to 100% later:
    pactl set-sink-volume @DEFAULT_SINK@ 100%

Launch with:
    cd "$PROJECT_DIR"
    bash ./run_music_player.sh

Shared ChromeOS data (when enabled):
    ${CHROMEOS_DATA:-not found; see the warning above}

In the player, choose the music directory using Music Settings.
The historical paths were ~/LinuxData/Music and ~/LinuxData/MUSICCOMP.

Optional song cache generation (after choosing/setting music directory):
    cd "$PROJECT_DIR"
    "$VENV_DIR/bin/python" utils/build_song_cache.py

Note: Your settings and music are not restored by cloning the Git repository.
Keep backups of application configuration and your ChromeOS music folder.

Optional: start the player from the ChromeOS launcher instead of a terminal.
Paste these lines into the Linux terminal once, exactly as shown (unindented):

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

"Dance Practice Music Player" then appears in the ChromeOS launcher, usually in
its Linux apps folder; delete that .desktop file to remove it. A launcher start
shows no error output: if the player does not open, start it from the terminal
as above, or read the newest log in ~/.kivy/logs.
SUMMARY
