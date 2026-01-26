
# Technical Specification: Music Ingest & Organization Pipeline

**Component:** `normalize_and_organize_ogg.py`
**Language:** Python 3
**Dependencies:** `ffmpeg-normalize`, `mutagen`, `ffmpeg`

## 1. System Overview

This utility implements an atomic audio ingest pipeline designed to normalize loudness (EBU R128) and flatten a nested music library into a single, semantic directory structure.

The system prioritizes **filesystem-level sorting** over metadata browsing. By "baking" specific metadata tags directly into the filename, the output directory becomes naturally sorted by Dance Style and Tempo without requiring a specialized music player or database.

## 2. Naming Architecture

The system utilizes a deterministic naming algorithm. It does not assign arbitrary UIDs; rather, it projects the file's metadata directly onto the filesystem.

### Filename Constructor

The output filename is generated using the following concatenation logic:

### Sorting Logic

The field order is chosen to enforce specific grouping behaviors in standard file explorers:

1. **Genre:** Primary grouping (e.g., all "ChaCha" tracks appear together).
2. **Album:** Secondary grouping (keeps tracks from the same release adjacent).
3. **Title/Artist:** Identification.

---

## 3. Data Integrity & Uniqueness Contract

To guarantee unique output filenames and prevent data loss, the input library must adhere to strict tagging standards. The system relies on the **Album** and **Track Title** tags to provide a unique namespace for every recording.

### Input Requirements

1. **Mandatory Album Tag:** The `Album` tag must be present and accurate. It acts as the primary namespace for the tracks it contains.
2. **Unique Track Titles:** Within a specific `Album`, every `Track Title` must be distinct.
* *Constraint:* If an album contains multiple versions of a song (e.g., "Instrumental" vs "Vocal"), the `Title` tag must explicitly differentiate them (e.g., *"Song A (Inst)"* vs *"Song A"*).


3. **Sanitization Awareness:** The system creates "Compact Filenames" by removing **all spaces** and replacing reserved characters (`< > : " / \ | ? *`) with underscores.
* *Requirement:* Users must ensure that `Title` tags remain unique even after spaces and special characters are stripped.



> **System Behavior:** The script performs a **Pre-Flight Check** before processing audio. It simulates the naming generation for all files; if distinct source files map to the same destination filename (due to missing or identical tags), the process aborts to prevent overwrites.

---

## 4. The "Encoded Genre" Schema

To achieve the desired sorting behavior (grouping by Dance Style, then ascending Tempo), the `Genre` tag must not use standard strings (e.g., "Pop"). Instead, it must follow a specific **Ballroom Compound Schema**.

### Schema Definition

The genre tag implies a strict structure that encodes the sort order:

| Component | Description | Regex Pattern | Example |
| --- | --- | --- | --- |
| **Style** | The dance category. Sorts primarily alphabetically. | `[A-Za-z]+` | `ChaCha`, `Waltz` |
| **Tempo** | The speed of the track. Sorts secondarily. | `\d{2,3}` | `28`, `30`, `50` |
| **Unit** | Time unit (Measures Per Minute). | `(mpm|bpm)` | `mpm` |
| **Modifier** | *Optional.* Context or sub-variant. | `.*` | `Slow`, `Practice` |

### Sorting Example

By adhering to this schema, the operating system sorts the files naturally:

1. `ChaCha29mpm-...`
2. `ChaCha30mpm-...`
3. `ChaCha31mpm-...`
4. `Jive42mpm-...`
5. `Jive44mpm-...`

*Note: The script does not calculate BPM. It relies entirely on the user populating the `Genre` tag with this pre-formatted string.  The string can contains spaces.  For instance, "Jive 44 mpm" will become "Jive44mpm".*

---

## 5. Transformation Logic

### Sanitization (NTFS Compatibility)

To ensure cross-platform compatibility and readability, input strings undergo strict sanitization via the `clean_filename` function:

1. **Whitespace Removal:** All spaces are stripped to create compact identifiers.
2. **Character Replacement:** Illegal NTFS characters are replaced with `_`.
3. **Deduplication:** Repeated underscores are collapsed (`__`  `_`).
4. **Length Cap:** Filenames are truncated to 255 bytes.

### Smart Title Casing

Standard Python title casing (`.title()`) incorrectly capitalizes contractions (e.g., "Don'T"). The script implements a custom Regex pass to correct this:

* **Pattern:** `r"([a-zA-Z])'([A-Z])"`
* **Logic:** Lowercase the character immediately following an apostrophe if it is preceded by a letter.
* **Result:** `DON'T`  `Don't`.

---

## 6. Atomic Write Operations

To ensure the library remains in a valid state during long batch processes, the script employs an atomic write strategy:

1. **Transcode to Temp:** FFmpeg writes the normalized audio to a temporary file: `filename.ogg.part.ogg`.
2. **Verify:** The script checks that the encoding process completed successfully.
3. **Atomic Rename:** Only upon success is the `.part.ogg` file renamed to `.ogg`.

This prevents the creation of corrupt or truncated files if the script is interrupted (e.g., power loss or `Ctrl+C`). Upon restart, the script will see the `.part` file as "incomplete" (or overwrite it) and skip files that were successfully renamed, effectively acting as a **resume function**.
