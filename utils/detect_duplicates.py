#!/usr/bin/env python3
# -*- encoding: utf-8 -*-

"""
Scans a directory for audio files to find duplicates.

This script identifies duplicates by "normalizing" titles to find
files that are exact matches or semantically similar.
For example, it can match "A Wink and a Smile" with
"1-04 F - 29_2_41 M - A Wink & A Smile".
"""

import os
import re
import argparse
from collections import defaultdict
from tinytag import TinyTag, TinyTagException

# Supported audio file extensions
AUDIO_EXTENSIONS = ('.mp3', '.flac', '.wav', '.m4a', '.ogg')


def normalize_title(title: str) -> str:
    """
    Cleans and standardizes a song title string for accurate comparison.
    """
    # Use rsplit to split on the *last* occurrence of " - " to handle complex prefixes.
    # For example: "1-04 F - 29_2_41 M - A Wink & A Smile"
    if ' - ' in title:
        title = title.rsplit(' - ', 1)[-1]

    # Standardize common connectors like '&'
    title = title.replace('&', 'and')

    # Convert to lowercase for case-insensitive matching
    title = title.lower()

    # Remove all punctuation and special characters
    title = re.sub(r'[^a-z0-9\s]', '', title)

    # Collapse multiple whitespace characters into one and trim ends
    title = re.sub(r'\s+', ' ', title).strip()

    return title


def _get_audio_titles(folder_path):
    """
    Scans a folder and extracts title metadata from audio files.
    """
    title_to_files = defaultdict(list)
    for filename in os.listdir(folder_path):
        file_path = os.path.join(folder_path, filename)

        is_audio_file = (os.path.isfile(file_path) and
                         filename.lower().endswith(AUDIO_EXTENSIONS))

        if is_audio_file:
            try:
                tag = TinyTag.get(file_path)
                if tag.title:
                    title_to_files[tag.title].append(file_path)
            except TinyTagException as e:
                print(f"Could not read metadata from {filename}: {e}")
    return title_to_files


def find_duplicates_normalized(title_to_files):
    """
    Finds duplicates using a normalized title representation.

    Args:
        title_to_files (dict): A dictionary mapping original titles to file paths.
    """
    print("\n--- Checking for Duplicates (using Normalization) ---")

    # Map normalized titles to a list of original titles and their files
    normalized_map = defaultdict(list)
    for original_title, files in title_to_files.items():
        normalized = normalize_title(original_title)
        if normalized:  # Ensure we don't process titles that become empty
            normalized_map[normalized].append((original_title, files))

    duplicates_found = False
    # Iterate through groups of titles that resolved to the same normalized string
    for normalized_key, groups in normalized_map.items():
        if len(groups) > 1:
            duplicates_found = True
            print(f"\nFound a group of similar titles (Normalized as: '{normalized_key}'):")
            # Each 'group' is a tuple of (original_title, file_list)
            for original_title, files in groups:
                print(f"  - Title: '{original_title}'")
                for file_path in files:
                    print(f"    - {file_path}")

    if not duplicates_found:
        print("No duplicate or similar titles were found.")


def main():
    """
    Parses command-line arguments and orchestrates the duplicate finding.
    """
    parser = argparse.ArgumentParser(
        description="Find audio files with duplicate or similar titles using normalization."
    )
    parser.add_argument(
        "folder_path",
        type=str,
        help="Path to the folder containing audio files."
    )

    args = parser.parse_args()

    if not os.path.isdir(args.folder_path):
        print(f"Error: Folder not found at '{args.folder_path}'")
        return

    # Scan files once and store the results
    title_map = _get_audio_titles(args.folder_path)

    if not title_map:
        print("No audio files with title metadata found in the folder.")
        return

    # Run the analysis function
    find_duplicates_normalized(title_map)


if __name__ == "__main__":
    main()
