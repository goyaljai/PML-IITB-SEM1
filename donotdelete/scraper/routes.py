"""
Route enumeration and 3-day batch rotation.

The route universe is ``itertools.permutations(IATA_codes, 2)`` — 15 cities ×
14 destinations = **210 directed routes**. The rotation distributes them across
three days so a full pass through the universe completes every 72 hours.

> **Fix vs legacy v3:** the old scraper advanced the rotation counter *before*
> the scrape ran, so a crashed run silently skipped that day's batch until the
> next 3-day cycle. v4 separates the read from the advance:
>
>   1. Pipeline calls ``current_batch(state_dir)`` at the start — pure read.
>   2. After a successful run, the pipeline calls ``advance_batch(state_dir)``.
>   3. On failure the counter stays put, so the next cron retries the same batch.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from pathlib import Path

# Filename for the rotation counter inside ``state_dir`` (see ``config.py``).
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


def current_batch(
    cities: dict[str, str],
    n_batches: int,
    state_dir: Path,
) -> Batch:
    """Read the rotation counter and return today's batch (PURE READ — no write)."""
    state_dir.mkdir(parents=True, exist_ok=True)
    state_file = state_dir / BATCH_STATE_FILENAME
    counter = 0
    if state_file.is_file():
        try:
            counter = int(state_file.read_text(encoding="utf-8").strip() or "0")
        except ValueError:
            # Treat corrupt state as "start of the rotation" — never crash on
            # bad state file; logging upstream notes it.
            counter = 0
    if counter < 0:
        counter = 0
    routes = all_routes(cities)
    batch_index = counter % n_batches
    return Batch(
        index=batch_index,
        cycle_count=counter // n_batches,
        routes=batch_for_index(routes, batch_index, n_batches),
    )


def advance_batch(state_dir: Path) -> int:
    """Atomically increment the rotation counter and return the new value.

    Called by the pipeline ONLY after a successful run. Write is atomic via
    rename so a kill between truncate and write can't corrupt the counter.
    """
    state_dir.mkdir(parents=True, exist_ok=True)
    state_file = state_dir / BATCH_STATE_FILENAME
    current = 0
    if state_file.is_file():
        try:
            current = int(state_file.read_text(encoding="utf-8").strip() or "0")
        except ValueError:
            current = 0
    new_value = current + 1
    tmp = state_file.with_suffix(".tmp")
    tmp.write_text(f"{new_value}\n", encoding="utf-8")
    tmp.replace(state_file)
    return new_value
