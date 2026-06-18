"""Canary patience and abort semantics."""

from __future__ import annotations

from datetime import datetime
from unittest import mock

import pytest

from scraper import canary
from scraper.adapter import AdapterError, FlightsNotFound, NormalizedFlight


def _ok_flight(price=7876):
    return NormalizedFlight(
        price=price, airline="IndiGo", airlines=("IndiGo",),
        flight_number="", aircraft="A320neo",
        departure_dt=datetime(2026, 6, 25, 6, 5),
        arrival_dt=datetime(2026, 6, 25, 8, 25),
        duration_mins=140, stops=0,
        layover_city="", layover_duration_mins=None,
        self_transfer=False, co2_g=103000, co2_typical_g=100000, co2_delta_pct=3,
    )


def test_canary_succeeds_on_first_probe():
    with mock.patch("scraper.canary.adapter.search_flights", return_value=[_ok_flight()]):
        ok = canary.run(
            origin="BOM", destination="DEL", days_out=7,
            max_wait_seconds=10, probe_interval_seconds=0,
            api_timeout_seconds=5,
            per_probe_attempts=1, backoff_base=0, backoff_max=0, backoff_jitter=0,
            now_fn=lambda: 0.0, sleep_fn=lambda _s: None,
        )
    assert ok is True


def test_canary_retries_then_succeeds():
    side = [FlightsNotFound("empty"), [_ok_flight()]]

    def fn(*a, **k):
        v = side.pop(0)
        if isinstance(v, Exception):
            raise v
        return v

    times = iter([0.0, 1.0, 2.0])
    with mock.patch("scraper.canary.adapter.search_flights", side_effect=fn):
        ok = canary.run(
            origin="BOM", destination="DEL", days_out=7,
            max_wait_seconds=10, probe_interval_seconds=0,
            api_timeout_seconds=5,
            per_probe_attempts=1, backoff_base=0, backoff_max=0, backoff_jitter=0,
            now_fn=lambda: next(times), sleep_fn=lambda _s: None,
        )
    assert ok is True


def test_canary_gives_up_after_window():
    """Sustained empties for the whole window → False."""
    # First call (deadline init) returns 1.0 → deadline = 1.5.
    # Second call (in-loop check) returns 2.0 → past deadline → return False.
    times = iter([1.0, 2.0])
    with mock.patch("scraper.canary.adapter.search_flights", side_effect=FlightsNotFound("empty")):
        ok = canary.run(
            origin="BOM", destination="DEL", days_out=7,
            max_wait_seconds=0.5, probe_interval_seconds=0,
            api_timeout_seconds=5,
            per_probe_attempts=1, backoff_base=0, backoff_max=0, backoff_jitter=0,
            now_fn=lambda: next(times), sleep_fn=lambda _s: None,
        )
    assert ok is False


def test_canary_errors_are_not_fatal_within_window():
    """A transient error early in the window should not abort the canary; it
    keeps probing until either success or deadline."""
    side = [AdapterError("boom"), [_ok_flight()]]

    def fn(*a, **k):
        v = side.pop(0)
        if isinstance(v, Exception):
            raise v
        return v

    times = iter([0.0, 0.0, 1.0])
    with mock.patch("scraper.canary.adapter.search_flights", side_effect=fn):
        ok = canary.run(
            origin="BOM", destination="DEL", days_out=7,
            max_wait_seconds=10, probe_interval_seconds=0,
            api_timeout_seconds=5,
            per_probe_attempts=1, backoff_base=0, backoff_max=0, backoff_jitter=0,
            now_fn=lambda: next(times), sleep_fn=lambda _s: None,
        )
    assert ok is True
