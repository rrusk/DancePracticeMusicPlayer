#!/usr/bin/env python3
import os
import sys
import shlex
import locale
import copy
import argparse
import re
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
    parser.add_argument("--clean", action="store_true", help="Auto-clean non-printable chars in batch mode")
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

def fix_encoding_mismatch(text):
    """
    Attempts to fix 'Mojibake' where Latin-1/Windows-1252 bytes were 
    incorrectly decoded as UTF-8 (resulting in surrogates or garbage).
    Returns the fixed text if successful, or the original text if not.
    """
    try:
        # 1. Reverse the UTF-8 decode using 'surrogateescape' to get original bytes
        #    (This works if the OS loaded the filename with surrogates for invalid bytes)
        raw_bytes = text.encode('utf-8', 'surrogateescape')
        
        # Guard clause: If the bytes contain the UTF-8 replacement char sequence (EF BF BD),
        # decoding them as cp1252 produces "ï¿½", which is garbage. Ignore this case.
        if b'\xef\xbf\xbd' in raw_bytes:
            return text
        
        # 2. Re-decode using Windows-1252 (covers Latin-1 + extra chars)
        fixed_text = raw_bytes.decode('cp1252')
        
        # 3. Verify the fix actually changed something and looks valid
        if fixed_text != text:
            return fixed_text
    except Exception:
        pass
    return text

def has_garbage(text):
    """
    Checks for Unicode Replacement Character, Surrogates, or non-printable chars.
    """
    if not text:
        return False
    if '\ufffd' in text:  # The replacement character
        return True
    
    # Check for surrogate characters (indicating encoding errors on Linux)
    # Surrogates range from 0xD800 to 0xDFFF
    for char in text:
        if 0xD800 <= ord(char) <= 0xDFFF:
            return True
            
    # Check for other control characters (keeping standard whitespace)
    return any(not c.isprintable() for c in text)

def strip_garbage(text):
    """
    Removes \ufffd and non-printable characters.
    Used primarily in batch mode as a fallback.
    """
    if not text:
        return ""
    
    # Try fixing encoding first!
    fixed = fix_encoding_mismatch(text)
    if not has_garbage(fixed):
        return fixed
        
    # If still garbage, strip it
    clean = text.replace('\ufffd', '')
    return "".join(c for c in clean if c.isprintable()).strip()

def remove_track_number(text):
    """
    Removes leading track numbers (e.g. "01 - ", "12. ") from the text.
    """
    if not text:
        return text
    # Match start, 1+ digits, separator characters (space . -), then more text
    # This handles "01 - Title", "01. Title", "01 Title"
    return re.sub(r'^\d+[\s.-]+', '', text).strip()

def repair_string(text):
    """
    Interactively repairs a string by stopping at invalid characters 
    and asking the user for a replacement.
    """
    # 1. First, try to auto-fix the encoding (Latin-1 -> UTF-8)
    fixed_attempt = fix_encoding_mismatch(text)
    
    if fixed_attempt != text and not has_garbage(fixed_attempt):
        print(f"  ⚠ Detected potential encoding error (e.g. Latin-1 decoded as UTF-8).")
        print(f"  Proposed fix: '{text}'  -->  '{fixed_attempt}'")
        choice = input("  Accept this fix? [Y/n]: ").strip().lower()
        if choice == '' or choice == 'y':
            return fixed_attempt

    if not has_garbage(text):
        return text

    print(f"\n  Original String: '{text}'")
    print("  ⚠ Invalid characters detected. Starting interactive repair...")
    
    chars = list(text)
    repaired_chars = []
    
    for i, char in enumerate(chars):
        if has_garbage(char):
            # Print context up to the bad character
            so_far = "".join(repaired_chars)
            print(f"  Valid so far:    \"{so_far}\"")
            
            # Prompt for replacement
            # Showing hex allows user to identify if it's a specific invisible char
            bad_hex = hex(ord(char))
            prompt = f"  Replace invalid char ({bad_hex}) with [Enter to delete]: "
            replacement = input(prompt)
            
            if replacement:
                repaired_chars.append(replacement)
        else:
            repaired_chars.append(char)
            
    return "".join(repaired_chars)

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

