#!/usr/bin/env python3
"""
Simulate timed-practice playlist lengths from song_metadata_cache.json.

The practice type is read from builtin_practice_types.json, overridden by the
user's custom_practice_types.json as in the player, and defaults to
"Silver+ Std 60min Timed". Its dance_minutes, dance_max_playtimes and
min_song_play_seconds are used as they are; a dance without a
dance_max_playtimes entry uses --default-cap.

Each block includes a --intro-seconds cue.  The planner draws songs until the
music portion of the block reaches its budget, then runs the player's own
planner (timed_blocks.py):

  * maximum normal trim: 45 s/song;
  * never trim a song below the practice type's minimum play time;
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
    ./simulate_timed_practice.py song_metadata_cache.json --min-play 90 --playlist-minutes 57
    ./simulate_timed_practice.py song_metadata_cache.json --practice-type "My Timed Type"
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
from typing import Iterable

# Import the player's modules regardless of where this is run from.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, REPO_DIR)

# pylint: disable=wrong-import-position
import app_paths
import practice_type_rules
import timed_blocks


DEFAULT_PRACTICE_TYPE = "Silver+ Std 60min Timed"

# The player's own values, repeated here so this script does not have to import
# music_player and with it the whole of Kivy. A test asserts they still agree.
FADE_SECONDS = 10.0
DEFAULT_GLOBAL_CAP = 210.0

DEFAULT_INTRO_SECONDS = 10.0
DEFAULT_RUNS = 10_000


@dataclass
class PracticeType:
    name: str
    dance_minutes: dict[str, float]
    dance_caps: dict[str, float]
    min_play: float

    @property
    def total_minutes(self) -> float:
        return sum(self.dance_minutes.values())


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


def load_definitions(path: str) -> dict:
    """The practice types in one JSON file, without comments. Missing is empty."""
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a JSON object.")
    return {name: data for name, data in raw.items()
            if not name.startswith("__COMMENT__")}


def load_practice_type(name: str, builtin_path: str, custom_path: str) -> PracticeType:
    """Reads one timed practice type, a custom definition overriding a built-in one."""
    definitions = load_definitions(builtin_path) | load_definitions(custom_path)
    if name not in definitions:
        raise ValueError(f"No practice type named {name!r}.")
    definition = practice_type_rules.normalize_practice_type(name, definitions[name])
    if definition is None:
        raise ValueError(f"Practice type {name!r} is not usable.")

    # As the player does, only dances the type actually plays are timed.
    dances = definition["dances"]

    def positive_numbers(field: str) -> dict[str, float]:
        values = {}
        raw = definition.get(field, {})
        for dance, amount in (raw.items() if isinstance(raw, dict) else ()):
            if dance not in dances:
                continue
            number = practice_type_rules.strict_number(amount, f"{field}: {dance!r}")
            if number is not None and number > 0:
                values[dance] = number
        return values

    minutes = positive_numbers("dance_minutes")
    if not minutes:
        raise ValueError(f"Practice type {name!r} has no timed dances (dance_minutes).")
    return PracticeType(
        name=name,
        dance_minutes=minutes,
        dance_caps=positive_numbers("dance_max_playtimes"),
        min_play=definition.get(
            "min_song_play_seconds", practice_type_rules.DEFAULT_MIN_SONG_PLAY_SECONDS),
    )


def load_pools(cache_path: str, dances: Iterable[str]) -> dict[str, list[Song]]:
    with open(cache_path, "r", encoding="utf-8") as handle:
        raw = json.load(handle)

    songs = raw.get("songs")
    if not isinstance(songs, dict):
        raise ValueError("Cache does not contain a top-level 'songs' object.")

    pools = {dance: [] for dance in dances}
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


def plan_timed_block(lengths: list[float], budget: float,
                     min_play: float) -> tuple[list[float], bool]:
    """The player's plan, and whether it dropped any of the drawn songs."""
    planned = timed_blocks.plan_timed_block(
        lengths, budget, timed_blocks.MAX_TRIM_SECONDS, min_play)
    return planned, len(planned) < len(lengths)


def simulate_block(
    practice: PracticeType,
    dance: str,
    pool: list[Song],
    rng: random.Random,
    global_cap: float,
    intro_seconds: float,
    min_play: float,
    playlist_minutes: float,
) -> BlockResult:
    scale = playlist_minutes / practice.total_minutes
    target = practice.dance_minutes[dance] * scale * 60.0
    music_budget = target - intro_seconds
    cap = practice.dance_caps.get(dance, global_cap)

    if music_budget <= 0:
        # The player plays the intro alone when it fills the block.
        return BlockResult(dance=dance, target_seconds=target,
                           intro_seconds=intro_seconds, songs=[],
                           dropped_last_song=False)

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

    planned, dropped = plan_timed_block(lengths, music_budget, min_play)
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
    if not songs:
        print(f"\n{label}\n  no songs: every block was its intro alone")
        return
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
        "hit_min_play_floor",
        "fade_start",
        "block_actual_seconds",
        "block_difference_seconds",
        "dropped_last_song",
    ]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)



