#!/usr/bin/env python3
import os
import sys
import shlex
import locale
import copy
import argparse
import re
import base64
import subprocess
import mutagen
from mutagen.id3 import (
    ID3, TIT2, TPE1, TALB, TCON, APIC,
    ID3NoHeaderError
)
from mutagen.flac import FLAC, Picture as FlacPicture
from mutagen.oggvorbis import OggVorbis
from mutagen.oggopus import OggOpus
from mutagen.mp4 import MP4, MP4Cover

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
    parser = argparse.ArgumentParser(description="Interactive generic audio tag editor (MP3/FLAC/OGG/OPUS/M4A).")
    parser.add_argument("folder", nargs="?", help="Folder containing audio files")
    parser.add_argument("--artist", help="Global Artist to apply")
    parser.add_argument("--album", help="Global Album to apply")
    parser.add_argument("--genre", help="Global Genre to apply")
    parser.add_argument("--remove-art", action="store_true", help="Remove all embedded cover art")
    parser.add_argument("--embed", action="store_true", help="Auto-embed 'cover.jpg' if found (Opt-in)")
    parser.add_argument("--clean", action="store_true", help="Auto-clean non-printable chars in batch mode")
    parser.add_argument("--rename", action="store_true", help="Rename file based on Title tag (preserves track number)")
    return parser.parse_args()

def is_id3_based(audio):
    """
    Checks if the audio object uses ID3 tags (mainly MP3).
    """
    return isinstance(audio, ID3) or (hasattr(audio, 'tags') and isinstance(audio.tags, ID3))

def is_generic_title(title):
    """
    Returns True if the title matches generic patterns like 'Track 01' or 'Unknown'.
    """
    if not title or not title.strip():
        return True
    # Pattern to represent generic titles like 'track01', 'track 01', or 'unknown'
    pattern = re.compile(r'^(track\s*\d*|unknown)$', re.IGNORECASE)
    return bool(pattern.match(title.strip()))

def load_tags(file_path):
    """
    Loads tags from a file (MP3, FLAC, OGG, OPUS, M4A), returning the Mutagen object 
    and a dictionary of simplified tag values.
    """
    try:
        audio = mutagen.File(file_path)
    except Exception:
        return None, {}

    if audio is None:
        return None, {}

    tags = {
        "title": "", "artist": "", "album": "", "genre": ""
    }

    # --- MP3 / ID3 Logic ---
    if is_id3_based(audio):
        # Ensure tags exist
        container = audio.tags if hasattr(audio, 'tags') else audio
        if container is None:
            try: 
                audio.add_tags()
                container = audio.tags
            except Exception: 
                container = ID3()

        def get_text(frame_name):
            frames = container.getall(frame_name)
            if frames and frames[0].text:
                return frames[0].text[0]
            return ""

        tags["title"] = get_text("TIT2")
        tags["artist"] = get_text("TPE1")
        tags["album"] = get_text("TALB")
        tags["genre"] = get_text("TCON")

    # --- M4A / MP4 Logic ---
    elif isinstance(audio, MP4):
        # M4A uses specific atoms: \xa9nam (Title), \xa9ART (Artist), \xa9alb (Album), \xa9gen (Genre)
        def get_m4a_text(atom):
            return audio.tags.get(atom, [""])[0]

        tags["title"] = get_m4a_text("\xa9nam")
        tags["artist"] = get_m4a_text("\xa9ART")
        tags["album"] = get_m4a_text("\xa9alb")
        tags["genre"] = get_m4a_text("\xa9gen")

    # --- FLAC / Ogg / Vorbis / Opus Logic ---
    else:
        # Mutagen Dict-like access (keys are usually 'title', 'artist' etc.)
        def get_val(keys):
            for k in keys:
                if k in audio:
                    return str(audio[k][0])
            return ""

        tags["title"] = get_val(["title", "TITLE"])
        tags["artist"] = get_val(["artist", "ARTIST"])
        tags["album"] = get_val(["album", "ALBUM"])
        tags["genre"] = get_val(["genre", "GENRE"])

    return audio, tags

