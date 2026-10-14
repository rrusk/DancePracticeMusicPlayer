#!/usr/bin/env python3
"""Preview a named practice and compare parameter changes without running Kivy.

Uses current cached or freshly read durations and the player's count rules and timed-block planner.
Run with --help for options; no settings, cache, or play history are written.
"""

from __future__ import annotations

import argparse
import copy
import configparser
import csv
import math
from pathlib import Path
import random
import statistics
import sys
from dataclasses import dataclass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app_paths
import practice_type_rules as rules
import playlist_rules
from practice_cache import (Song, load_cache, load_definitions, load_pools,
                            read_player_settings, local_duration)

try:  # Both direct execution and importing as utils.simulate_practice work.
    from . import simulate_timed_practice as timed
except ImportError:
    import simulate_timed_practice as timed


MIN_COUNT_SONG_SECONDS = playlist_rules.MIN_COUNT_SONG_SECONDS


@dataclass
class Block:
    dance: str
    mode: str
    requested: float
    intro_seconds: float
    songs: list[Song]
    play_lengths: list[float]

    @property
    def seconds(self):
        return self.intro_seconds + sum(self.play_lengths)


def load_types(builtin_path, custom_path):
    return (rules.base_practice_types() | load_definitions(builtin_path)
            | load_definitions(custom_path))


def load_practice(name, definitions):
    if name not in definitions:
        raise ValueError(f"No practice type named {name!r}. Use --list to see names.")
    definition = rules.normalize_practice_type(
        name, definitions[name], warn=lambda message: print(message, file=sys.stderr))
    if definition is None or not definition["dances"]:
        raise ValueError(f"Practice type {name!r} has no usable dances.")
    if definition["segments"]:
        raise ValueError("Competition segment playlists are not supported by this preview.")
    for key, default in rules.BOOLEAN_DEFAULTS.items():
        definition.setdefault(key, default)
    definition["dance_adjustments"] = rules.dance_adjustments_in_use(definition)
    definition.setdefault("min_song_play_seconds", rules.DEFAULT_MIN_SONG_PLAY_SECONDS)
    definition["dance_minutes"] = rules.validate_dance_minutes(
        definition.get("dance_minutes"), definition["dances"])
    return definition


def preview_names(definitions):
    """List usable previews in menu order, with the base types at the front."""
    valid = {}
    for name in definitions:
        try:
            valid[name] = load_practice(name, definitions)
        except ValueError:
            continue
    base = [name for name in rules.base_practice_types() if name in valid]
    return base + [name for name in rules.ordered_practice_types(valid) if name not in base]


def read_settings(config_path, explicit):
    """The player's song cap and music folder, with a note in place of an unread file.

    A settings file named on the command line must exist; the player's own may
    not have been created yet.
    """
    try:
        cap, music_dir = read_player_settings(config_path)
        return cap, music_dir, f"settings: {config_path}"
    except FileNotFoundError:
        if explicit:
            raise ValueError(f"Settings file does not exist: {config_path}") from None
        problem = "no such file"
    except (OSError, ValueError, configparser.Error) as error:
        problem = str(error)
    print(f"Note: cannot read the player's settings from {config_path}: {problem}; "
          f"using {playlist_rules.DEFAULT_GLOBAL_CAP}s.", file=sys.stderr)
    return playlist_rules.DEFAULT_GLOBAL_CAP, None, f"default; {config_path} not read"


def asset_duration(cache, folder, names):
    """Read the selected local asset; use only its exact, current cache entry.

    Name fallback resolves files, never unreadable metadata. A current entry is
    trusted as the player trusts it, including one recording no duration.
    ImportError means the file exists but TinyTag is unavailable, allowing an
    explicit estimate.
    """
    asset_dir = app_paths.app_path(folder)
    path = next((path for name in names
                 if (path := playlist_rules.entry_ignoring_case(asset_dir, name, False))), None)
    if path is None:
        return None
    return local_duration(path, cache.get(path))


def intro_lengths(definition, cache, fallback, overrides):
    lengths = {}
    intros = definition["dance_intros"]
    for dance in dict.fromkeys(definition["dances"]):
        if dance in overrides:
            lengths[dance] = overrides[dance]
            continue
        intro = intros.get(dance, intros.get("default", rules.INTRO_ANNOUNCE))
        if intro == rules.INTRO_NONE:
            lengths[dance] = 0.0
            continue
        try:
            if intro == rules.INTRO_ANNOUNCE:
                duration = asset_duration(cache, "announce", [f"{dance}.ogg", "Generic.ogg"])
            else:
                duration = asset_duration(cache, "cues", [intro + ext for ext in
                                          (".ogg", ".mp3", ".wav", ".flac", ".m4a")])
        except ImportError:
            print(f"Note: {dance} intro {intro!r} exists but TinyTag is unavailable; "
                  f"estimating {fallback:g}s. Override with --dance-intro-seconds if needed.",
                  file=sys.stderr)
            duration = fallback
        if duration is None:
            print(f"Note: {dance} intro {intro!r} is missing or unreadable; skipped as in the player.",
                  file=sys.stderr)
            duration = 0.0
        lengths[dance] = duration
    return lengths