def compact_scenario(practice: PracticeType, pools, runs: int, seed: int, global_cap: float,
                     intro_seconds: float, min_play: float, playlist_minutes: float):
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
        for dance in practice.dance_minutes:
            result = simulate_block(
                practice, dance, pools[dance], rng, global_cap, intro_seconds,
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
    # Every block can be its intro alone, leaving no songs to measure.
    song_count = len(all_songs)
    return {
        "min_play": min_play,
        "playlist_minutes": playlist_minutes,
        "mean_song": statistics.fmean(lengths) if lengths else math.nan,
        "median_song": statistics.median(lengths) if lengths else math.nan,
        "p10_song": percentile(lengths, .10),
        "p90_song": percentile(lengths, .90),
        "trim_pct": 100.0 * len(trimmed) / song_count if song_count else math.nan,
        "floor_pct": 100.0 * len(floors) / song_count if song_count else math.nan,
        "mean_songs": statistics.fmean(song_counts),
        "mean_runtime": statistics.fmean(playlist_lengths),
        "p05_runtime": percentile(playlist_lengths, .05),
        "p95_runtime": percentile(playlist_lengths, .95),
        "short_playlist_pct": 100.0 * sum(x < target - 1.0 for x in playlist_lengths) / runs,
        "over_playlist_pct": 100.0 * sum(x > target + 1.0 for x in playlist_lengths) / runs,
        "dropped_block_pct": 100.0 * dropped_blocks / (runs * len(practice.dance_minutes)),
        "short_block_pct": 100.0 * short_blocks / (runs * len(practice.dance_minutes)),
        "over_block_pct": 100.0 * over_blocks / (runs * len(practice.dance_minutes)),
    }


def print_comparison(practice: PracticeType, pools, args):
    floors = [60.0, 75.0, 90.0, 105.0, 120.0]
    targets = sorted({practice.total_minutes, args.playlist_minutes})
    rows = []
    for target in targets:
        for floor in floors:
            rows.append(compact_scenario(
                practice, pools, args.runs, args.seed, args.default_cap,
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
    print(f"  * {practice.total_minutes:g} minutes is {practice.name!r} as defined; any other")
    print("    target scales every dance block in proportion to its dance_minutes.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Monte Carlo simulation of a DancePracticeMusicPlayer "
            "timed practice type's playlist."
        )
    )
    parser.add_argument("cache", help="Path to song_metadata_cache.json")
    parser.add_argument(
        "--practice-type",
        default=DEFAULT_PRACTICE_TYPE,
        help=f"Practice type to simulate (default: {DEFAULT_PRACTICE_TYPE!r})",
    )
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
        help=(
            "Minimum allowed total playback of a trimmed song, including fade "
            "(default: the practice type's min_song_play_seconds, else "
            f"{practice_type_rules.DEFAULT_MIN_SONG_PLAY_SECONDS:g} s)"
        ),
    )
    parser.add_argument(
        "--playlist-minutes",
        type=float,
        help=(
            "Target total playlist minutes. Dance block lengths are scaled "
            "in proportion to the practice type's dance_minutes "
            "(default: their total)"
        ),
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help=(
            "Compare min-play floors 60,75,90,105,120 s at the practice type's "
            "own length and at --playlist-minutes, then exit."
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
    if args.min_play is not None and args.min_play <= 0:
        parser.error("--min-play must be positive")
    if args.playlist_minutes is not None and args.playlist_minutes <= 0:
        parser.error("--playlist-minutes must be positive")

    try:
        practice = load_practice_type(
            args.practice_type,
            app_paths.app_path("builtin_practice_types.json"),
            app_paths.user_path("custom_practice_types.json", seed_from_app_dir=False))
    except (OSError, ValueError) as error:
        parser.error(str(error))
    if args.min_play is None:
        args.min_play = practice.min_play
    if args.playlist_minutes is None:
        args.playlist_minutes = practice.total_minutes

    pools = load_pools(args.cache, practice.dance_minutes)
    if args.compare:
        print_comparison(practice, pools, args)
        return 0
    rng = random.Random(args.seed)

    print("Timed-practice simulation")
    print("========================")
    print(f"practice type      : {practice.name}")
    print(f"cache              : {args.cache}")
    print(f"simulated playlists: {args.runs:,}")
    print(f"random seed        : {args.seed}")
    print(f"global cap         : {args.default_cap:g} s + {FADE_SECONDS:g} s fade")
    for dance, cap in practice.dance_caps.items():
        print(f"{dance + ' cap':19s}: {cap:g} s + {FADE_SECONDS:g} s fade")
    print(f"block intro        : {args.intro_seconds:g} s")
    print(f"max uniform trim   : {timed_blocks.MAX_TRIM_SECONDS:g} s/song")
    print(f"minimum play       : {args.min_play:g} s including fade")
    print(f"playlist target    : {args.playlist_minutes:g} min")
    print("\nUsable songs in cache:")
    for dance in practice.dance_minutes:
        durations = [s.duration for s in pools[dance]]
        print(
            f"  {dance:16s} {len(durations):4d} songs; "
            f"median {statistics.median(durations):6.1f} s; "
            f"range {min(durations):6.1f}-{max(durations):6.1f} s"
        )

    all_songs: list[PlayedSong] = []
    songs_by_dance = {dance: [] for dance in practice.dance_minutes}
    block_actuals = {dance: [] for dance in practice.dance_minutes}
    block_differences = {dance: [] for dance in practice.dance_minutes}
    block_drops = {dance: 0 for dance in practice.dance_minutes}
    playlist_lengths: list[float] = []
    csv_rows: list[dict] = []

    for run in range(1, args.runs + 1):
        playlist_total = 0.0

        for dance in practice.dance_minutes:
            result = simulate_block(
                practice,
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
                            "hit_min_play_floor": int(song.floor_hit),
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
    for dance in practice.dance_minutes:
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
    over_target = sum(1 for x in playlist_lengths if x > target_playlist + 1.0)
    short_target = sum(1 for x in playlist_lengths if x < target_playlist - 1.0)
    print(f"  >target +1 s           : {over_target:,} ({pct(over_target, args.runs).strip()})")
    print(f"  <target -1 s           : {short_target:,} ({pct(short_target, args.runs).strip()})")

    if args.csv:
        write_csv(args.csv, csv_rows)
        print(f"\nWrote per-song simulation data to {args.csv}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
