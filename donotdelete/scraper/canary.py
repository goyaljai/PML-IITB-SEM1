"""
Startup canary.

Before the pipeline commits to a full ~2-hour scrape, it sanity-checks the
plumbing with one search on a known-busy route (BOM→DEL +7d by default). If
this succeeds, the rest of the run is overwhelmingly likely to work. If it
sustainly fails, the run aborts BEFORE perturbing the rotation counter so the
next cron retries the same batch unmodified.

The canary is **patient**: a fresh-IP scenario (VPS rebooted, ISP failover)
often shows a "warm-up" period during which the API returns empty results.
We retry across a configurable window (default 15 min) before declaring the
pipeline broken.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Callable

from . import adapter

log = logging.getLogger("canary")


def run(
    *,
    origin: str,
    destination: str,
    days_out: int,
    max_wait_seconds: float,
    probe_interval_seconds: float,
    api_timeout_seconds: int,
    per_probe_attempts: int,
    backoff_base: float,
    backoff_max: float,
    backoff_jitter: float,
    cabin: str = "economy",
    adults: int = 1,
    currency: str = "INR",
    now_fn: Callable[[], float] = time.monotonic,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> bool:
    """Return True iff at least one priced flight comes back within the window."""
    target_date = (datetime.now(timezone.utc) + timedelta(days=days_out)).strftime("%Y-%m-%d")
    log.info(
        "canary start: %s→%s on %s (window=%ds interval=%ds)",
        origin, destination, target_date, int(max_wait_seconds), int(probe_interval_seconds),
    )

    deadline = now_fn() + max_wait_seconds
    attempt = 0

    while True:
        attempt += 1
        try:
            results = adapter.search_flights(
                origin=origin,
                destination=destination,
                date_str=target_date,
                cabin=cabin,
                adults=adults,
                currency=currency,
                timeout_seconds=api_timeout_seconds,
                max_attempts=per_probe_attempts,
                backoff_base=backoff_base,
                backoff_max=backoff_max,
                backoff_jitter=backoff_jitter,
                sleep_fn=sleep_fn,
            )
        except adapter.FlightsNotFound:
            log.info("canary probe %d: empty (likely warm-up); retrying", attempt)
            results = []
        except adapter.APITimeout as e:
            log.warning("canary probe %d: timeout: %s", attempt, e)
            results = []
        except adapter.AdapterError as e:
            log.warning("canary probe %d: error: %s", attempt, e)
            results = []
        else:
            # search_flights already retried internally — if it returned, we
            # have a non-empty list. But defend against future refactors.
            priced = [f for f in results if f.price]
            if priced:
                cheapest = min(p.price for p in priced)
                log.info(
                    "canary OK on probe %d: %d results, cheapest ₹%d",
                    attempt, len(results), cheapest,
                )
                return True

        if now_fn() >= deadline:
            log.error(
                "canary FAILED — no fares for %s→%s after %d probes (%ds window)",
                origin, destination, attempt, int(max_wait_seconds),
            )
            return False

        sleep_fn(probe_interval_seconds)
