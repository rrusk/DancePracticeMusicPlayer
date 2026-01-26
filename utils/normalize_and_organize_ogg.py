#!/usr/bin/env python3
# -*- encoding: utf-8 -*-
"""
Music Ingest Pipeline (Safe Edition with Pre-Flight Check)

Features:
1. PRE-FLIGHT CHECK: Scans for filename collisions BEFORE processing audio.
   - User can abort if duplicate tags are found.
2. ATOMIC WRITES: Writes to .part.ogg first, renames only on success. 
   (Prevents corrupt files from being skipped on restart).
3. BUG FIX: Clears ffmpeg queue to prevent infinite processing loops.
4. RESUME: Skips files that already exist in the destination.
5. PROCESSING: Normalizes to -14 LUFS, Ogg Vorbis Q7, 44.1kHz.
6. METADATA: Smart Titling, NTFS cleaning, Raw Genre.
"""

import os
import sys
import re
import shutil
from datetime import datetime

# Third-party libraries
try:
    import mutagen
    from ffmpeg_normalize import FFmpegNormalize
except ImportError:
    print("Missing libraries. Please run: pip install ffmpeg-normalize mutagen")
    sys.exit(1)

def smart_title(s):
    """
    Title cases text but fixes standard Python issues with apostrophes.
    Standard .title() turns "Don't" into "Don'T". This fixes it.
    
    Args:
        s (str): The input string.
    
    Returns:
        str: The smart-title-cased string.
    """
    if not s:
        return ""
    
    # 1. Apply standard Title Case first
    s = str(s).title()
    
    # 2. Fix contractions using Regex
    # Pattern: (Letter) + ' + (Uppercase Letter) -> Lowercase the second letter
    # Example: Matches "n'T" in "Don'T" -> "n't"
    return re.sub(r"([a-zA-Z])'([A-Z])", lambda m: m.group(1) + "'" + m.group(2).lower(), s)

def clean_filename(s):
    """
    Sanitizes filenames for NTFS compatibility and readability.
    
    Logic:
    1. Replace illegal NTFS chars with Underscore (_)
    2. Remove spaces (User preference for compact naming)
    3. Collapse repeated delimiters (e.g., '__' becomes '_')
    4. Truncate to 255 chars
    
    Args:
        s (str): The raw filename string.
        
    Returns:
        str: The sanitized filename.
    """
    #
    ILLEGAL_NTFS_CHARS = r'[<>:/\\|?*"]|[\0-\31]'
    
    # Step A: Replace illegal chars with Underscore (Visual best practice)
    s = re.sub(ILLEGAL_NTFS_CHARS, "_", s)
    
    # Step B: Remove spaces (Compact naming)
    s = s.replace(" ", "")
    
    # Step C: Cleanup - prevent double underscores
    # Example: "Song: Title" -> "Song__Title" -> "Song_Title"
    s = re.sub(r'_+', '_', s)
    
    return s[:255]

def get_metadata(filepath):
    """
    Reads tags using Mutagen. 
    - Genre is kept RAW to preserve formatting like 'mpm'.
    - Artist/Album/Title are processed with smart_title().
    """
    try:
        f = mutagen.File(filepath, easy=True)
        
        def get_tag_raw(tag_name, default):
            if f and tag_name in f:
                return str(f[tag_name][0])
            return default

        # Get raw values
        raw_genre = get_tag_raw("genre", "UnknownGenre")
        raw_artist = get_tag_raw("artist", "UnknownArtist")
        raw_album = get_tag_raw("album", "UnknownAlbum")
        raw_title = get_tag_raw("title", "UnknownTitle")

        return {
            "genre": raw_genre,                 # KEEP RAW (Fixes 'mpm' casing)
            "artist": smart_title(raw_artist),  # Smart Casing (Fixes "I'll")
            "album": smart_title(raw_album),    # Smart Casing
            "title": smart_title(raw_title),    # Smart Casing
        }
    except Exception as e:
        # Suppress warning to keep pre-flight check clean, or enable for debugging
        # print(f"Warning: Could not read metadata for {filepath}: {e}")
        return {
            "genre": "UnknownGenre", 
            "artist": "UnknownArtist", 
            "album": "UnknownAlbum", 
            "title": "UnknownTitle"
        }

# --- PRE-FLIGHT CHECK ---

