#!/usr/bin/env python3
"""
Collision Detector
Scans the source library and checks if multiple input files 
map to the exact same output filename.
"""

import os
import sys
import re
import mutagen

# --- COPYING EXACT LOGIC FROM YOUR MAIN SCRIPT ---

def smart_title(s):
    if not s: return ""
    s = str(s).title()
    return re.sub(r"([a-zA-Z])'([A-Z])", lambda m: m.group(1) + "'" + m.group(2).lower(), s)

def clean_filename(s):
    ILLEGAL_NTFS_CHARS = r'[<>:/\\|?*"]|[\0-\31]'
    s = re.sub(ILLEGAL_NTFS_CHARS, "_", s)
    s = s.replace(" ", "")
    s = re.sub(r'_+', '_', s)
    return s[:255]

def get_metadata(filepath):
    try:
        f = mutagen.File(filepath, easy=True)
        def get_tag_raw(tag_name, default):
            if f and tag_name in f:
                return str(f[tag_name][0])
            return default

        return {
            "genre": get_tag_raw("genre", "UnknownGenre"),
            "artist": smart_title(get_tag_raw("artist", "UnknownArtist")),
            "album": smart_title(get_tag_raw("album", "UnknownAlbum")),
            "title": smart_title(get_tag_raw("title", "UnknownTitle")),
        }
    except Exception:
        return {k: f"Unknown{k.capitalize()}" for k in ["genre", "artist", "album", "title"]}

# --- DEBUG LOGIC ---

def find_collisions(src_dir):
    supported_exts = ('.flac', '.ogg', '.m4a', '.opus', '.wav')
    
    # Dictionary to track: { 'OutputFilename.ogg': ['SourcePath1', 'SourcePath2'] }
    mapping = {}
    
    print(f"Scanning {src_dir} for potential tag collisions...\n")
    
    count = 0
    for root, dirs, files in os.walk(src_dir):
        for name in files:
            if not name.lower().endswith(supported_exts):
                continue
            
            input_path = os.path.join(root, name)
            
            # Simulate the naming logic
            meta = get_metadata(input_path)
            base_name = f"{meta['genre']}-{meta['album']}_{meta['title']}_{meta['artist']}"
            clean_name = clean_filename(base_name)
            output_filename = f"{clean_name}.ogg"
            
            if output_filename not in mapping:
                mapping[output_filename] = []
            mapping[output_filename].append(input_path)
            count += 1
            if count % 100 == 0:
                print(f"Scanned {count} files...", end='\r')

    print(f"\nScan complete. Scanned {count} files. Checking {len(mapping)} generated names.\n")
    
    # Report Collisions
    collisions_found = 0
    for out_file, sources in mapping.items():
        if len(sources) > 1:
            collisions_found += 1
            print("="*60)
            print(f"COLLISION DETECTED for: {out_file}")
            print("-" * 60)
            for src in sources:
                print(f"  SOURCE: {src}")
            print("="*60 + "\n")

    if collisions_found == 0:
        print("No collisions found. Your tags generate unique filenames.")
        print("If 'Skipping' is occurring, it is correctly identifying previously processed files.")
    else:
        print(f"Found {collisions_found} filename collisions.")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: python3 find_collisions.py <source_dir>")
        sys.exit(1)
    
    find_collisions(sys.argv[1])
