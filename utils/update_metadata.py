#!/usr/bin/env python3
import os
import sys
import shlex
import locale
import copy
from mutagen.id3 import (
    ID3, TIT2, TPE1, TALB, TCON,
    ID3NoHeaderError
)

# -----------------------------------------------------------------------------
# Configuration & Setup
# -----------------------------------------------------------------------------

try:
    locale.setlocale(locale.LC_ALL, '')
except locale.Error:
    pass

# -----------------------------------------------------------------------------
# Core Logic
# -----------------------------------------------------------------------------

def load_tags(file_path):
    """
    Loads ID3 tags from a file, returning the ID3 object and a dictionary
    of simplified tag values.
    """
    try:
        audio = ID3(file_path)
    except ID3NoHeaderError:
        audio = ID3()

    def get_text(frame_name):
        frames = audio.getall(frame_name)
        if frames and frames[0].text:
            return frames[0].text[0]
        return ""

    tags = {
        "title": get_text("TIT2"),
        "artist": get_text("TPE1"),
        "album": get_text("TALB"),
        "genre": get_text("TCON"),
    }
    return audio, tags

def find_replaygain_keys(audio):
    """Returns a list of ReplayGain TXXX keys present in the audio object."""
    return [
        key for key in audio.keys()
        if key.lower().startswith("txxx:replaygain")
    ]

def prompt_input(field_name, current_value, allow_empty=True):
    while True:
        user_input = input(f"{field_name.capitalize()} [{current_value}]: ").strip()
        result = user_input or current_value
        
        if result or allow_empty:
            return result
        print(f"  ⚠ {field_name.capitalize()} cannot be empty. Please enter a value.")

def apply_tags_to_audio(audio, tags):
    """Helper to modify the ID3 object in memory (does not save)."""
    audio.delall("TIT2")
    audio.delall("TPE1")
    audio.delall("TALB")
    audio.delall("TCON")

    if tags["title"]: audio.add(TIT2(encoding=3, text=tags["title"]))
    if tags["artist"]: audio.add(TPE1(encoding=3, text=tags["artist"]))
    if tags["album"]: audio.add(TALB(encoding=3, text=tags["album"]))
    if tags["genre"]: audio.add(TCON(encoding=3, text=tags["genre"]))

def handle_save_exception(file_path, audio, error):
    """
    Handles exceptions during save. Checks for ReplayGain and prompts user.
    Returns True if retry was successful (and ReplayGain was removed), False otherwise.
    """
    print(f"\n⚠ Error saving {os.path.basename(file_path)}")
    print(f"  Reason: {error}")
    
    rg_keys = find_replaygain_keys(audio)
    
    if not rg_keys:
        print("  No ReplayGain tags detected to clean up.")
        return False

    print(f"  Detected {len(rg_keys)} ReplayGain frame(s). These may be causing corruption.")
    choice = input("  Remove ReplayGain tags and retry? [y]es / [n]o / [q]uit program: ").lower()

    if choice == 'q':
        print("Exiting program.")
        sys.exit(1)
    
    if choice == 'y':
        for key in rg_keys:
            audio.delall(key)
        
        try:
            audio.save(file_path, v2_version=3)
            print("  ✔ Retry successful.")
            return True
        except Exception as retry_err:
            print(f"  ✘ Retry failed: {retry_err}")
            return False
            
    return False

def write_file_changes(file_path, audio, tags):
    """
    Attempts to write changes to a single file immediately.
    Returns: (success: bool, error_reason: str|None)
    If error_reason is returned, it means we had to clean the file.
    """
    apply_tags_to_audio(audio, tags)
    
    try:
        audio.save(file_path, v2_version=3)
        print(f"✔ Saved: {os.path.basename(file_path)}")
        return True, None
    except Exception as e:
        # If this returns True, it means we successfully cleaned and saved
        if handle_save_exception(file_path, audio, e):
            return True, str(e) # Return the original error reason for the log
        return False, None

