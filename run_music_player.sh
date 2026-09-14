#!/bin/bash
# Run from the checkout containing this script, wherever it is located.
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cd "$SCRIPT_DIR" || exit 1
source "$SCRIPT_DIR/kivy_venv/bin/activate"
# Write startup and playlist-generation timings to the Kivy log (~/.kivy/logs).
export DPMP_TIMING=1
python "$SCRIPT_DIR/music_player.py"