def apply_batch_updates(files, global_overrides, remove_art=False, auto_embed=False, auto_clean=False):
    """
    Applies global overrides and optionally removes/adds art.
    """
    incident_log = []
    
    for file_path in files:
        # Pre-cleanup in batch mode if requested
        if auto_clean:
            fname = os.path.basename(file_path)
            
            # Try to smart-fix encoding first, then strip if that fails
            if has_garbage(fname):
                clean_name = strip_garbage(fname)
                if clean_name != fname:
                    try:
                        new_path = os.path.join(os.path.dirname(file_path), clean_name)
                        os.rename(file_path, new_path)
                        print(f"Renamed: {fname} -> {clean_name}")
                        file_path = new_path
                    except OSError as e:
                        print(f"Error renaming {fname}: {e}")

        audio, tags = load_tags(file_path)
        current_tags = copy.deepcopy(tags)
        
        changes_needed = False
        
        # Cleanup Title in batch mode
        if auto_clean and has_garbage(current_tags['title']):
             current_tags['title'] = strip_garbage(current_tags['title'])
             changes_needed = True
        
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
        # ---------------------------------------------------------
        # 1. Clean Garbage Characters (Iterative Repair)
        # ---------------------------------------------------------

        # Separate Filename from Extension
        directory = os.path.dirname(file_path)
        current_filename = os.path.basename(file_path)
        name_root, ext = os.path.splitext(current_filename)

        filename_was_changed = False

        # Check Filename
        if has_garbage(name_root):
            print(f"\n⚠ Encoding issues detected in Filename {index}/{total_files}")
            new_root = repair_string(name_root)

            if new_root != name_root:
                new_filename = new_root + ext
                new_path = os.path.join(directory, new_filename)

                try:
                    os.rename(file_path, new_path)
                    print(f"  ✔ File renamed to: {new_filename}")
                    file_path = new_path
                    filename_was_changed = True
                    # Update variable for this iteration
                    current_filename = new_filename
                    name_root = new_root
                except OSError as e:
                    print(f"  ✘ Rename failed: {e}")

        # Load Tags (from potentially renamed file)
        audio, original_tags = load_tags(file_path)
        current_tags = copy.deepcopy(original_tags)

        # Sync Filename to Title or Repair Title
        if filename_was_changed:
            # Smart Logic: remove track number before suggesting title
            suggested_title = remove_track_number(name_root)
            
            print(f"  Title currently: '{current_tags['title']}'")
            prompt = f"  Use cleaned filename '{suggested_title}' for Track Title? [Y/n]: "
            choice = input(prompt).strip().lower()
            if choice == '' or choice == 'y':
                current_tags['title'] = suggested_title
            elif has_garbage(current_tags['title']):
                # User said No, but title is dirty, so repair it manually
                current_tags['title'] = repair_string(current_tags['title'])
        else:
            # Filename wasn't changed, but title might be dirty
            if has_garbage(current_tags['title']):
                print(f"\n⚠ Encoding issues detected in Track Title")
                current_tags['title'] = repair_string(current_tags['title'])

        # ---------------------------------------------------------
        # 2. Standard Tag Editing
        # ---------------------------------------------------------

        # Check for cover art availability
        cover_path = os.path.join(os.path.dirname(file_path), "cover.jpg")
        can_embed = os.path.exists(cover_path)

        while True:
            print(f"\n--- File {index}/{total_files}: {current_filename} ---")
            
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
            tags_changed = (current_tags != original_tags)

            if not tags_changed and not art_added_this_session:
                choice = input("\n  ⚠ No changes detected. [s]kip / [e]dit again [s]: ").lower().strip()
                if choice == 'e':
                    continue
                else:
                    break 

            # Summary
            art_status = "Yes" if has_art else "No"
            
            print(f"\n   Summary for {current_filename}:")
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
            auto_embed=auto_embed,
            auto_clean=args.clean
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
                auto_embed=should_auto_embed,
                auto_clean=args.clean
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