def process_files_interactively(files):
    """
    Main loop: Iterates, edits, checks for changes, and writes immediately.
    Returns the incident log.
    """
    incident_log = []
    total_files = len(files)

    for index, file_path in enumerate(files, 1):
        audio, original_tags = load_tags(file_path)
        
        # Deep copy to allow comparison later
        current_tags = copy.deepcopy(original_tags)

        # Per-song Edit/Confirm Loop
        while True:
            print(f"\n--- File {index}/{total_files}: {os.path.basename(file_path)} ---")
            
            # 1. Edit Tags
            current_tags["title"] = prompt_input("title", current_tags["title"], allow_empty=False)
            current_tags["artist"] = prompt_input("artist", current_tags["artist"])
            current_tags["album"] = prompt_input("album", current_tags["album"])
            current_tags["genre"] = prompt_input("genre", current_tags["genre"])

            # 2. Check for changes logic
            if current_tags == original_tags:
                # Ask user what to do since no changes were found
                choice = input("\n  ⚠ No changes detected. [s]kip / [e]dit again [s]: ").lower().strip()
                
                if choice == 'e':
                    print("   Re-editing...")
                    continue  # Restart the loop for this file
                else:
                    # Default is 's' (skip) on empty string or explicit 's'
                    print("   Skipping file...")
                    break  # Break inner loop, move to next file

            # 3. Show Summary (only if changes exist)
            print(f"\n   Summary for {os.path.basename(file_path)}:")
            print(f"     Title:  {current_tags['title']}")
            print(f"     Artist: {current_tags['artist']}")
            print(f"     Album:  {current_tags['album']}")
            print(f"     Genre:  {current_tags['genre']}")

            # 4. Confirm & Write Immediately
            choice = input("\n   Write these changes? [y]es / [e]dit again / [q]uit: ").lower()

            if choice == 'y':
                success, error_reason = write_file_changes(file_path, audio, current_tags)
                
                if success and error_reason:
                    incident_log.append({
                        'file': file_path,
                        'reason': error_reason
                    })
                break  # Move to next file
                
            elif choice == 'e':
                print("   Re-editing...")
                continue
                
            elif choice == 'q':
                print("Exiting program.")
                # We return whatever logs we collected so far before exiting
                if incident_log:
                    print_summary_report(incident_log)
                sys.exit(0)
    
    return incident_log

def print_summary_report(incident_log):
    if not incident_log:
        return

    print("\n" + "="*40)
    print("=== ReplayGain Action Required ===")
    print("="*40)
    
    print("\nReplayGain tags were removed from the following files due to write errors:\n")

    for entry in incident_log:
        fname = os.path.basename(entry['file'])
        print(f"• {fname}")
        print(f"  Reason: {entry['reason']}")
    
    print("\n" + "-"*40)
    print("To restore ReplayGain for these files, run:")
    print("-"*40 + "\n")

    print("mp3gain -r -d 3 -c \\")
    
    count = len(incident_log)
    for i, entry in enumerate(incident_log):
        suffix = " \\" if i < count - 1 else ""
        quoted_file = shlex.quote(entry['file'])
        print(f"  {quoted_file}{suffix}")

    print("\n(Verify 'mp3gain' is installed and in your PATH)")

def main():
    folder = input("Folder containing MP3s: ").strip()
    if not os.path.isdir(folder):
        print("Invalid folder.")
        return

    try:
        files = sorted([
            os.path.join(folder, f)
            for f in os.listdir(folder)
            if f.lower().endswith(".mp3")
        ], key=locale.strxfrm)
    except Exception:
        files = sorted([
            os.path.join(folder, f)
            for f in os.listdir(folder)
            if f.lower().endswith(".mp3")
        ])

    if not files:
        print("No MP3 files found.")
        return

    incident_log = process_files_interactively(files)
    
    if incident_log:
        print_summary_report(incident_log)
    else:
        print("\nAll operations completed.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        sys.exit(0)