def block_mode(definition, dance, counts):
    if dance in counts:
        return "count", counts[dance]
    return rules.practice_block_rule(
        dance, definition["num_selections"],
        **{field: definition[field] for field in ("play_all_songs", "play_single_song",
           "dance_minutes", "adjust_song_counts", "dance_adjustments")})


def generate(definition, pools, intros, counts, global_cap, seed):
    """One preview playlist. Seed each dance independently to pair scenarios."""
    taken = set()
    blocks = []
    for position, dance in enumerate(definition["dances"]):
        tiers = playlist_rules.candidate_tiers(pools[dance], taken, key=lambda song: song.path)
        if definition["randomize_playlist"]:
            rng = random.Random(f"{seed}:{position}:{dance}")
            for tier in tiers:
                rng.shuffle(tier)
        candidates = [song for tier in tiers for song in tier]
        mode, requested = block_mode(definition, dance, counts)
        played = bool(candidates) and playlist_rules.block_is_played(mode, requested)
        intro = intros[dance] if played else 0.0
        cap = definition["dance_max_playtimes"].get(dance, global_cap)
        if not played:
            chosen, caps = [], []
        elif mode == "timed":
            chosen, full_lengths, planned, _dropped = playlist_rules.draw_timed(
                candidates, requested * 60 - intro, cap,
                definition["min_song_play_seconds"], lambda song: song.duration)
            caps = [playlist_rules.timed_song_cap(full, length, cap)
                    for full, length in zip(full_lengths, planned)]
        elif mode == "all":
            chosen, caps = candidates, [cap] * len(candidates)
        else:
            chosen, _fallback = playlist_rules.select_count(
                candidates, requested, MIN_COUNT_SONG_SECONDS, lambda song: song.duration)
            caps = [cap] * len(chosen)
        lengths = [playlist_rules.play_length(song.duration, song_cap,
                                              single_song=definition["play_single_song"])
                   for song, song_cap in zip(chosen, caps)]
        taken.update(song.path for song in chosen)
        blocks.append(Block(dance, mode, requested, intro, chosen, lengths))
    return blocks


def assignments(items, dances, label, integer=False, allow_zero=False):
    result = {}
    for item in items:
        dance, sep, value = item.rpartition("=")
        if not sep or dance not in dances:
            raise ValueError(f"{label}: expected DANCE=VALUE with a dance in this practice; got {item!r}.")
        number = rules.strict_int(value, label) if integer else rules.strict_number(value, label)
        if number is None or number < 0 or (number == 0 and not allow_zero):
            raise ValueError(f"{label}: {dance} needs a {'nonnegative' if allow_zero else 'positive'} "
                             f"{'integer' if integer else 'number'}.")
        if dance in result:
            raise ValueError(f"{label}: {dance!r} was specified twice.")
        result[dance] = number
    return result


