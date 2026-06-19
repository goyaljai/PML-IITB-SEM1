"""
Route enumeration and 3-day batch rotation.

The route universe is ``itertools.permutations(IATA_codes, 2)`` — 15 cities ×
14 destinations = **210 directed routes**. The rotation distributes them across
three days so a full pass through the universe completes every 72 hours.

> **Rotation is a pure function of the UTC date — the past cannot break the
> future.** ``batch_index = days_since_epoch % n_batches``. There is no
> success-gated counter and no persistent state, so a degraded, failed, or
> entirely-skipped run CANNOT starve future batches: tomorrow's batch is
> determined solely by tomorrow's date. Every 3-day window covers all 210
> routes regardless of what happened on any prior day.
>
> This replaced the legacy success-gated counter (advanced only on a passing
> run). That design had a latent freeze: if the routes that landed in the
> rotation-advancing slice were chronically broken, the counter never moved and
> two-thirds of the universe was never collected. Decoupling rotation from
> success removes that coupling entirely.
>
> UTC (not the display timezone) is deliberate: all of a day's slices fire
> within the same UTC calendar day (00:17–21:17 UTC), so they all compute the
> SAME ``batch_index`` and partition the same batch. Keying off IST would put
> the late slice (21:17 UTC = 02:47 IST next day) on a different date than its
> siblings and split the batch across two rotation indices.
"""

from __future__ import annotations

import datetime as _dt
import itertools
from dataclasses import dataclass
from pathlib import Path

# Fixed reference date for the date-based rotation. Arbitrary but immutable:
# changing it would shift which batch a given date maps to. 2000-01-01 (a
# Saturday) is well before any data we hold, so day_number is always positive.
ROTATION_EPOCH = _dt.date(2000, 1, 1)

# Retained for backward compatibility with any external reader; the date-based
# rotation no longer writes or reads a counter file.
BATCH_STATE_FILENAME = ".batch_state"


@dataclass(frozen=True)
class Batch:
    """A single day's slice of the route universe."""

    index: int                            # 0-based batch index within the cycle
    cycle_count: int                      # how many full cycles have completed
    routes: list[tuple[str, str]]         # [(origin_iata, dest_iata), ...]


def all_routes(cities: dict[str, str]) -> list[tuple[str, str]]:
    """All directed (origin, destination) IATA pairs, deterministically ordered.

    Order: sorted by IATA code → permutations → list. So a given ``cities``
    dict always yields the SAME route order, making the batch rotation stable
    across processes, machines, and Python builds.
    """
    codes = sorted(set(cities.values()))
    return list(itertools.permutations(codes, 2))


def batch_for_index(
    routes: list[tuple[str, str]],
    batch_index: int,
    n_batches: int,
) -> list[tuple[str, str]]:
    """The slice of ``routes`` that belongs to ``batch_index`` (0-based).

    The last batch absorbs any remainder so every route is covered exactly
    once per cycle.
    """
    if n_batches < 1:
        raise ValueError("n_batches must be ≥ 1")
    if not (0 <= batch_index < n_batches):
        raise ValueError(f"batch_index {batch_index} out of range [0, {n_batches})")
    size = len(routes) // n_batches
    start = batch_index * size
    end = len(routes) if batch_index == n_batches - 1 else start + size
    return routes[start:end]


def batch_slice(
    routes: list[tuple[str, str]],
    slice_index: int,
    slice_count: int,
) -> list[tuple[str, str]]:
    """The ``slice_index``-th contiguous slice (1-based) of ``slice_count``.

    Used to spread a day's batch across multiple cron fires (e.g. 8 slices,
    one every 3 h) so the request rate stays low enough to avoid Google's
    per-IP rate-limit. The last slice absorbs any remainder so the union of all
    slices is exactly the input list — every route in the batch is covered once
    per day across the slices.
    """
    if slice_count < 1:
        raise ValueError("slice_count must be ≥ 1")
    if not (1 <= slice_index <= slice_count):
        raise ValueError(f"slice_index {slice_index} out of range [1, {slice_count}]")
    size = len(routes) // slice_count
    start = (slice_index - 1) * size
    end = len(routes) if slice_index == slice_count else start + size
    return routes[start:end]


def batch_index_for_date(day: _dt.date, n_batches: int) -> int:
    """Map a calendar date to a rotation batch index — the whole rotation logic.

    Pure and stateless: ``(day - ROTATION_EPOCH).days % n_batches``. Same date →
    same index, always; consecutive dates step through 0, 1, 2, 0, 1, 2 … so the
    full route universe is covered every ``n_batches`` days no matter what
    happened on any prior day.
    """
    if n_batches < 1:
        raise ValueError("n_batches must be ≥ 1")
    day_number = (day - ROTATION_EPOCH).days
    return day_number % n_batches


def current_batch(
    cities: dict[str, str],
    n_batches: int,
    state_dir: Path,  # kept for signature stability; unused (rotation is stateless)
    *,
    today: _dt.date | None = None,
) -> Batch:
    """Return today's batch as a pure function of the UTC date — no state.

    ``state_dir`` is accepted for backward-compatible call sites but is no longer
    read or written: the batch is derived from the calendar date so a failed or
    skipped run on any prior day cannot affect which batch runs today. ``today``
    is injectable for tests; it defaults to the current UTC date (UTC so all of
    a day's slices agree — see module docstring).
    """
    day = today or _dt.datetime.now(_dt.timezone.utc).date()
    routes = all_routes(cities)
    batch_index = batch_index_for_date(day, n_batches)
    cycle_count = (day - ROTATION_EPOCH).days // n_batches
    return Batch(
        index=batch_index,
        cycle_count=cycle_count,
        routes=batch_for_index(routes, batch_index, n_batches),
    )


def advance_batch(state_dir: Path) -> int:
    """No-op shim — rotation is now stateless (date-based), so there is nothing
    to advance. Retained so existing call sites don't break; returns -1 to make
    "rotation is not counter-driven" obvious in any log that prints the result.

    The pipeline/CLI no longer need to call this; it remains only as a guard
    against an older caller still wired to the previous contract.
    """
    return -1