def find_replaygain_keys(audio):
    """
    Returns a list of ReplayGain keys present in the audio object.
    """
    keys_found = []
    
    # ID3 TXXX Frames or Vorbis Comments
    if hasattr(audio, 'keys'):
        for key in audio.keys():
            if key.lower().startswith("txxx:replaygain"):
                keys_found.append(key)
            elif key.lower().startswith("replaygain_"):
                keys_found.append(key)
                
    return keys_found

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

def sanitize_filename(text):
    """
    Sanitizes text for use as a filename.
    Removes characters invalid in most filesystems.
    """
    if not text:
        return ""
    # Remove / \ : * ? " < > |
    return re.sub(r'[\\/*?:"<>|]', "", text).strip()

def rename_file_based_on_title(file_path, title):
    """
    Renames file to 'Track - Title.ext' or 'Title.ext' based on provided title.
    Preserves leading track number if present in original filename.
    Returns the new file path (or original if no change).
    """
    if not title:
        return file_path

    directory = os.path.dirname(file_path)
    filename = os.path.basename(file_path)
    base, ext = os.path.splitext(filename)
    
    clean_title = sanitize_filename(title)
    if not clean_title:
        return file_path

    # Check for track number prefix (e.g. "01 - ", "01. ", "01 ")
    # Restored original [ \s.-]* behavior to capture leading digits
    match = re.match(r'^(\d+)[\s.-]*', base)
    
    if match:
        track_num = match.group(1)
        new_filename = f"{track_num} - {clean_title}{ext}"
    else:
        new_filename = f"{clean_title}{ext}"

    if new_filename != filename:
        new_path = os.path.join(directory, new_filename)
        try:
            os.rename(file_path, new_path)
            print(f"  ➜ Renamed: {filename} -> {new_filename}")
            return new_path
        except OSError as e:
            print(f"  ✘ Error renaming {filename}: {e}")
            return file_path
            
    return file_path

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
    """
    Helper to modify the audio object in memory (does not save).
    """
    # --- MP3 / ID3 Logic ---
    if is_id3_based(audio):
        container = audio.tags if hasattr(audio, 'tags') else audio
        if container is None: return # Should not happen

        container.delall("TIT2")
        container.delall("TPE1")
        container.delall("TALB")
        container.delall("TCON")

        if tags["title"]: container.add(TIT2(encoding=3, text=tags["title"]))
        if tags["artist"]: container.add(TPE1(encoding=3, text=tags["artist"]))
        if tags["album"]: container.add(TALB(encoding=3, text=tags["album"]))
        if tags["genre"]: container.add(TCON(encoding=3, text=tags["genre"]))
    
    # --- M4A / MP4 Logic ---
    elif isinstance(audio, MP4):
        # M4A uses specific atoms: \xa9nam, \xa9ART, \xa9alb, \xa9gen
        mapping = {
            "title": "\xa9nam",
            "artist": "\xa9ART",
            "album": "\xa9alb",
            "genre": "\xa9gen"
        }
        for key, atom in mapping.items():
            if tags[key]:
                audio.tags[atom] = [tags[key]]
            elif atom in audio.tags:
                del audio.tags[atom]

    # --- FLAC / Ogg / Vorbis / Opus Logic ---
    else:
        # Standard Vorbis comments
        mapping = {
            "title": "title", 
            "artist": "artist", 
            "album": "album", 
            "genre": "genre"
        }
        
        for key, vorbis_key in mapping.items():
            if tags[key]:
                # Overwrite existing
                audio[vorbis_key] = tags[key]
            elif vorbis_key in audio:
                # Remove empty tags to keep it clean
                del audio[vorbis_key]

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
        # Remove ID3 TXXX frames or Vorbis keys
        if is_id3_based(audio):
            container = audio.tags if hasattr(audio, 'tags') else audio
            for key in rg_keys:
                container.delall(key)
        else:
            for key in rg_keys:
                if key in audio:
                    del audio[key]
        
        try:
            # Generic save for all types
            # v2_version arg is only supported by ID3 save, others might error
            if is_id3_based(audio):
                audio.save(file_path, v2_version=3)
            else:
                audio.save(file_path)

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
        if is_id3_based(audio):
            audio.save(file_path, v2_version=3)
        else:
            audio.save(file_path)
            
        if not silent:
            print(f"✔ Saved: {os.path.basename(file_path)}")
        return True, None
    except Exception as e:
        if handle_save_exception(file_path, audio, e, auto_fix=auto_fix):
            return True, str(e)
        return False, None

