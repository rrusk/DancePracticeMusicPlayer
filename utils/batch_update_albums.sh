#!/bin/bash

# ==============================================================================
# Script Name: batch_update_albums.sh
# Description: Automates the process of tagging and renaming audio files.
#              1. Iterates through all subdirectories in the current folder.
#              2. Only updates specific tags explicitly requested via flags.
#              3. Can set Album tag to match the directory name (requires -t).
#              4. Can RENAME files based on the Title tag (requires --rename).
#              5. Cover Art is IGNORED by default (Opt-in via --embed).
#
# Usage:       batch_update_albums.sh [-a "Artist"] [-g "Genre"] [--rename] [--embed]
# ==============================================================================

# Strict Mode
set -euo pipefail

# -----------------------------------------------------------------------------
# Configuration & Defaults
# -----------------------------------------------------------------------------

TOOL_NAME="update_metadata.py"

# State Variables
TARGET_ARTIST=""
TARGET_GENRE=""
SET_ALBUM_FROM_DIR=false  # Default: Do not change album tag
REMOVE_ART=false          # Default: Do not remove art
RENAME_FILES=false        # Default: Do not rename files
EMBED_ART=false           # Default: Do not embed art

# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------

print_usage() {
    echo "Usage: $(basename "$0") [OPTIONS]"
    echo ""
    echo "Updates audio metadata in all subdirectories of the current folder."
    echo "NOTE: No tags are changed unless explicitly requested."
    echo ""
    echo "Options:"
    echo "  -a, --artist ARTIST    Set global Artist"
    echo "  -g, --genre GENRE      Set global Genre"
    echo "  -t, --tag-album        Set Album tag to match the subdirectory name"
    echo "  -r, --remove-art       Remove all embedded cover art"
    echo "  -n, --rename           Rename files based on Title tag (e.g. '01 - Title.ogg')"
    echo "  -e, --embed            Embed 'cover.jpg' if found (Opt-in)"
    echo "  -h, --help             Show this help message"
    echo ""
    echo "Examples:"
    echo "  $(basename "$0") --rename                       (Batch rename only)"
    echo "  $(basename "$0") -a \"Lyle Lovett\" --rename      (Set Artist and Rename)"
}

# -----------------------------------------------------------------------------
# Argument Parsing
# -----------------------------------------------------------------------------

while [[ $# -gt 0 ]]; do
    case "$1" in
        -a|--artist)
            if [[ -n "${2:-}" ]]; then
                TARGET_ARTIST="$2"
                shift 2
            else
                echo "Error: Argument for $1 is missing" >&2
                exit 1
            fi
            ;;
        -g|--genre)
            if [[ -n "${2:-}" ]]; then
                TARGET_GENRE="$2"
                shift 2
            else
                echo "Error: Argument for $1 is missing" >&2
                exit 1
            fi
            ;;
        -t|--tag-album)
            SET_ALBUM_FROM_DIR=true
            shift 1
            ;;
        -r|--remove-art|--remove-art-only)
            REMOVE_ART=true
            shift 1
            ;;
        -n|--rename)
            RENAME_FILES=true
            shift 1
            ;;
        -e|--embed)
            EMBED_ART=true
            shift 1
            ;;
        -h|--help)
            print_usage
            exit 0
            ;;
        *)
            echo "Error: Unknown option '$1'" >&2
            print_usage
            exit 1
            ;;
    esac
done

# -----------------------------------------------------------------------------
# Pre-flight Checks
# -----------------------------------------------------------------------------

# 1. Ensure at least one action is specified
if [[ -z "$TARGET_ARTIST" ]] && \
   [[ -z "$TARGET_GENRE" ]] && \
   [[ "$SET_ALBUM_FROM_DIR" == false ]] && \
   [[ "$REMOVE_ART" == false ]] && \
   [[ "$RENAME_FILES" == false ]] && \
   [[ "$EMBED_ART" == false ]]; then
    echo "Error: No actions specified."
    echo "You must provide at least one option (e.g., --artist, --rename, -t)."
    echo ""
    print_usage
    exit 1
fi

# 2. Check if tool exists in PATH
if ! command -v "$TOOL_NAME" &> /dev/null; then
    echo "Error: '$TOOL_NAME' was not found in your PATH." >&2
    exit 1
fi

# Resolve path for display
TOOL_PATH=$(command -v "$TOOL_NAME")

# 3. Check for directories
dir_count=$(find . -maxdepth 1 -type d -not -path '.' | wc -l)
if [[ "$dir_count" -eq 0 ]]; then
    echo "Error: No subdirectories found in current location." >&2
    exit 1
fi

# -----------------------------------------------------------------------------
# User Confirmation
# -----------------------------------------------------------------------------

echo "=========================================="
echo "      Batch Metadata Update Review        "
echo "=========================================="
echo "Working Directory: $(pwd)"
echo "Using Tool:        $TOOL_PATH"
echo "------------------------------------------"

if [[ -n "$TARGET_ARTIST" ]]; then
    echo "Target Artist:     $TARGET_ARTIST"
else
    echo "Target Artist:     [No Change]"
fi

if [[ -n "$TARGET_GENRE" ]]; then
    echo "Target Genre:      $TARGET_GENRE"
else
    echo "Target Genre:      [No Change]"
fi

if [[ "$SET_ALBUM_FROM_DIR" == true ]]; then
    echo "Target Album:      [Set to Subdirectory Name]"
else
    echo "Target Album:      [No Change]"
fi

if [[ "$RENAME_FILES" == true ]]; then
    echo "File Renaming:     ENABLED (Title -> Filename)"
else
    echo "File Renaming:     [No Change]"
fi

if [[ "$REMOVE_ART" == true ]]; then
    echo "Cover Art:         REMOVE ALL EMBEDDED ART"
elif [[ "$EMBED_ART" == true ]]; then
    echo "Cover Art:         AUTO-EMBED 'cover.jpg' IF FOUND"
else
    echo "Cover Art:         [No Change / Ignore]"
fi

echo "------------------------------------------"
echo "Albums (Dirs):     $dir_count detected"
echo "=========================================="
echo ""
echo "WARNING: This operation will modify files in subdirectories."
read -r -p "Are you sure you want to proceed? [y/N] " response

if [[ ! "$response" =~ ^[yY]$ ]]; then
    echo "Operation cancelled."
    exit 0
fi

# -----------------------------------------------------------------------------
# Main Execution
# -----------------------------------------------------------------------------

echo ""
for dir_path in */; do
    [ -d "$dir_path" ] || continue

    # Strip trailing slash
    album_title="${dir_path%/}"
    
    echo "Processing Album: [$album_title]"

    # Start building the command
    cmd=("$TOOL_NAME" "$dir_path")

    # 1. Conditionally add flags based on user input
    if [[ -n "$TARGET_ARTIST" ]]; then
        cmd+=(--artist "$TARGET_ARTIST")
    fi

    if [[ -n "$TARGET_GENRE" ]]; then
        cmd+=(--genre "$TARGET_GENRE")
    fi

    if [[ "$SET_ALBUM_FROM_DIR" == true ]]; then
        cmd+=(--album "$album_title")
    fi

    if [[ "$RENAME_FILES" == true ]]; then
        cmd+=(--rename)
    fi

    if [[ "$REMOVE_ART" == true ]]; then
        cmd+=(--remove-art)
    fi

    if [[ "$EMBED_ART" == true ]]; then
        cmd+=(--embed)
    fi

    # Execute the constructed command
    "${cmd[@]}"

    echo "------------------------------------------"
done

echo "✔ All batch operations completed successfully."