def report(label, definition, pools, intros, counts, cap, runs, seed, show_playlist):
    samples = [generate(definition, pools, intros, counts, cap, seed + run) for run in range(runs)]
    rows = []
    print(f"\n{label}")
    print(f"{'Dance':20} {'Rule':>12} {'Mean songs':>11} {'Mean runtime':>14} {'P05–P95 runtime':>23}")
    # Keep repeated dance blocks distinct, in their configured order.
    for index, block in enumerate(samples[0]):
        blocks = [sample[index] for sample in samples]
        lengths = [b.seconds for b in blocks]
        song_counts = [len(b.songs) for b in blocks]
        rule = f"{block.requested:.2f} min" if block.mode == "timed" else (
            "all songs" if block.mode == "all" else f"{block.requested:g} songs")
        mean_seconds = statistics.fmean(lengths)
        low, high = timed.percentile(lengths, .05), timed.percentile(lengths, .95)
        print(f"{block.dance:20} {rule:>12} {statistics.fmean(song_counts):11.2f} "
              f"{timed.fmt_time(mean_seconds):>14} "
              f"{timed.fmt_time(low):>10}–{timed.fmt_time(high):<10}")
        rows.append({"scenario": label, "block": index + 1, "dance": block.dance, "rule": rule,
                     "mean_songs": statistics.fmean(song_counts), "mean_seconds": mean_seconds,
                     "p05_seconds": low, "p95_seconds": high})
        if block.mode == "count" and min(song_counts) < block.requested:
            print(f"  Note: only {len(pools[block.dance])} usable cached songs available.")
        if block.mode == "count" and any(song.duration < MIN_COUNT_SONG_SECONDS
                                         for b in blocks for song in b.songs):
            print(f"  Note: too few songs of at least {MIN_COUNT_SONG_SECONDS:g}s; "
                  "using the longest shorter songs.")
        if block.mode == "timed":
            short = sum(value < block.requested * 60 - 1 for value in lengths)
            over = sum(value > block.requested * 60 + 1 for value in lengths)
            print(f"  Target difference: {timed.fmt_time(mean_seconds - block.requested * 60)} mean; "
                  f"{100 * short / runs:.1f}% short, {100 * over / runs:.1f}% over (>1s).")
    totals = [sum(b.seconds for b in sample) for sample in samples]
    mean = statistics.fmean(totals)
    count = statistics.fmean(sum(len(b.songs) for b in sample) for sample in samples)
    low, high = timed.percentile(totals, .05), timed.percentile(totals, .95)
    print(f"{'TOTAL':20} {'':12} {count:11.2f} {timed.fmt_time(mean):>14} "
          f"{timed.fmt_time(low):>10}–{timed.fmt_time(high):<10}")
    rows.append({"scenario": label, "block": "", "dance": "TOTAL", "rule": "",
                 "mean_songs": count, "mean_seconds": mean, "p05_seconds": low, "p95_seconds": high})
    if show_playlist:
        print("  Example playlist (first run, including intros):")
        for block in samples[0]:
            if block.intro_seconds:
                print(f"    {block.dance}: intro {timed.fmt_time(block.intro_seconds)}")
            for song, length in zip(block.songs, block.play_lengths):
                print(f"    {block.dance}: {timed.fmt_time(length)}  {song.path}")
    return mean, rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cache", nargs="?", help="song_metadata_cache.json (default: player's cache)")
    parser.add_argument("--practice-type", default="60min", help="Named practice to preview (default: 60min)")
    parser.add_argument("--list", action="store_true", help="List practice names without loading the cache")
    parser.add_argument("--builtin-types", default=app_paths.app_path("builtin_practice_types.json"))
    parser.add_argument("--custom-types", help="Custom definitions file (default: player's file)")
    parser.add_argument("--config", help="music.ini for the baseline song cap and music folder "
                        "(default: player's settings)")
    parser.add_argument("--music-dir", help="Library root whose dance folders are previewed "
                        "(default: the player's music_dir setting)")
    parser.add_argument("--selections", type=int, action="append", default=[], metavar="N",
                        help="Change default count; repeat to compare several counts. Keeps adjustment rules; "
                             "switches play-all to counts. Timed blocks retain their budgets.")
    parser.add_argument("--dance-selections", action="append", default=[], metavar="DANCE=N",
                        help="Exact individual count, bypassing adjustments and timing; 0 skips the dance")
    parser.add_argument("--dance-minutes", action="append", default=[], metavar="DANCE=MINUTES",
                        help="Set an individual timed budget")
    parser.add_argument("--playlist-minutes", type=float, help="Scale active timed budgets proportionally; "
                        "count-based dances are additional")
    parser.add_argument("--default-cap", type=float,
                        help="Change global song cap before 10s fade (baseline: music.ini, else 210)")
    parser.add_argument("--dance-cap", action="append", default=[], metavar="DANCE=SECONDS")
    parser.add_argument("--min-play", type=float, help="Minimum duration for trimmed timed songs")
    parser.add_argument("--intro-seconds", type=float, default=10.0,
                        help="Estimate for an existing intro if TinyTag and current cache metadata "
                             "are unavailable (default: 10); missing/unreadable files are skipped")
    parser.add_argument("--dance-intro-seconds", action="append", default=[], metavar="DANCE=SECONDS",
                        help="Override a dance's intro duration, including 0 for none")
    parser.add_argument("--runs", type=int, default=1000, help="Playlists per scenario (default: 1000)")
    parser.add_argument("--seed", type=int, default=20261014, help="Reproducible random seed")
    parser.add_argument("--show-playlist", action="store_true", help="Show each scenario's first playlist")
    parser.add_argument("--csv", metavar="FILE", help="Write per-dance and total comparison statistics")
    args = parser.parse_args(argv)
    if args.runs < 1:
        parser.error("--runs must be positive")
    if any(n < 1 for n in args.selections):
        parser.error("--selections must be positive; use --dance-selections DANCE=0 to skip a dance")
    for field in ("default_cap", "min_play", "playlist_minutes", "intro_seconds"):
        value = getattr(args, field)
        if value is not None and (not math.isfinite(value) or value < 0
                                  or (value == 0 and field != "intro_seconds")):
            parser.error(f"--{field.replace('_', '-')} must be finite and "
                         f"{'nonnegative' if field == 'intro_seconds' else 'positive'}")
    try:
        custom = args.custom_types if args.custom_types is not None else app_paths.user_path(
            "custom_practice_types.json", seed_from_app_dir=False)
        if args.custom_types and not Path(custom).is_file():
            raise ValueError(f"Custom definitions file does not exist: {custom}")
        if not Path(args.builtin_types).is_file():
            raise ValueError(f"Built-in definitions file does not exist: {args.builtin_types}")
        definitions = load_types(args.builtin_types, custom)
        if args.list:
            print("\n".join(preview_names(definitions)))
            return 0
        config_path = args.config or app_paths.user_path("music.ini", seed_from_app_dir=False)
        baseline_cap, configured_music_dir, settings_source = read_settings(
            config_path, explicit=args.config is not None)
        music_dir = args.music_dir or configured_music_dir
        baseline = load_practice(args.practice_type, definitions)
        dances = baseline["dances"]
        counts = assignments(args.dance_selections, dances, "--dance-selections", True, True)
        minutes = assignments(args.dance_minutes, dances, "--dance-minutes")
        caps = assignments(args.dance_cap, dances, "--dance-cap")
        intro_overrides = assignments(args.dance_intro_seconds, dances, "--dance-intro-seconds", allow_zero=True)
        if counts.keys() & minutes.keys():
            raise ValueError("A dance cannot have both --dance-selections and --dance-minutes.")
        cache_path = args.cache or app_paths.user_path("song_metadata_cache.json", seed_from_app_dir=False)
        cache = load_cache(cache_path)
        pools = load_pools(cache, dances, music_dir)
        if not any(pools.values()):
            where = f" under {music_dir}" if music_dir else ""
            raise ValueError(f"No usable songs found for this practice{where}. Set --music-dir to the "
                             "library, or to the original root of a cache from another computer.")
        for dance, pool in pools.items():
            if not pool:
                print(f"Note: no usable cached songs for {dance}; its block will be empty.", file=sys.stderr)
        intros = intro_lengths(baseline, cache, args.intro_seconds, {})
        changed = copy.deepcopy(baseline)
        if args.selections:
            changed["play_all_songs"] = False
        changed["dance_minutes"].update(minutes)
        for dance in counts:
            changed["dance_minutes"].pop(dance, None)
        changed["dance_max_playtimes"].update(caps)
        if args.min_play is not None:
            changed["min_song_play_seconds"] = args.min_play
        if minutes and (changed["play_all_songs"] or changed["play_single_song"]):
            raise ValueError("--dance-minutes requires a practice without play-all or single-song mode.")
        if args.playlist_minutes is not None:
            if not changed["dance_minutes"] or changed["play_all_songs"] or changed["play_single_song"]:
                raise ValueError("--playlist-minutes needs active timed dances; use --dance-minutes first.")
            total_minutes = sum(changed["dance_minutes"].get(dance, 0) for dance in dances)
            scale = args.playlist_minutes / total_minutes
            changed["dance_minutes"] = {d: m * scale for d, m in changed["dance_minutes"].items()}
    except (OSError, ValueError) as error:
        parser.error(str(error))

    print(f"Practice preview: {args.practice_type} | {args.runs:,} runs | seed {args.seed}")
    print("Estimates use current cached or freshly read durations, song caps including fades, and block intros.")
    print("Randomized previews use the full available music pool; play history is not modeled.")
    print("Runtime is planned audio time; playback end margins and manual pauses are excluded.")
    print(f"Baseline global cap: {baseline_cap:g}s + {playlist_rules.FADE_SECONDS:g}s fade "
          f"({settings_source})")
    print(f"Music library: {music_dir or 'existing local cached paths in dance folders'}")
    if baseline["play_single_song"]:
        print("Single-song mode: totals describe the generated list; playback stops after each song.")
    baseline_mean, rows = report("As defined", baseline, pools, intros, {}, baseline_cap,
                                 args.runs, args.seed, args.show_playlist)
    has_changes = bool(args.selections or counts or minutes or caps or intro_overrides
                       or args.min_play is not None or args.playlist_minutes is not None
                       or args.default_cap is not None)
    if has_changes:
        changed_intros = dict(intros, **intro_overrides)
        for count in args.selections or [None]:
            scenario = copy.deepcopy(changed)
            if count is not None:
                scenario["num_selections"] = count
                scenario["play_all_songs"] = False
            label = f"Changed (default selections={count})" if count is not None else "Changed"
            mean, scenario_rows = report(label, scenario, pools, changed_intros, counts,
                                         args.default_cap if args.default_cap is not None else
                                         baseline_cap,
                                         args.runs, args.seed, args.show_playlist)
            print(f"Mean runtime change: {timed.fmt_time(mean - baseline_mean)}")
            rows.extend(scenario_rows)
    if args.csv:
        try:
            with open(args.csv, "w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
        except OSError as error:
            parser.error(str(error))
        print(f"\nWrote comparison statistics to {args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
