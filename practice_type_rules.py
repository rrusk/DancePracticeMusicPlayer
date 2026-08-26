# practice_type_rules.py
"""Validation rules for practice type definitions.

Shared by the player, which repairs what it can and warns about the rest, and by
the practice type editor, which refuses to save a definition that would need
repairing. Keeping the rules here means the editor cannot accept something the
player would then have to work around, and neither module has to import the
other.

Every validator takes a `warn` callback. The player passes something that logs;
the editor passes a list's `append` and shows what was collected.
"""

import math
import os

# What can precede a dance block. Either the spoken announcement, nothing at
# all, or the name of a cue in cues/ -- normally a few seconds of silence.
INTRO_ANNOUNCE = "announce"
INTRO_NONE = "none"

# The string formulas `_get_adjusted_song_count` understands.
ADJUSTMENT_RULES = ("n-1", "cap_at_1", "cap_at_2")

# Fields that must be true or false, with the value used when they are neither.
BOOLEAN_DEFAULTS = {
    "play_all_songs": False,
    "auto_update": False,
    "play_single_song": False,
    "randomize_playlist": True,
    "adjust_song_counts": False,
}


def _ignore(_message):
    """Default warn callback: say nothing."""


def strict_bool(value, default: bool, description: str, warn=_ignore) -> bool:
    """Returns `value` if it is a real boolean, else `default`.

    `bool("false")` is True, which is exactly the mistake a hand-edited file
    makes, so anything that is not already true or false uses the documented
    default rather than Python truthiness.
    """
    if isinstance(value, bool):
        return value
    warn(f"{description} must be true or false, not {value!r}. Using {default}.")
    return default