def get_optimized_cover_art(directory):
    """
    Ensures 'cover_embed.jpg' exists and is up-to-date relative to 'cover.jpg'.
    Resizes 'cover.jpg' to max 600x600 using ffmpeg if needed.
    Returns path to 'cover_embed.jpg' if available, else None.
    """
    master_path = os.path.join(directory, "cover.jpg")
    embed_path = os.path.join(directory, "cover_embed.jpg")

    # If no master exists, check if we have an orphan embed to fallback on
    if not os.path.exists(master_path):
        if os.path.exists(embed_path):
            return embed_path 
        return None

    # Check if we need to regenerate
    needs_update = False
    if not os.path.exists(embed_path):
        needs_update = True
    else:
        # Check timestamps: if master is newer than embed
        if os.path.getmtime(master_path) > os.path.getmtime(embed_path):
            needs_update = True
            
    if needs_update:
        try:
            # ffmpeg -i input -vf scale=600:600:force_original_aspect_ratio=decrease -y output
            cmd = [
                'ffmpeg', '-i', master_path,
                '-vf', 'scale=600:600:force_original_aspect_ratio=decrease',
                '-y', # Overwrite without asking
                '-loglevel', 'error', # Quiet
                embed_path
            ]
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print(f"  ➜ Generated optimized art: cover_embed.jpg")
        except (subprocess.CalledProcessError, FileNotFoundError):
            print("  ⚠ Failed to resize cover art using ffmpeg. Skipping embed.")
            return None

    return embed_path

def attach_cover_art(audio, file_path):
    """
    Checks for cover art (optimizing it if needed) and attaches it.
    Returns True if art was added, False otherwise.
    Does NOT save the file.
    """
    directory = os.path.dirname(file_path)
    
    # Retrieve optimized path (generates it if missing/stale)
    cover_path = get_optimized_cover_art(directory)
    
    if not cover_path or not os.path.exists(cover_path):
        return False

    try:
        with open(cover_path, 'rb') as f:
            image_data = f.read()
    except IOError:
        return False

    # --- MP3 Logic ---
    if is_id3_based(audio):
        container = audio.tags if hasattr(audio, 'tags') else audio
        if container.getall("APIC"): return False # Already exists
        container.add(APIC(
            encoding=3,
            mime='image/jpeg',
            type=3,
            desc='Cover',
            data=image_data
        ))
        return True

    # --- M4A / MP4 Logic ---
    elif isinstance(audio, MP4):
        # M4A stores art in 'covr' atom as a list of MP4Cover objects
        if "covr" in audio.tags: return False # Already exists
        
        # We assume JPEG because get_optimized_cover_art always produces JPEGs
        cover = MP4Cover(image_data, imageformat=MP4Cover.FORMAT_JPEG)
        audio.tags["covr"] = [cover]
        return True

    # --- FLAC Logic ---
    elif isinstance(audio, FLAC):
        if audio.pictures: return False # Already exists
        p = FlacPicture()
        p.type = 3
        p.mime = 'image/jpeg'
        p.desc = 'Cover'
        p.data = image_data
        audio.add_picture(p)
        return True

    # --- Ogg Vorbis / Opus Logic ---
    elif isinstance(audio, (OggVorbis, OggOpus)):
        # Ogg stores art in the metadata block encoded as base64
        if 'metadata_block_picture' in audio: return False
        
        p = FlacPicture()
        p.type = 3
        p.mime = 'image/jpeg'
        p.desc = 'Cover'
        p.data = image_data
        
        # Write picture to base64 string
        picture_data = p.write()
        base64_data = base64.b64encode(picture_data).decode('ascii')
        
        audio["metadata_block_picture"] = [base64_data]
        return True

    return False 

