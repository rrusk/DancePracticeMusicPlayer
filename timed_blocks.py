# timed_blocks.py
"""Planning for timed practice blocks.

A dance listed in a practice type's `dance_minutes` is played for that many
minutes rather than for a set number of songs. These functions decide how long
each song in such a block plays. They have no Kivy dependency, so the player and
utils/simulate_timed_practice.py run the same planner.
"""

# Largest uniform trim applied to each song to make a block fit its budget.
# If the trim would exceed this, the last song is dropped and the block runs
# short instead, rather than audibly chopping every song in the block.
MAX_TRIM_SECONDS = 45


def apply_uniform_trim(lengths: list[float], total_trim: float,
                       min_play: float) -> list[float]:
    """Spreads `total_trim` seconds evenly across `lengths`.

    Every song gives up the same number of seconds, so songs keep their
    relative lengths -- a block is not a run of identical clips. A song is
    never taken below `min_play`; whatever it cannot absorb is redistributed
    over the songs that still have headroom.

    Args:
        lengths: Planned play length of each song, in seconds.
        total_trim: Total seconds that must come out of the block.
        min_play: Floor below which no song may be trimmed.

    Returns:
        The trimmed lengths. If the block cannot absorb the whole trim, the
        result sums to more than the budget and the caller reports it.
    """
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


def plan_timed_block(lengths: list[float], budget: float,
                     max_trim: float, min_play: float) -> list[float]:
    """Decides how long each song in a timed block should play.

    `lengths` are the effective (cap-limited) lengths of the songs drawn for
    the block, in play order, drawn until their total reached `budget`. The
    overshoot is shared evenly across all of them so the block ends exactly on
    budget. If that share would be a bigger cut than `max_trim`, the last song
    is dropped and the block runs short instead.

    Returns:
        Planned play lengths for the songs that are kept -- always a prefix of
        `lengths`, possibly empty.
    """
    kept = [float(length) for length in lengths]

    while kept:
        overshoot = sum(kept) - budget
        if overshoot <= 0:
            # Songs ran out before the budget was met: play them untrimmed.
            return kept
        if overshoot / len(kept) <= max_trim or len(kept) == 1:
            return apply_uniform_trim(kept, overshoot, min_play)
        kept.pop()

    return []