def strict_number(value, description: str, warn=_ignore):
    """Returns `value` as a finite float, or None if it is not one.

    Rejects booleans, which are ints in Python, and infinities and NaN, which
    Python's JSON parser accepts: an infinite block budget makes a timed block
    consume the whole dance folder, and an infinite song count crashes loading.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        warn(f"{description} must be a number, not {value!r}.")
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        warn(f"{description} must be a number, not {value!r}.")
        return None
    except OverflowError:
        # An integer too large for a float. JSON has no size limit, so this is
        # reachable from a file and used to escape validation entirely.
        warn(f"{description} is too large to be a sensible value.")
        return None
    if not math.isfinite(number):
        warn(f"{description} must be an ordinary number, not {value!r}.")
        return None
    return number


def strict_int(value, description: str, warn=_ignore):
    """Returns `value` as an int, or None if it is not a whole number.

    A fraction is rejected rather than truncated: silently turning a count of
    1.9 into 1 hides a typo in a hand-edited file.
    """
    if isinstance(value, bool):
        warn(f"{description} must be a number, not {value!r}.")
        return None
    if isinstance(value, int):
        # Used directly: going via float loses precision above 2**53, so
        # 9007199254740993 would come back as ...992.
        return value

    number = strict_number(value, description, warn)
    if number is None:
        return None
    if number != int(number):
        warn(f"{description} must be a whole number, not {value!r}.")
        return None
    return int(number)


def valid_cue_name(name) -> bool:
    """Returns True if `name` can be used to look up a file in cues/.

    Path separators are refused: a cue name is joined onto the cues directory,
    and a name like "../../something" would reach outside it.
    """
    return (isinstance(name, str) and bool(name.strip())
            and not any(part in name for part in ("/", "\\", os.pardir))
            and name == os.path.basename(name))


def validate_dance_intros(raw, warn=_ignore) -> dict:
    """Returns the usable entries of a `dance_intros` mapping.

    Each value says what precedes that dance's block: "announce" for the spoken
    announcement, "none" for nothing, or the name of a cue in cues/ -- normally
    a few seconds of silence. A "default" key applies to every dance that is not
    named individually, matching how `dance_adjustments` works.

    Args:
        raw: The value of the practice type's "dance_intros" key.
        warn: Called with a description of anything dropped.

    Returns:
        A mapping the player can apply.
    """
    if not raw:
        return {}
    if not isinstance(raw, dict):
        warn(f"Dance Intros: must be a JSON object, not a {type(raw).__name__}.")
        return {}

    clean = {}
    for dance, intro in raw.items():
        if intro in (INTRO_ANNOUNCE, INTRO_NONE):
            clean[dance] = intro
        elif valid_cue_name(intro):
            clean[dance] = intro
        else:
            warn(f"Dance Intros: '{dance}' must be \"{INTRO_ANNOUNCE}\", "
                 f"\"{INTRO_NONE}\", or the name of a cue in cues/, not {intro!r}.")
    return clean


def validate_dance_adjustments(raw, warn=_ignore) -> dict:
    """Returns the usable entries of a `dance_adjustments` mapping.

    A rule is either one of `ADJUSTMENT_RULES` or a mapping from a song count to
    the count to use instead. Only the outer type used to be checked, so a rule
    like `{"2": "two"}` reached the arithmetic in `_get_adjusted_song_count`, and
    a negative count made the selector walk the entire dance folder instead of
    rejecting the value.

    Args:
        raw: The value of the practice type's "dance_adjustments" key.
        warn: Called with a description of anything dropped.

    Returns:
        A mapping containing only rules the player can apply.
    """
    if not isinstance(raw, dict):
        warn(f"Dance Adjustments: must be a JSON object, not a {type(raw).__name__}.")
        return {}

    clean = {}
    for dance, rule in raw.items():
        if isinstance(rule, str):
            if rule not in ADJUSTMENT_RULES:
                warn(f"Dance Adjustments: '{dance}' has unknown rule \"{rule}\"; "
                     f"expected one of {', '.join(ADJUSTMENT_RULES)}.")
                continue
            clean[dance] = rule

        elif isinstance(rule, dict):
            mapping = {}
            for count, result in rule.items():
                if not (count == "default" or str(count).isdigit()):
                    warn(f"Dance Adjustments: '{dance}' has key \"{count}\"; keys must "
                         "be song counts or \"default\".")
                    continue
                if isinstance(result, bool) or not isinstance(result, int):
                    warn(f"Dance Adjustments: '{dance}' -> \"{count}\" must be a whole "
                         "number of songs.")
                    continue
                if result < 0:
                    warn(f"Dance Adjustments: '{dance}' -> \"{count}\" cannot be "
                         "negative.")
                    continue
                mapping[str(count)] = result
            if mapping:
                clean[dance] = mapping

        else:
            warn(f"Dance Adjustments: '{dance}' must be a rule name or an object, "
                 f"not a {type(rule).__name__}.")

    return clean


def validate_segments(raw, warn=_ignore) -> list:
    """Returns the usable entries of a `segments` list.

    A segment is either a cue or a round. Timing values are checked as well as
    types: a negative clip length cuts a song off before it starts, and a
    negative gap looks for a cue named `gap_-5`, silently shortening the round.

    `fade_seconds` comes out of the clip rather than being added to it, so a
    ninety second clip with a five second fade still runs ninety seconds and the
    round keeps its length.

    Args:
        raw: The value of the practice type's "segments" key.
        warn: Called with a description of anything dropped.

    Returns:
        Validated segments with defaults filled in.
    """
    if raw is None:
        return []
    if not isinstance(raw, list):
        # Checked before the empty test: an empty object is falsy too, and would
        # otherwise be accepted silently as "no segments".
        warn(f"Segments: must be a JSON list, not a {type(raw).__name__}.")
        return []
    if not raw:
        return []

    validated = []
    for index, segment in enumerate(raw):
        position = f"Segment {index + 1}"

        if not isinstance(segment, dict):
            warn(f"{position}: must be a JSON object.")
            continue

        if cue := segment.get("cue"):
            if not valid_cue_name(cue):
                warn(f"{position}: \"cue\" must be the name of a file in cues/, "
                     f"not {cue!r}.")
                continue
            validated.append({"cue": cue, "label": segment.get("label")})
            continue

        dances = segment.get("round")
        if not isinstance(dances, list) or not dances:
            warn(f"{position}: needs either a \"cue\" or a non-empty \"round\".")
            continue

        names = [dance for dance in dances if isinstance(dance, str) and dance.strip()]
        if len(names) != len(dances):
            warn(f"{position}: \"round\" contains entries that are not dance names.")
            continue

        count = strict_int(segment.get("count", 1), f"{position}: \"count\"", warn)
        gap_seconds = strict_int(segment.get("gap_seconds", 0),
                                 f"{position}: \"gap_seconds\"", warn)
        # A clip length is either absent, meaning songs play at their own
        # length, or a positive number. Zero used to fall through to "absent",
        # which quietly accepted a value the warning below says is wrong.
        clip_seconds = None
        if (clip_raw := segment.get("clip_seconds")) is not None:
            clip_seconds = strict_number(clip_raw, f"{position}: \"clip_seconds\"", warn)
            if clip_seconds is None:
                continue
        fade_seconds = strict_number(segment.get("fade_seconds", 0),
                                     f"{position}: \"fade_seconds\"", warn)
        if count is None or gap_seconds is None or fade_seconds is None:
            continue

        if count < 1:
            warn(f"{position}: \"count\" must be at least 1.")
            continue
        if clip_seconds is not None and clip_seconds <= 0:
            warn(f"{position}: \"clip_seconds\" must be positive.")
            continue
        if gap_seconds < 0:
            warn(f"{position}: \"gap_seconds\" cannot be negative.")
            continue
        if fade_seconds < 0:
            warn(f"{position}: \"fade_seconds\" cannot be negative.")
            continue
        if fade_seconds > 0 and clip_seconds is None:
            # The fade is taken out of the clip, so without one there is
            # nothing for it to come out of and it would do nothing at all.
            warn(f"{position}: \"fade_seconds\" needs a \"clip_seconds\" to be "
                 "taken out of; a song played at its own length is not faded.")
            continue
        if clip_seconds is not None and fade_seconds >= clip_seconds:
            # The fade is taken out of the clip, not added to it, so a fade as
            # long as the clip would mean the song never reaches full volume.
            warn(f"{position}: \"fade_seconds\" must be shorter than "
                 f"\"clip_seconds\" ({clip_seconds:g}s), since the fade happens "
                 "within the clip rather than after it.")
            continue

        validated.append({
            "round": names,
            "count": count,
            "clip_seconds": clip_seconds,
            "gap_seconds": gap_seconds,
            "fade_seconds": fade_seconds,
            "announce": strict_bool(segment.get("announce", False), False,
                                    f"{position}: \"announce\"", warn),
            "label": segment.get("label"),
        })

    return validated


def normalize_practice_type(name, data, warn=None):
    """Checks and repairs one practice type definition.

    These values are assigned straight to Kivy properties, where a dict property
    given a list or a number raises during `set_practice_type` -- on the UI
    thread, during startup, where nothing catches it. A hand-edited file with the
    wrong type in one field would stop the application from starting.

    Args:
        name: The practice type name, used in the warnings.
        data: The definition as loaded from JSON.
        warn: Called with a description of anything repaired. Prints by default.

    Returns:
        A definition safe to use, or None if it cannot be salvaged.
    """
    if warn is None:
        def warn(message):
            print(f"Practice type '{name}': {message}")

    if not isinstance(data, dict):
        warn(f"definition must be a JSON object, not a {type(data).__name__}. "
             "Skipping it.")
        return None

    clean = dict(data)

    dances = clean.get("dances", [])
    if not isinstance(dances, list):
        warn(f"'dances' must be a list, not a {type(dances).__name__}. Using none.")
        dances = []
    valid_dances = [d for d in dances if isinstance(d, str) and d.strip()]
    if len(valid_dances) != len(dances):
        warn("'dances' contained entries that are not names; they were dropped.")
    clean["dances"] = valid_dances

    selections = strict_int(clean.get("num_selections", 2), "'num_selections'")
    if selections is None:
        warn(f"'num_selections' is not a number ({clean.get('num_selections')!r}). Using 2.")
        selections = 2
    if selections < 1:
        warn(f"'num_selections' must be at least 1 ({selections}). Using 1.")
        selections = 1
    clean["num_selections"] = selections

    # Where this type sits in the practice type list. Everything defaults to 0
    # and keeps its position in the file; a higher number sinks to the bottom,
    # which is how the types actually in use are kept together at the end
    # whatever else has been added.
    order = clean.get("order", 0)
    if (order := strict_int(order, "'order'", warn)) is None:
        order = 0
    clean["order"] = order

    clean["dance_adjustments"] = validate_dance_adjustments(
        clean.get("dance_adjustments", {}), warn)
    clean["dance_intros"] = validate_dance_intros(clean.get("dance_intros", {}), warn)

    for key in ("dance_max_playtimes", "dance_minutes"):
        value = clean.get(key, {})
        if not isinstance(value, dict):
            warn(f"'{key}' must be a JSON object, not a {type(value).__name__}. "
                 "Ignoring it.")
            clean[key] = {}

    playtimes = {}
    for dance, seconds in clean.get("dance_max_playtimes", {}).items():
        seconds = strict_number(seconds, f"'dance_max_playtimes' for '{dance}'", warn)
        if seconds is None:
            continue
        if seconds <= 0:
            warn(f"'dance_max_playtimes' for '{dance}' must be positive. Ignoring it.")
            continue
        playtimes[dance] = seconds
    clean["dance_max_playtimes"] = playtimes

    clean["segments"] = validate_segments(clean.get("segments", []), warn)

    for key, default in BOOLEAN_DEFAULTS.items():
        if key in clean:
            clean[key] = strict_bool(clean[key], default, f"'{key}'", warn)

    return clean
