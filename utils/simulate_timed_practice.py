#!/usr/bin/env python3
"""
Simulate timed-practice playlist lengths from song_metadata_cache.json.

Defaults model the current "Silver+ Std 60min Timed" practice type in
DancePracticeMusicPlayer:

    Waltz             13 min
    Tango             13 min
    VienneseWaltz      8 min, 150 s max-playtime cap
    Foxtrot           13 min
    QuickStep         10 min

Each block includes a 10-second gap cue.  The planner draws songs until the
music portion of the block reaches its budget, then applies the same uniform
trim algorithm as music_player.py:

  * maximum normal trim: 45 s/song;
  * never trim a song below 60 s total playback;
  * if the average trim would exceed 45 s/song, drop the final drawn song
    and allow the block to run short;
  * a song longer than its cap occupies cap + fade time (10 s);
  * a trimmed song fades during its final 10 s.

This is a statistical simulation.  It uses the cache durations and random
permutations of each dance's song pool.  It does not model play_history.json,
which changes ordering between sessions but not the underlying duration pool.

Examples:
    ./simulate_timed_practice.py song_metadata_cache.json
    ./simulate_timed_practice.py song_metadata_cache.json --runs 100000 --seed 1234
    ./simulate_timed_practice.py song_metadata_cache.json --default-cap 180
    ./simulate_timed_practice.py song_metadata_cache.json --min-play 90 --playlist-minutes 60
    ./simulate_timed_practice.py song_metadata_cache.json --compare
    ./simulate_timed_practice.py song_metadata_cache.json --csv results.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import statistics
import sys
from dataclasses import dataclass
from pathlib import PurePath
from typing import Iterable


PRACTICE_MINUTES = {
    "Waltz": 13,
    "Tango": 13,
    "VienneseWaltz": 8,
    "Foxtrot": 13,
    "QuickStep": 10,
}

DANCE_CAPS = {
    "VienneseWaltz": 150.0,
}

FADE_SECONDS = 10.0
MAX_TRIM_SECONDS = 45.0
DEFAULT_MIN_SONG_PLAY_SECONDS = 60.0
DEFAULT_PLAYLIST_MINUTES = 57.0
DEFAULT_GLOBAL_CAP = 210.0
DEFAULT_INTRO_SECONDS = 10.0
DEFAULT_RUNS = 10_000


@dataclass
class Song:
    path: str
    duration: float


@dataclass
class PlayedSong:
    dance: str
    natural_duration: float
    effective_duration: float
    play_duration: float
    trimmed: bool
    floor_hit: bool

    @property
    def fade_start(self) -> float | None:
        if not self.trimmed:
            return None
        return max(self.play_duration - FADE_SECONDS, 0.0)


@dataclass
class BlockResult:
    dance: str
    target_seconds: float
    intro_seconds: float
    songs: list[PlayedSong]
    dropped_last_song: bool

    @property
    def music_seconds(self) -> float:
        return sum(song.play_duration for song in self.songs)

    @property
    def actual_seconds(self) -> float:
        return self.intro_seconds + self.music_seconds

    @property
    def difference_seconds(self) -> float:
        return self.actual_seconds - self.target_seconds


def usable_duration(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(value) or value <= 0:
        return None
    return value


def dance_from_path(path: str, wanted: Iterable[str]) -> str | None:
    """
    Find the dance folder as an exact path component.

    This avoids needing to know the music-library root and remains correct if
    songs are stored in album subdirectories below the dance directory.
    """
    # Cache paths are currently POSIX paths, but tolerate backslashes too.
    normalized = path.replace("\\", "/")
    parts = [part for part in normalized.split("/") if part]
    wanted_set = set(wanted)
    for part in parts:
        if part in wanted_set:
            return part
    return None


def load_pools(cache_path: str) -> dict[str, list[Song]]:
    with open(cache_path, "r", encoding="utf-8") as handle:
        raw = json.load(handle)

    songs = raw.get("songs")
    if not isinstance(songs, dict):
        raise ValueError("Cache does not contain a top-level 'songs' object.")

    pools = {dance: [] for dance in PRACTICE_MINUTES}
    skipped = 0

    for path, metadata in songs.items():
        if not isinstance(path, str) or not isinstance(metadata, dict):
            skipped += 1
            continue
        dance = dance_from_path(path, pools)
        if dance is None:
            continue
        duration = usable_duration(metadata.get("duration"))
        if duration is None:
            skipped += 1
            continue
        pools[dance].append(Song(path=path, duration=duration))

    missing = [dance for dance, pool in pools.items() if not pool]
    if missing:
        raise ValueError(
            "No usable cached songs found for: " + ", ".join(missing)
        )

    if skipped:
        print(f"Note: ignored {skipped} malformed/unusable cache entries.", file=sys.stderr)

    return pools


def effective_length(duration: float, cap: float) -> float:
    # Mirrors MusicPlayer._effective_length().
    return min(float(duration), cap + FADE_SECONDS)


def apply_uniform_trim(
    lengths: list[float], total_trim: float, min_play: float
) -> list[float]:
    # Mirrors MusicPlayer._apply_uniform_trim().
    planned = [float(length) for length in lengths]
    remaining = float(total_trim)
    active = [i for i, length in enumerate(planned) if length > min_play]

    while remaining > 0.5 and active:
        share = remaining / len(active)
        still_active = []
        for i in active:
            take = min(share, planned[i] - min_play)
            planned[i] -= take
            remaining -= take
            if planned[i] > min_play + 0.5:
                still_active.append(i)
        active = still_active

    return planned


def plan_timed_block(
    lengths: list[float],
    budget: float,
    max_trim: float = MAX_TRIM_SECONDS,
    min_play: float = DEFAULT_MIN_SONG_PLAY_SECONDS,
) -> tuple[list[float], bool]:
    # Mirrors MusicPlayer._plan_timed_block().
    kept = [float(length) for length in lengths]
    original_count = len(kept)

    while kept:
        overshoot = sum(kept) - budget
        if overshoot <= 0:
            return kept, len(kept) < original_count

        if overshoot / len(kept) <= max_trim or len(kept) == 1:
            return (
                apply_uniform_trim(kept, overshoot, min_play),
                len(kept) < original_count,
            )
        kept.pop()

    return [], original_count > 0


def simulate_block(
    dance: str,
    pool: list[Song],
    rng: random.Random,
    global_cap: float,
    intro_seconds: float,
    min_play: float,
    playlist_minutes: float,
) -> BlockResult:
    scale = playlist_minutes / sum(PRACTICE_MINUTES.values())
    target = PRACTICE_MINUTES[dance] * scale * 60.0
    music_budget = target - intro_seconds
    cap = DANCE_CAPS.get(dance, global_cap)

    candidates = pool[:]
    rng.shuffle(candidates)

    drawn: list[Song] = []
    lengths: list[float] = []
    total = 0.0

    for song in candidates:
        length = effective_length(song.duration, cap)
        drawn.append(song)
        lengths.append(length)
        total += length
        if total >= music_budget:
            break

    planned, dropped = plan_timed_block(lengths, music_budget, min_play=min_play)
    kept_songs = drawn[: len(planned)]
    kept_lengths = lengths[: len(planned)]

    songs: list[PlayedSong] = []
    for song, full_length, play_length in zip(kept_songs, kept_lengths, planned):
        trimmed = play_length < full_length - 0.5
        floor_hit = trimmed and play_length <= min_play + 0.5
        songs.append(
            PlayedSong(
                dance=dance,
                natural_duration=song.duration,
                effective_duration=full_length,
                play_duration=play_length,
                trimmed=trimmed,
                floor_hit=floor_hit,
            )
        )

    return BlockResult(
        dance=dance,
        target_seconds=target,
        intro_seconds=intro_seconds,
        songs=songs,
        dropped_last_song=dropped,
    )


def percentile(values: list[float], p: float) -> float:
    if not values:
        return math.nan
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * p
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return ordered[lo]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def fmt_time(seconds: float) -> str:
    sign = "-" if seconds < 0 else ""
    # Work in tenths so values such as 779.999999 print as 13:00.0,
    # rather than the confusing 12:60.0.
    tenths = int(round(abs(seconds) * 10.0))
    whole_seconds, tenth = divmod(tenths, 10)
    minutes, sec = divmod(whole_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{sign}{hours:d}:{minutes:02d}:{sec:02d}.{tenth}"
    return f"{sign}{minutes:d}:{sec:02d}.{tenth}"


def pct(numerator: int, denominator: int) -> str:
    return f"{100.0 * numerator / denominator:6.2f}%" if denominator else "   n/a"


def summarize_song_lengths(label: str, songs: list[PlayedSong], min_play: float) -> None:
    lengths = [s.play_duration for s in songs]
    trimmed = [s for s in songs if s.trimmed]
    floors = [s for s in songs if s.floor_hit]
    fade_starts = [s.fade_start for s in trimmed if s.fade_start is not None]

    print(f"\n{label}")
    print(f"  songs simulated        : {len(songs):,}")
    print(f"  mean play length       : {statistics.fmean(lengths):6.1f} s")
    print(f"  median play length     : {statistics.median(lengths):6.1f} s")
    print(
        "  play length P10/P25/P75/P90:"
        f" {percentile(lengths, .10):5.1f} /"
        f" {percentile(lengths, .25):5.1f} /"
        f" {percentile(lengths, .75):5.1f} /"
        f" {percentile(lengths, .90):5.1f} s"
    )
    print(f"  shortest / longest     : {min(lengths):6.1f} / {max(lengths):6.1f} s")
    print(f"  trimmed songs          : {len(trimmed):,} ({pct(len(trimmed), len(songs)).strip()})")
    print(f"  hit {min_play:g} s trim floor : {len(floors):,} ({pct(len(floors), len(songs)).strip()})")
    if fade_starts:
        print(
            f"  trimmed fade starts    : median {statistics.median(fade_starts):.1f} s, "
            f"P10 {percentile(fade_starts, .10):.1f} s"
        )


def write_csv(path: str, rows: list[dict]) -> None:
    fields = [
        "run",
        "dance",
        "song_index",
        "natural_duration",
        "effective_duration",
        "play_duration",
        "trimmed",
        "hit_60s_floor",
        "fade_start",
        "block_actual_seconds",
        "block_difference_seconds",
        "dropped_last_song",
    ]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)



def compact_scenario(pools, runs: int, seed: int, global_cap: float, intro_seconds: float, min_play: float, playlist_minutes: float):
    rng = random.Random(seed)
    all_songs = []
    playlist_lengths = []
    dropped_blocks = 0
    short_blocks = 0
    over_blocks = 0
    song_counts = []

    for _run in range(runs):
        playlist_total = 0.0
        playlist_song_count = 0
        for dance in PRACTICE_MINUTES:
            result = simulate_block(
                dance, pools[dance], rng, global_cap, intro_seconds,
                min_play, playlist_minutes
            )
            playlist_total += result.actual_seconds
            playlist_song_count += len(result.songs)
            all_songs.extend(result.songs)
            if result.dropped_last_song:
                dropped_blocks += 1
            if result.difference_seconds < -1.0:
                short_blocks += 1
            elif result.difference_seconds > 1.0:
                over_blocks += 1
        playlist_lengths.append(playlist_total)
        song_counts.append(playlist_song_count)

    lengths = [s.play_duration for s in all_songs]
    trimmed = [s for s in all_songs if s.trimmed]
    floors = [s for s in all_songs if s.floor_hit]
    target = playlist_minutes * 60.0
    return {
        "min_play": min_play,
        "playlist_minutes": playlist_minutes,
        "mean_song": statistics.fmean(lengths),
        "median_song": statistics.median(lengths),
        "p10_song": percentile(lengths, .10),
        "p90_song": percentile(lengths, .90),
        "trim_pct": 100.0 * len(trimmed) / len(all_songs),
        "floor_pct": 100.0 * len(floors) / len(all_songs),
        "mean_songs": statistics.fmean(song_counts),
        "mean_runtime": statistics.fmean(playlist_lengths),
        "p05_runtime": percentile(playlist_lengths, .05),
        "p95_runtime": percentile(playlist_lengths, .95),
        "short_playlist_pct": 100.0 * sum(x < target - 1.0 for x in playlist_lengths) / runs,
        "over_playlist_pct": 100.0 * sum(x > target + 1.0 for x in playlist_lengths) / runs,
        "dropped_block_pct": 100.0 * dropped_blocks / (runs * len(PRACTICE_MINUTES)),
        "short_block_pct": 100.0 * short_blocks / (runs * len(PRACTICE_MINUTES)),
        "over_block_pct": 100.0 * over_blocks / (runs * len(PRACTICE_MINUTES)),
    }


def print_comparison(pools, args):
    floors = [60.0, 75.0, 90.0, 105.0, 120.0]
    targets = [57.0, 60.0]
    rows = []
    for target in targets:
        for floor in floors:
            rows.append(compact_scenario(
                pools, args.runs, args.seed, args.default_cap,
                args.intro_seconds, floor, target
            ))

    print("Minimum-play / playlist-target comparison")
    print("=========================================")
    print(f"runs per scenario: {args.runs:,}   seed: {args.seed}")
    print()
    print(" target  floor   avg song  med song  P10-P90      avg #songs  floor hits  avg runtime  short    over")
    print(" ------  -----   --------  --------  -----------  ----------  ----------  -----------  -------  -------")
    for r in rows:
        print(
            f" {r['playlist_minutes']:5.0f}m  {r['min_play']:4.0f}s   "
            f"{r['mean_song']:7.1f}s  {r['median_song']:7.1f}s  "
            f"{r['p10_song']:5.1f}-{r['p90_song']:5.1f}s   "
            f"{r['mean_songs']:8.2f}    {r['floor_pct']:7.2f}%    "
            f"{fmt_time(r['mean_runtime']):>9s}    {r['short_playlist_pct']:6.2f}%  {r['over_playlist_pct']:6.2f}%"
        )
    print()
    print("Notes:")
    print("  * 'floor hits' = trimmed songs that land on the chosen minimum play time.")
    print("  * 'short'/'over' = total runtime more than 1 s below/above the requested target.")
    print("  * The 60-minute target scales all five dance blocks proportionally from")
    print("    the existing 13/13/8/13/10-minute pattern.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Monte Carlo simulation of the DancePracticeMusicPlayer "
            "'Silver+ Std 60min Timed' playlist."
        )
    )
    parser.add_argument("cache", help="Path to song_metadata_cache.json")
    parser.add_argument(
        "--runs",
        type=int,
        default=DEFAULT_RUNS,
        help=f"Number of simulated playlists (default: {DEFAULT_RUNS:,})",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=20261002,
        help="Random seed for reproducible results (default: 20261002)",
    )
    parser.add_argument(
        "--default-cap",
        type=float,
        default=DEFAULT_GLOBAL_CAP,
        help=(
            "Global song max_playtime in seconds for dances without an override "
            f"(default: {DEFAULT_GLOBAL_CAP:g})"
        ),
    )
    parser.add_argument(
        "--intro-seconds",
        type=float,
        default=DEFAULT_INTRO_SECONDS,
        help=(
            "Duration of each gap_10 intro cue in seconds "
            f"(default: {DEFAULT_INTRO_SECONDS:g})"
        ),
    )
    parser.add_argument(
        "--min-play",
        type=float,
        default=DEFAULT_MIN_SONG_PLAY_SECONDS,
        help=(
            "Minimum allowed total playback of a trimmed song, including fade "
            f"(default: {DEFAULT_MIN_SONG_PLAY_SECONDS:g} s)"
        ),
    )
    parser.add_argument(
        "--playlist-minutes",
        type=float,
        default=DEFAULT_PLAYLIST_MINUTES,
        help=(
            "Target total playlist minutes. Dance block lengths are scaled "
            "proportionally from the 13/13/8/13/10 pattern "
            f"(default: {DEFAULT_PLAYLIST_MINUTES:g})"
        ),
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help=(
            "Compare min-play floors 60,75,90,105,120 s at both 57 and 60 "
            "playlist minutes, then exit."
        ),
    )
    parser.add_argument(
        "--csv",
        metavar="FILE",
        help="Optional CSV containing every simulated played song.",
    )
    args = parser.parse_args()

    if args.runs <= 0:
        parser.error("--runs must be positive")
    if args.default_cap <= 0:
        parser.error("--default-cap must be positive")
    if args.intro_seconds < 0:
        parser.error("--intro-seconds cannot be negative")
    if args.min_play <= 0:
        parser.error("--min-play must be positive")
    if args.playlist_minutes <= 0:
        parser.error("--playlist-minutes must be positive")

    pools = load_pools(args.cache)
    if args.compare:
        print_comparison(pools, args)
        return 0
    rng = random.Random(args.seed)

    print("Timed-practice simulation")
    print("========================")
    print(f"cache              : {args.cache}")
    print(f"simulated playlists: {args.runs:,}")
    print(f"random seed        : {args.seed}")
    print(f"global cap         : {args.default_cap:g} s + {FADE_SECONDS:g} s fade")
    print(f"VW cap             : {DANCE_CAPS['VienneseWaltz']:g} s + {FADE_SECONDS:g} s fade")
    print(f"block intro        : {args.intro_seconds:g} s")
    print(f"max uniform trim   : {MAX_TRIM_SECONDS:g} s/song")
    print(f"minimum play       : {args.min_play:g} s including fade")
    print(f"playlist target    : {args.playlist_minutes:g} min")
    print("\nUsable songs in cache:")
    for dance in PRACTICE_MINUTES:
        durations = [s.duration for s in pools[dance]]
        print(
            f"  {dance:16s} {len(durations):4d} songs; "
            f"median {statistics.median(durations):6.1f} s; "
            f"range {min(durations):6.1f}-{max(durations):6.1f} s"
        )

    all_songs: list[PlayedSong] = []
    songs_by_dance = {dance: [] for dance in PRACTICE_MINUTES}
    block_actuals = {dance: [] for dance in PRACTICE_MINUTES}
    block_differences = {dance: [] for dance in PRACTICE_MINUTES}
    block_drops = {dance: 0 for dance in PRACTICE_MINUTES}
    playlist_lengths: list[float] = []
    csv_rows: list[dict] = []

    for run in range(1, args.runs + 1):
        playlist_total = 0.0

        for dance in PRACTICE_MINUTES:
            result = simulate_block(
                dance,
                pools[dance],
                rng,
                args.default_cap,
                args.intro_seconds,
                args.min_play,
                args.playlist_minutes,
            )
            playlist_total += result.actual_seconds
            block_actuals[dance].append(result.actual_seconds)
            block_differences[dance].append(result.difference_seconds)
            if result.dropped_last_song:
                block_drops[dance] += 1

            all_songs.extend(result.songs)
            songs_by_dance[dance].extend(result.songs)

            if args.csv:
                for index, song in enumerate(result.songs, 1):
                    csv_rows.append(
                        {
                            "run": run,
                            "dance": dance,
                            "song_index": index,
                            "natural_duration": f"{song.natural_duration:.6f}",
                            "effective_duration": f"{song.effective_duration:.6f}",
                            "play_duration": f"{song.play_duration:.6f}",
                            "trimmed": int(song.trimmed),
                            "hit_60s_floor": int(song.floor_hit),
                            "fade_start": (
                                "" if song.fade_start is None else f"{song.fade_start:.6f}"
                            ),
                            "block_actual_seconds": f"{result.actual_seconds:.6f}",
                            "block_difference_seconds": f"{result.difference_seconds:.6f}",
                            "dropped_last_song": int(result.dropped_last_song),
                        }
                    )

        playlist_lengths.append(playlist_total)

    print("\nPer-dance results")
    print("=================")
    for dance in PRACTICE_MINUTES:
        summarize_song_lengths(dance, songs_by_dance[dance], args.min_play)
        print(
            f"  mean songs per block   : "
            f"{len(songs_by_dance[dance]) / args.runs:6.2f}"
        )
        diffs = block_differences[dance]
        short = sum(1 for x in diffs if x < -1.0)
        over = sum(1 for x in diffs if x > 1.0)
        exact = args.runs - short - over
        print(
            f"  blocks on target ±1 s  : {exact:,} ({pct(exact, args.runs).strip()})"
        )
        print(
            f"  blocks >1 s short      : {short:,} ({pct(short, args.runs).strip()})"
        )
        print(
            f"  blocks >1 s over       : {over:,} ({pct(over, args.runs).strip()})"
        )
        print(
            f"  last song dropped      : {block_drops[dance]:,} "
            f"({pct(block_drops[dance], args.runs).strip()})"
        )
        print(
            f"  actual block range     : "
            f"{fmt_time(min(block_actuals[dance]))} - "
            f"{fmt_time(max(block_actuals[dance]))}"
        )

    summarize_song_lengths("ALL DANCES", all_songs, args.min_play)

    target_playlist = args.playlist_minutes * 60.0
    print("\nPlaylist runtime")
    print("================")
    print(f"  nominal target         : {fmt_time(target_playlist)}")
    print(f"  mean                   : {fmt_time(statistics.fmean(playlist_lengths))}")
    print(f"  median                 : {fmt_time(statistics.median(playlist_lengths))}")
    print(
        f"  P05 / P95              : "
        f"{fmt_time(percentile(playlist_lengths, .05))} / "
        f"{fmt_time(percentile(playlist_lengths, .95))}"
    )
    print(
        f"  shortest / longest     : "
        f"{fmt_time(min(playlist_lengths))} / "
        f"{fmt_time(max(playlist_lengths))}"
    )
    over_57 = sum(1 for x in playlist_lengths if x > target_playlist + 1.0)
    short_57 = sum(1 for x in playlist_lengths if x < target_playlist - 1.0)
    print(f"  >target +1 s           : {over_57:,} ({pct(over_57, args.runs).strip()})")
    print(f"  <target -1 s           : {short_57:,} ({pct(short_57, args.runs).strip()})")

    if args.csv:
        write_csv(args.csv, csv_rows)
        print(f"\nWrote per-song simulation data to {args.csv}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