def check_collisions(src_dir):
    """
    Scans the library to simulate filename generation.
    Returns True if collisions are found, False otherwise.
    """
    print(f"Performing Pre-Flight Collision Check on {src_dir}...")
    
    supported_exts = ('.flac', '.ogg', '.m4a', '.opus', '.wav')
    mapping = {}
    collisions_found = 0
    
    for root, dirs, files in os.walk(src_dir):
        for name in files:
            if not name.lower().endswith(supported_exts):
                continue
            
            input_path = os.path.join(root, name)
            
            # Simulate naming logic
            meta = get_metadata(input_path)
            base_name = f"{meta['genre']}-{meta['album']}_{meta['title']}_{meta['artist']}"
            clean_name = clean_filename(base_name)
            output_filename = f"{clean_name}.ogg"
            
            if output_filename not in mapping:
                mapping[output_filename] = []
            mapping[output_filename].append(input_path)

    # Report Results
    for out_file, sources in mapping.items():
        if len(sources) > 1:
            collisions_found += 1
            print("="*60)
            print(f"COLLISION DETECTED for: {out_file}")
            print("-" * 60)
            for src in sources:
                print(f"  SOURCE: {src}")
            print("="*60 + "\n")

    if collisions_found > 0:
        print(f"\nALERT: Found {collisions_found} filename collisions.")
        return True
    
    print("Pre-Flight Check Passed: No collisions found.\n")
    return False

# --- MAIN PROCESSING ---

