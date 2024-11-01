#!/usr/bin/env python3
# -*- encoding: utf-8 -*-
#

import os
import argparse
from tinytag import TinyTag
from collections import defaultdict

def find_files_with_similar_titles(folder_path, min_length):
    # Dictionary to store titles and corresponding file paths
    title_to_files = defaultdict(list)

    # Loop through each file in the folder
    for filename in os.listdir(folder_path):
        file_path = os.path.join(folder_path, filename)

        # Check if it's a file (not a directory) and if it's an audio file
        if os.path.isfile(file_path) and filename.lower().endswith(('.mp3', '.flac', '.wav', '.m4a', '.ogg')):
            try:
                # Extract metadata
                tag = TinyTag.get(file_path)
                if tag.title:  # Only consider files with a title tag
                    title_to_files[tag.title].append(file_path)
            except Exception as e:
                print(f"Error reading {filename}: {e}")

    # Find and display files with similar titles
    similar_titles_found = False
    titles = list(title_to_files.keys())
    
    for i in range(len(titles)):
        for j in range(i + 1, len(titles)):
            title1, title2 = titles[i].lower(), titles[j].lower()
            
            # Check if one title is a substring of the other and meets the minimum length
            if (title1 in title2 and len(title1) >= min_length) or (title2 in title1 and len(title2) >= min_length):
                similar_titles_found = True
                print(f"\nSimilar Titles Found:")
                print(f" - Title '{titles[i]}' in files:")
                for file in title_to_files[titles[i]]:
                    print(f"    {file}")
                print(f" - Title '{titles[j]}' in files:")
                for file in title_to_files[titles[j]]:
                    print(f"    {file}")

    if not similar_titles_found:
        print("No files with similar titles found.")

# Set up command-line argument parsing
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Find audio files with similar titles in a specified folder.")
    parser.add_argument("folder_path", type=str, nargs="?", help="Path to the folder containing audio files")
    parser.add_argument("--min_length", type=int, default=10, help="Minimum length of substring for titles to be considered similar")

    args = parser.parse_args()

    if not args.folder_path:
        print("Error: No folder path provided. Please specify the path to the folder containing audio files.")
    else:
        find_files_with_similar_titles(args.folder_path, args.min_length)

