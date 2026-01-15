#!/usr/bin/env python3
import os
import sys
import shlex
import locale
import copy
import argparse
from mutagen.id3 import (
    ID3, TIT2, TPE1, TALB, TCON, APIC,
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

def parse_arguments():
    """
    Parses command line arguments.
    """
    parser = argparse.ArgumentParser(description="Interactive MP3 ID3 tag editor.")
    parser.add_argument("folder", nargs="?", help="Folder containing MP3 files")
    parser.add_argument("--artist", help="Global Artist to apply")
    parser.add_argument("--album", help="Global Album to apply")
    parser.add_argument("--genre", help="Global Genre to apply")
    parser.add_argument("--remove-art", action="store_true", help="Remove all embedded cover art")
    parser.add_argument("--no-embed", action="store_true", help="Do not auto-embed cover art")
    return parser.parse_args()

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
    """
    Prompts user for input.
    - If user hits Enter, returns 'current_value'.
    - If user types something, returns that new value.
    """
    while True:
        user_input = input(f"{field_name.capitalize()} [{current_value}]: ").strip()
        result = user_input or current_value
        
        if result or allow_empty:
            return result
        print(f"  ⚠ {field_name.capitalize()} cannot be empty. Please enter a value.")

def configure_globals(args):
    """
    Interactively setup global overrides for Artist, Album, and Genre.
    Also asks about global art embedding preference.
    Only runs in Interactive Mode.
    """
    print("\n--- Global Settings Configuration ---")
    print("Set values here to apply them IMMEDIATELY to all files.")
    print("Leave empty to keep original file tags.\n")

    globals = {
        "artist": "",
        "album": "",
        "genre": ""
    }

    # Text Tags
    for field in ["artist", "album", "genre"]:
        prompt = f"Set global {field.capitalize()}? [y/N]: "
        choice = input(prompt).strip().lower()

        if choice == 'y':
             globals[field] = input(f"  Enter global {field.capitalize()}: ").strip()
    
    overrides = {k: v for k, v in globals.items() if v}

    # Cover Art Preference
    # Returns: 'yes' (all), 'no' (none), 'ask' (per file)
    print("-" * 40)
    print("Embed 'cover.jpg' if missing?")
    print("  [y]es  : Embed in ALL files immediately")
    print("  [n]o   : Do not embed in any file")
    print("  [a]sk  : Ask for each file individually")
    art_choice = input("Choice [a]: ").strip().lower()

    if art_choice.startswith('y'):
        overrides['_embed_mode'] = 'yes'
    elif art_choice.startswith('n'):
        overrides['_embed_mode'] = 'no'
    else:
        overrides['_embed_mode'] = 'ask'

    return overrides

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

def handle_save_exception(file_path, audio, error, auto_fix=False):
    """
    Handles exceptions during save. Checks for ReplayGain.
    If auto_fix is True, it removes ReplayGain without asking.
    """
    rg_keys = find_replaygain_keys(audio)
    
    if not rg_keys:
        print(f"  ⚠ Error saving {os.path.basename(file_path)}: {error}")
        return False

    if not auto_fix:
        print(f"\n⚠ Error saving {os.path.basename(file_path)}")
        print(f"  Reason: {error}")
        print(f"  Detected {len(rg_keys)} ReplayGain frame(s).")
        choice = input("  Remove ReplayGain tags and retry? [y]es / [n]o / [q]uit program: ").lower()
    else:
        choice = 'y' # Automatically say yes in batch mode

    if choice == 'q':
        print("Exiting program.")
        sys.exit(1)
    
    if choice == 'y':
        for key in rg_keys:
            audio.delall(key)
        
        try:
            audio.save(file_path, v2_version=3)
            if not auto_fix: print("  ✔ Retry successful.")
            return True
        except Exception as retry_err:
            print(f"  ✘ Retry failed: {retry_err}")
            return False
            
    return False

def write_file_changes(file_path, audio, tags, silent=False, auto_fix=False):
    """
    Attempts to write changes to a single file immediately.
    """
    apply_tags_to_audio(audio, tags)
    
    try:
        audio.save(file_path, v2_version=3)
        if not silent:
            print(f"✔ Saved: {os.path.basename(file_path)}")
        return True, None
    except Exception as e:
        if handle_save_exception(file_path, audio, e, auto_fix=auto_fix):
            return True, str(e)
        return False, None

def attach_cover_art(audio, file_path):
    """
    Checks for cover.jpg and attaches it to the audio object in memory.
    Returns True if art was added, False otherwise.
    Does NOT save the file.
    """
    cover_path = os.path.join(os.path.dirname(file_path), "cover.jpg")
    if not os.path.exists(cover_path):
        return False

    # Check if art already exists
    if audio.getall("APIC"):
        return False

    try:
        with open(cover_path, 'rb') as albumart:
            audio.add(APIC(
                encoding=3,
                mime='image/jpeg',
                type=3,
                desc='Cover',
                data=albumart.read()
            ))
        return True
    except Exception:
        return False 

def apply_batch_updates(files, global_overrides, remove_art=False, auto_embed=False):
    """
    Applies global overrides and optionally removes/adds art.
    """
    incident_log = []
    
    for file_path in files:
        audio, tags = load_tags(file_path)
        current_tags = copy.deepcopy(tags)
        
        changes_needed = False
        
        # 1. Apply Global Tags
        for key, val in global_overrides.items():
            # Skip internal control keys starting with _
            if key.startswith('_'): continue
            
            if val and current_tags[key] != val:
                current_tags[key] = val
                changes_needed = True
        
        # 2. Handle Art (Remove vs Embed)
        if remove_art:
            if audio.getall("APIC"):
                audio.delall("APIC")
                changes_needed = True
        elif auto_embed:
            # Only attempt to embed if requested
            if attach_cover_art(audio, file_path):
                changes_needed = True

        # 3. Save if needed
        if changes_needed:
            success, error_reason = write_file_changes(
                file_path, audio, current_tags, 
                silent=True, 
                auto_fix=True
            )
            if success and error_reason:
                incident_log.append({'file': file_path, 'reason': error_reason})
            elif success:
                print(f"Updated: {os.path.basename(file_path)}")

    return incident_log

def process_files_interactively(files, embed_mode='ask'):
    """
    Main loop: Iterates, edits, checks for changes, and writes immediately.
    embed_mode: 'yes' (handled in batch), 'no' (never), 'ask' (prompt user)
    """
    incident_log = []
    total_files = len(files)

    print(f"\n--- Starting Interactive Fine-Tuning ---")

    for index, file_path in enumerate(files, 1):
        audio, original_tags = load_tags(file_path)
        current_tags = copy.deepcopy(original_tags)

        # Check for cover art availability
        cover_path = os.path.join(os.path.dirname(file_path), "cover.jpg")
        can_embed = os.path.exists(cover_path)

        while True:
            print(f"\n--- File {index}/{total_files}: {os.path.basename(file_path)} ---")
            
            # Edit Tags
            current_tags["title"] = prompt_input("title", current_tags["title"], allow_empty=False)
            current_tags["artist"] = prompt_input("artist", current_tags["artist"])
            current_tags["album"] = prompt_input("album", current_tags["album"])
            current_tags["genre"] = prompt_input("genre", current_tags["genre"])

            # Art Logic (Ask per file)
            art_added_this_session = False
            has_art = True if audio.getall("APIC") else False

            if embed_mode == 'ask' and can_embed and not has_art:
                choice = input("   Embed 'cover.jpg'? [y/N]: ").strip().lower()
                if choice == 'y':
                    if attach_cover_art(audio, file_path):
                        art_added_this_session = True
                        has_art = True # Update for summary

            # Check for changes
            # Note: We must check if art was added, as tags might be identical
            if current_tags == original_tags and not art_added_this_session:
                choice = input("\n  ⚠ No changes detected. [s]kip / [e]dit again [s]: ").lower().strip()
                if choice == 'e':
                    continue
                else:
                    break 

            # Summary
            art_status = "Yes" if has_art else "No"
            
            print(f"\n   Summary for {os.path.basename(file_path)}:")
            print(f"     Title:   {current_tags['title']}")
            print(f"     Artist:  {current_tags['artist']}")
            print(f"     Album:   {current_tags['album']}")
            print(f"     Genre:   {current_tags['genre']}")
            print(f"     Has Art: {art_status}")

            # Confirm
            choice = input("\n   Write these changes? [y]es / [e]dit again / [q]uit: ").lower()

            if choice == 'y':
                success, error_reason = write_file_changes(file_path, audio, current_tags)
                if success and error_reason:
                    incident_log.append({'file': file_path, 'reason': error_reason})
                break 
                
            elif choice == 'e':
                # If user wants to edit again, and we added art in memory, 
                # we technically should revert it or reload, but simplest is 
                # to just continue (art is still attached to 'audio' object).
                # To be safe, we reload if they edit again to clear 'art_added_this_session'
                audio, _ = load_tags(file_path)
                continue
                
            elif choice == 'q':
                print("Exiting program.")
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

def main():
    args = parse_arguments()

    # --- 1. Mode Detection ---
    # Batch Mode if any tag arguments OR remove-art is set
    batch_mode = any([args.artist, args.album, args.genre, args.remove_art])

    # --- 2. Folder Validation ---
    if batch_mode and not args.folder:
        print("Error: --folder is required when providing tag/action arguments.")
        sys.exit(1)
    
    folder = args.folder
    if not folder and not batch_mode:
        folder = input("Folder containing MP3s: ").strip()

    if not os.path.isdir(folder):
        print(f"Error: Invalid folder '{folder}'")
        sys.exit(1)

    # --- 3. Scan Files ---
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

    # --- 4. Execution ---
    if batch_mode:
        # --- BATCH PATH ---
        print(f"Batch processing {len(files)} files...")
        global_overrides = {
            "artist": args.artist if args.artist else "",
            "album": args.album if args.album else "",
            "genre": args.genre if args.genre else ""
        }
        
        # Batch Mode determines embedding purely via flags
        auto_embed = not args.no_embed
        
        incident_log = apply_batch_updates(
            files, 
            global_overrides, 
            remove_art=args.remove_art,
            auto_embed=auto_embed
        )
        
        if incident_log:
            print_summary_report(incident_log)
        else:
            print("Batch update completed successfully.")
            
    else:
        # --- INTERACTIVE PATH ---
        global_overrides = configure_globals(args)
        
        # Extract the special Embed Mode key
        embed_mode = global_overrides.pop('_embed_mode', 'ask')
        
        incident_log = []
        if global_overrides or embed_mode == 'yes':
            print("\nApplying interactive global settings first...")
            
            # If user said 'yes' to embed globally, we do it here
            should_auto_embed = (embed_mode == 'yes')
            
            incident_log = apply_batch_updates(
                files, 
                global_overrides, 
                auto_embed=should_auto_embed
            )
            print("Globals applied.")

            print("\n" + "-"*60)
            choice = input("Continue to per-file editing? [y/N]: ").strip().lower()
            if choice != 'y':
                if incident_log: print_summary_report(incident_log)
                sys.exit(0)

        # Pass the embed_mode ('ask', 'no', 'yes') to the interactive loop
        # Note: if 'yes', art is already added, so loop will see has_art=True
        interactive_log = process_files_interactively(files, embed_mode=embed_mode)
        
        total_log = incident_log + interactive_log
        
        if total_log:
            print_summary_report(total_log)
        else:
            print("\nAll operations completed.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        sys.exit(0)
