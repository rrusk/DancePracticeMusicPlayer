#!/bin/bash

# ==============================================================================
# Script Name: batch_update_albums.sh
# Description: Automates the process of tagging MP3 albums.
#              1. Iterates through all subdirectories in the current folder.
#              2. Uses the directory name as the 'Album' tag.
#              3. Applies global 'Artist' and 'Genre' tags to all files.
#              4. Supports a "Remove Art Only" mode that preserves existing tags.
#              5. ENSURES cover.jpg files are NEVER embedded.
#
# Usage:       batch_update_albums.sh [-a "Artist"] [-g "Genre"] [--remove-art-only]
# ==============================================================================

# Strict Mode
set -euo pipefail

# -----------------------------------------------------------------------------
# Configuration & Defaults
# -----------------------------------------------------------------------------

DEFAULT_ARTIST="Various Artists"
DEFAULT_GENRE="Country"
TOOL_NAME="update_metadata.py"

# State Variables
TARGET_ARTIST="$DEFAULT_ARTIST"
TARGET_GENRE="$DEFAULT_GENRE"
UPDATE_TAGS=true        # Default: Yes, update the text tags
REMOVE_ART_FLAG=""      # Default: No, do not remove art

# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------

print_usage() {
    echo "Usage: $(basename "$0") [OPTIONS]"
    echo ""
    echo "Updates MP3 metadata in all subdirectories of the current folder."
    echo "This script explicitly PREVENTS embedding cover art."
    echo ""
    echo "Options:"
    echo "  -a, --artist ARTIST    Set global Artist (default: '$DEFAULT_ARTIST')"
    echo "  -g, --genre GENRE      Set global Genre (default: '$DEFAULT_GENRE')"
    echo "  -r, --remove-art-only  Remove embedded art WITHOUT changing any text tags"
    echo "                         (Ignores -a, -g and preserves Album titles)"
    echo "  -h, --help             Show this help message"
    echo ""
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
        -r|--remove-art-only)
            UPDATE_TAGS=false
            REMOVE_ART_FLAG="--remove-art"
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

# Check if tool exists in PATH
if ! command -v "$TOOL_NAME" &> /dev/null; then
    echo "Error: '$TOOL_NAME' was not found in your PATH." >&2
    exit 1
fi

# Resolve path for display
TOOL_PATH=$(command -v "$TOOL_NAME")

# Check for directories
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

if [ "$UPDATE_TAGS" = true ]; then
    echo "Mode:              UPDATE TAGS (Artist/Genre/Album)"
    echo "Target Artist:     $TARGET_ARTIST"
    echo "Target Genre:      $TARGET_GENRE"
    echo "Target Album:      (Set to subdirectory name)"
    echo "Art Embedding:     DISABLED (Using --no-embed)"
else
    echo "Mode:              REMOVE ART ONLY"
    echo "Target Artist:     (Preserve existing)"
    echo "Target Genre:      (Preserve existing)"
    echo "Target Album:      (Preserve existing)"
fi

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

    # Build the command dynamically using a Bash Array
    cmd=("$TOOL_NAME" "$dir_path")

    # 1. Handle Art Removal
    if [[ -n "$REMOVE_ART_FLAG" ]]; then
        cmd+=("$REMOVE_ART_FLAG")
    fi

    # 2. Handle Text Tags
    if [ "$UPDATE_TAGS" = true ]; then
        cmd+=(--artist "$TARGET_ARTIST")
        cmd+=(--genre "$TARGET_GENRE")
        cmd+=(--album "$album_title")
        
        # ALWAYS pass --no-embed when updating tags to prevent touching cover.jpg
        cmd+=(--no-embed)
    fi

    # Execute the constructed command
    "${cmd[@]}"

    echo "------------------------------------------"
done

echo "✔ All batch operations completed successfully."