def process_library(src_dir, dst_dir):
    """
    Main processing loop. Scans source, normalizes, and writes to dest.
    """
    # Setup the normalizer
    # target_level=-14: Modern streaming loudness
    # audio_codec='libvorbis': Standard Ogg encoder
    # extra_output_options:
    #   -q:a 7   : Quality ~224-256kbps
    #   -ar 44100: Force 44.1kHz sample rate (Fixes 192kHz upsampling bug)
    normalizer = FFmpegNormalize(
        target_level=-14,
        print_stats=False,
        debug=False,
        progress=False, 
        audio_codec='libvorbis',
        extra_output_options=['-q:a', '7', '-ar', '44100'] 
    )

    # Note: .mp3 is EXCLUDED to prevent re-encoding generation loss
    supported_exts = ('.flac', '.ogg', '.m4a', '.opus', '.wav')
    
    # Initialize Counters for Verification
    stats = {
        "scanned": 0,        # Total files found
        "selected": 0,       # Files matching supported extensions
        "skipped_existing": 0, # Files already processed (Resume)
        "skipped_mp3": 0,    # MP3s intentionally skipped
        "skipped_other": 0,  # Non-audio files
        "converted": 0,      # Successfully created output files
        "errors": 0          # Processing failures
    }
    
    # Lists for detailed summary
    list_skipped_existing = []
    list_skipped_other = []
    list_errors = []

    if not os.path.isdir(src_dir):
        print(f"Source directory not found: {src_dir}")
        return
    if not os.path.exists(dst_dir):
        os.makedirs(dst_dir)

    print(f"Scanning {src_dir} for audio files...\n")

    for root, dirs, files in os.walk(src_dir):
        for name in files:
            stats["scanned"] += 1
            
            # Filter Logic
            lower_name = name.lower()
            if not lower_name.endswith(supported_exts):
                if lower_name.endswith('.mp3'):
                    stats["skipped_mp3"] += 1
                else:
                    stats["skipped_other"] += 1
                    # Store relative path for cleaner output (like find command)
                    rel_path = os.path.relpath(os.path.join(root, name), src_dir)
                    list_skipped_other.append(rel_path)
                continue

            stats["selected"] += 1
            input_path = os.path.join(root, name)
            
            # 1. Get Metadata
            meta = get_metadata(input_path)
            
            # 2. Construct Filename
            # Pattern: Genre-Album_Title_Artist
            base_name = f"{meta['genre']}-{meta['album']}_{meta['title']}_{meta['artist']}"
            clean_name = clean_filename(base_name)
            output_filename = f"{clean_name}.ogg"
            output_path = os.path.join(dst_dir, output_filename)

            # 3. CHECK FOR EXISTING FILE (Resume Logic)
            if os.path.exists(output_path):
                # print(f"[{stats['selected']}] SKIPPING (Already exists): {output_filename}")
                stats["skipped_existing"] += 1
                list_skipped_existing.append(output_filename)
                continue

            # 4. ATOMIC SETUP: Define temporary path
            # We append ".part.ogg" so ffmpeg knows it's an Ogg file.
            temp_output_path = output_path + ".part.ogg"

            print(f"[{stats['selected']}] Processing: {name} -> {output_filename}")

            try:
                # 5. Transcode & Normalize (Write to temp file)
                # Note: We overwrite temp file if it exists (trash from previous crash)
                normalizer.add_media_file(input_path, temp_output_path)
                normalizer.run_normalization()
                
                # --- CRITICAL FIX 1: CLEAR QUEUE ---
                # This prevents the script from re-processing all previous files
                # in every iteration of the loop.
                normalizer.media_files = [] 
                # ---------------------------------
                
                # --- CRITICAL FIX 2: ATOMIC RENAME ---
                # Only rename .part.ogg to .ogg if ffmpeg finished successfully
                if os.path.exists(temp_output_path):
                    os.rename(temp_output_path, output_path)
                    
                    if os.path.exists(output_path):
                        stats["converted"] += 1
                    else:
                        print(f"  ERROR: Rename failed for: {output_filename}")
                        stats["errors"] += 1
                        list_errors.append(f"{name} (Rename Failed)")
                else:
                    print(f"  ERROR: Normalization finished but temp file missing: {temp_output_path}")
                    stats["errors"] += 1
                    list_errors.append(f"{name} (Temp File Missing)")

            except Exception as e:
                print(f"  FAILED to process {name}: {e}")
                stats["errors"] += 1
                list_errors.append(f"{name} (Exception: {e})")
                # Clear queue to prevent blocking subsequent files
                normalizer.media_files = []
                # Clean up partial file if it exists so we don't leave trash
                if os.path.exists(temp_output_path):
                    os.remove(temp_output_path)

    # Final Report
    print("\n" + "="*50)
    print("              PROCESSING SUMMARY")
    print("="*50)

    # List Non-Audio Skips
    if list_skipped_other:
        print(f"Skipped other files (Non-audio): {len(list_skipped_other)}")
        for i, f in enumerate(list_skipped_other):
            if i >= 10:
                print(f"  ... {len(list_skipped_other) - 10} more skipped.")
                break
            print(f"  [Skip Other] {f}")
        print("-" * 50)

    # List Existing Skips
    if list_skipped_existing:
        print(f"Skipped existing files (Resume): {len(list_skipped_existing)}")
        for i, f in enumerate(list_skipped_existing):
            if i >= 10:
                print(f"  ... {len(list_skipped_existing) - 10} more skipped.")
                break
            print(f"  [Skip Exist] {f}")
        print("-" * 50)
        
    # List Errors
    if list_errors:
        print(f"Errors encountered: {len(list_errors)}")
        for f in list_errors:
            print(f"  [Error] {f}")
        print("-" * 50)

    # Verification Logic
    valid_outputs = stats['skipped_existing'] + stats['converted']

    print(f"Total files scanned:       {stats['scanned']}")
    print(f"Skipped MP3s:              {stats['skipped_mp3']}")
    print("-" * 50)
    print(f"Input Audio Files found:   {stats['selected']}")
    print(f"Output Audio Files:        {valid_outputs}")
    print(f"  - Already Existed:       {stats['skipped_existing']}")
    print(f"  - Newly Converted:       {stats['converted']}")
    if stats['errors'] > 0:
        print(f"  - Failed/Errors:         {stats['errors']}")
    print("="*50)
    
    if stats['selected'] > 0 and stats['selected'] == valid_outputs:
        print("VERIFICATION SUCCESS: An output audio file exists for every input audio file.")
    elif stats['selected'] == 0:
        print("WARNING: No supported files (flac/m4a/opus/wav) were found.")
    else:
        print("ALERT: Discrepancy detected!")
        print(f"       Input Audio Count:  {stats['selected']}")
        print(f"       Output Audio Count: {valid_outputs}")
        print(f"       Difference:         {stats['selected'] - valid_outputs}")
        if list_errors:
            print("       (Check error list above for details)")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <source_dir> <dest_dir>")
        sys.exit(1)

    # 1. Run Pre-Flight Collision Check
    has_collisions = check_collisions(sys.argv[1])
    
    if has_collisions:
        response = input("WARNING: Collision(s) detected. Do you want to proceed? [y/N]: ").strip().lower()
        if response != 'y':
            print("Aborting processing. Please fix tags or remove duplicate files.")
            sys.exit(1)
        print("Proceeding despite collisions (Overwrites will occur)...")

    # 2. Start Processing
    process_library(sys.argv[1], sys.argv[2])
