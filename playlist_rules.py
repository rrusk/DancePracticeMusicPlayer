"""Selection and playback lengths shared by the player and offline previews.

Candidate ordering and metadata loading belong to callers. Selection consumes
their iterators lazily so the player need not read tags for the whole library.
"""

import os

import timed_blocks

FADE_SECONDS = 10.0
DEFAULT_GLOBAL_CAP = 210
MIN_COUNT_SONG_SECONDS = 90
MUSIC_EXTENSIONS = (".mp3", ".ogg", ".m4a", ".flac", ".wav")


def collect_music_files(directory):
    """Recursively find the audio files the player considers, in scan order."""
    paths = []
    for root, _, files in os.walk(directory):
        paths.extend(os.path.join(root, name) for name in files
                     if name.lower().endswith(MUSIC_EXTENSIONS))
    return paths


def entry_ignoring_case(folder, name, want_dir, warn=lambda message: None):
    """Prefer the exact local entry, then the first case-insensitive match."""
    exact = os.path.join(folder, name)
    check = os.path.isdir if want_dir else os.path.isfile
    if check(exact):
        return exact
    try:
        entries = os.listdir(folder)
    except OSError:
        return None
    wanted = name.casefold()
    matches = sorted(entry for entry in entries
                     if entry.casefold() == wanted and check(os.path.join(folder, entry)))
    if not matches:
        return None
    if len(matches) > 1:
        warn(f"{folder} contains {len(matches)} entries named '{name}' differing only in case: "
             f"{', '.join(matches)}. Using '{matches[0]}'.")
    return os.path.join(folder, matches[0])


def play_length(duration, max_playtime, fade=FADE_SECONDS, single_song=False):
    """Seconds an item plays: a single song in full, anything else cut at its cap and faded."""
    if single_song:
        return float(duration)
    return min(float(duration), float(max_playtime) + float(fade))


def effective_length(duration, cap):
    return play_length(duration, cap)


def block_is_played(mode, amount):
    """A fixed count of zero leaves the dance out, intro included."""
    return mode != "count" or amount > 0


def candidate_tiers(items, taken, played=frozenset(), key=lambda item: item):
    """Split candidates into unplayed, played before, and already in this playlist.

    Callers shuffle or sort within each tier and take them in that order, so a
    dance listed twice repeats a song only when nothing else will do.
    """
    unplayed, replayed, repeated = [], [], []
    for item in items:
        name = key(item)
        (repeated if name in taken else replayed if name in played else unplayed).append(item)
    return unplayed, replayed, repeated


def select_count(candidates, wanted, min_seconds, duration):
    """Pick eligible songs first, then the longest short tracks if necessary."""
    if wanted <= 0:
        return [], 0
    chosen, too_short = [], []
    for song in candidates:
        if not min_seconds or duration(song) >= min_seconds:
            chosen.append(song)
            if len(chosen) == wanted:
                break
        else:
            too_short.append(song)
    fallback = min(wanted - len(chosen), len(too_short))
    if fallback:
        too_short.sort(key=lambda song: -duration(song))
        chosen.extend(too_short[:fallback])
    return chosen, fallback


def draw_timed(candidates, budget, cap, min_play, duration):
    """Return kept songs, their untrimmed lengths, plan, and whether a song was dropped."""
    drawn, lengths = [], []
    total = 0.0
    if budget <= 0:
        return [], [], [], False
    for song in candidates:
        drawn.append(song)
        length = effective_length(duration(song), cap)
        lengths.append(length)
        total += length
        if total >= budget:
            break
    planned = timed_blocks.plan_timed_block(lengths, budget, timed_blocks.MAX_TRIM_SECONDS, min_play)
    return drawn[:len(planned)], lengths[:len(planned)], planned, len(planned) < len(lengths)


def timed_song_cap(full_length, planned_length, cap):
    """Resolve the exact per-song cap installed by the player after planning."""
    if planned_length < full_length - 0.5:
        return max(planned_length - FADE_SECONDS, 1.0)
    return cap