def apply_batch_updates(files, global_overrides, remove_art=False, auto_embed=False, auto_clean=False, rename_files=False):
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
        if audio is None:
            continue

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
            if is_id3_based(audio):
                container = audio.tags if hasattr(audio, 'tags') else audio
                if container.getall("APIC"):
                    container.delall("APIC")
                    changes_needed = True
            elif isinstance(audio, MP4):
                if "covr" in audio.tags:
                    del audio.tags["covr"]
                    changes_needed = True
            elif isinstance(audio, FLAC):
                if audio.pictures:
                    audio.clear_pictures()
                    changes_needed = True
            elif isinstance(audio, (OggVorbis, OggOpus)):
                if 'metadata_block_picture' in audio:
                    del audio['metadata_block_picture']
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

        # 4. Rename File from Title
        # We do this AFTER saving so the file contains the correct tags before rename
        if rename_files or current_tags['title']:
            file_path = rename_file_based_on_title(file_path, current_tags['title'])

    return incident_log

def process_files_interactively(files, embed_mode='ask', rename_files=False):
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
        if audio is None:
            print(f"Skipping unsupported file: {current_filename}")
            continue
            
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
        # We check for EITHER the master cover.jpg OR an existing optimized version
        can_embed = os.path.exists(os.path.join(directory, "cover.jpg")) or \
                    os.path.exists(os.path.join(directory, "cover_embed.jpg"))

        while True:
            print(f"\n--- File {index}/{total_files}: {current_filename} ---")
            
            # Edit Tags
            current_tags["title"] = prompt_input("title", current_tags["title"], allow_empty=False)
            current_tags["artist"] = prompt_input("artist", current_tags["artist"])
            current_tags["album"] = prompt_input("album", current_tags["album"])
            current_tags["genre"] = prompt_input("genre", current_tags["genre"])

            # Art Logic (Ask per file)
            art_added_this_session = False
            
            # Check for art existence based on type
            has_art = False
            if is_id3_based(audio):
                container = audio.tags if hasattr(audio, 'tags') else audio
                has_art = bool(container.getall("APIC"))
            elif isinstance(audio, MP4):
                has_art = "covr" in audio.tags
            elif isinstance(audio, FLAC):
                has_art = bool(audio.pictures)
            elif isinstance(audio, (OggVorbis, OggOpus)):
                has_art = 'metadata_block_picture' in audio

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
                
                # Automatic Rename (No prompt)
                # Renames happens after save to ensure safe state
                if current_tags['title']:
                    rename_file_based_on_title(file_path, current_tags['title'])
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
    batch_mode = any([args.artist, args.album, args.genre, args.remove_art, args.rename, args.embed])

    # --- 2. Folder Validation ---
    if batch_mode and not args.folder:
        print("Error: --folder is required when providing tag/action arguments.")
        sys.exit(1)
    
    folder = args.folder
    if not folder and not batch_mode:
        folder = input("Folder containing audio files: ").strip()

    if not os.path.isdir(folder):
        print(f"Error: Invalid folder '{folder}'")
        sys.exit(1)

    # --- 3. Scan Files ---
    supported_exts = (".mp3", ".flac", ".ogg", ".opus", ".m4a")
    try:
        files = sorted([
            os.path.join(folder, f)
            for f in os.listdir(folder)
            if f.lower().endswith(supported_exts)
        ], key=locale.strxfrm)
    except Exception:
        files = sorted([
            os.path.join(folder, f)
            for f in os.listdir(folder)
            if f.lower().endswith(supported_exts)
        ])

    if not files:
        print("No supported audio files (MP3/FLAC/OGG/OPUS/M4A) found.")
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
        auto_embed = args.embed
        
        incident_log = apply_batch_updates(
            files, 
            global_overrides, 
            remove_art=args.remove_art,
            auto_embed=auto_embed,
            auto_clean=args.clean,
            rename_files=args.rename
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
                auto_clean=args.clean,
                rename_files=args.rename
            )
            print("Globals applied.")

            print("\n" + "-"*60)
            choice = input("Continue to per-file editing? [y/N]: ").strip().lower()
            if choice != 'y':
                if incident_log: print_summary_report(incident_log)
                sys.exit(0)

        # Pass the embed_mode ('ask', 'no', 'yes') to the interactive loop
        # Note: if 'yes', art is already added, so loop will see has_art=True
        interactive_log = process_files_interactively(files, embed_mode=embed_mode, rename_files=args.rename)
        
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
