#!/usr/bin/env python3
import os
from mutagen.id3 import (
    ID3, TIT2, TPE1, TALB, TCON,
    ID3NoHeaderError
)

REPLAYGAIN_FRAMES = (
    "TXXX:replaygain_track_gain",
    "TXXX:replaygain_track_peak",
    "TXXX:replaygain_album_gain",
    "TXXX:replaygain_album_peak",
)

def load_tags(file):
    try:
        audio = ID3(file)
    except ID3NoHeaderError:
        audio = ID3()

    def get(tag):
        f = audio.getall(tag)
        return f[0].text[0] if f else ""

    return audio, {
        "title": get("TIT2"),
        "artist": get("TPE1"),
        "album": get("TALB"),
        "genre": get("TCON"),
    }

def find_replaygain(audio):
    found = []
    for key in audio.keys():
        if key.lower().startswith("txxx:replaygain"):
            found.append(key)
    return found

def prompt(field, current):
    return input(f"{field.capitalize()} [{current}]: ").strip() or current

def edit_album(files, replaygain_log):
    edited = []

    for file in files:
        audio, tags = load_tags(file)

        rg = find_replaygain(audio)
        if rg:
            print(f"\n⚠ ReplayGain detected in {os.path.basename(file)}")
            for r in rg:
                print(f"  - {r}")
            print("  → Will be removed for safe tagging\n")
            replaygain_log.append(file)

        print(f"File: {os.path.basename(file)}")
        tags["title"] = prompt("title", tags["title"])
        tags["artist"] = prompt("artist", tags["artist"])
        tags["album"] = prompt("album", tags["album"])
        tags["genre"] = prompt("genre", tags["genre"])

        edited.append((file, audio, tags))

    return edited

def confirm_album(edited):
    print("\n=== Album Summary ===")
    for file, _, tags in edited:
        print(f"\n{os.path.basename(file)}")
        for k, v in tags.items():
            print(f"  {k.capitalize()}: {v}")

    while True:
        choice = input("\nAccept these tags? [y]es / [e]dit again / [q]uit: ").lower()
        if choice in ("y", "e", "q"):
            return choice

def write_tags(edited):
    for file, audio, tags in edited:
        # Remove replay-gain frames
        for key in list(audio.keys()):
            if key.lower().startswith("txxx:replaygain"):
                audio.delall(key)

        audio.delall("TIT2")
        audio.add(TIT2(encoding=3, text=tags["title"]))

        audio.delall("TPE1")
        audio.add(TPE1(encoding=3, text=tags["artist"]))

        audio.delall("TALB")
        audio.add(TALB(encoding=3, text=tags["album"]))

        audio.delall("TCON")
        audio.add(TCON(encoding=3, text=tags["genre"]))

        audio.save(file, v2_version=3)

    print("\n✔ Tags written successfully.")

def replaygain_summary(replaygain_log):
    if not replaygain_log:
        return

    print("\n=== ReplayGain Removal Summary ===")
    print("The following files had ReplayGain tags removed and should be re-scanned:\n")
    for f in replaygain_log:
        print(f"  {os.path.basename(f)}")

    print("\nRecommended next step:")
    print("  Run your ReplayGain scanner on this album once tagging is complete.\n")

def main():
    folder = input("Folder containing MP3s: ").strip()
    if not os.path.isdir(folder):
        print("Invalid folder.")
        return

    files = sorted(
        os.path.join(folder, f)
        for f in os.listdir(folder)
        if f.lower().endswith(".mp3")
    )

    if not files:
        print("No MP3 files found.")
        return

    replaygain_log = []

    while True:
        edited = edit_album(files, replaygain_log)
        decision = confirm_album(edited)

        if decision == "y":
            write_tags(edited)
            replaygain_summary(replaygain_log)
            break
        elif decision == "e":
            continue
        else:
            print("Aborted. No changes written.")
            break

if __name__ == "__main__":
    main()
