"""Adapter retry / normalisation — mocks fast-flights to avoid network."""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass
from datetime import datetime
from unittest import mock

import pytest


# ── Fake fast-flights module ─────────────────────────────────────────────────


@dataclass
class _SDT:
    date: tuple
    time: tuple


@dataclass
class _Airport:
    name: str
    code: str


@dataclass
class _Leg:
    from_airport: _Airport
    to_airport: _Airport
    departure: _SDT
    arrival: _SDT
    duration: int
    plane_type: str


@dataclass
class _Carbon:
    typical_on_route: int
    emission: int


@dataclass
class _Flight:
    type: str
    price: int
    airlines: list
    flights: list
    carbon: _Carbon


def _make_fake_flight(price=7876, airline="SpiceJet", stops=0,
                      origin="BOM", destination="DEL", connect="HYD") -> _Flight:
    # Topology: nonstop legs go origin → destination directly; multi-leg
    # itineraries pass through `connect` (the layover airport).
    if stops == 0:
        legs = [_Leg(
            from_airport=_Airport(name=origin, code=origin),
            to_airport=_Airport(name=destination, code=destination),
            departure=_SDT(date=(2026, 6, 25), time=(6, 5)),
            arrival=_SDT(date=(2026, 6, 25), time=(8, 25)),
            duration=140,
            plane_type="Airbus A320neo",
        )]
    else:
        legs = [
            _Leg(
                from_airport=_Airport(name=origin, code=origin),
                to_airport=_Airport(name=connect, code=connect),
                departure=_SDT(date=(2026, 6, 25), time=(6, 5)),
                arrival=_SDT(date=(2026, 6, 25), time=(8, 25)),
                duration=140,
                plane_type="Airbus A320neo",
            ),
            _Leg(
                from_airport=_Airport(name=connect, code=connect),
                to_airport=_Airport(name=destination, code=destination),
                departure=_SDT(date=(2026, 6, 25), time=(9, 0)),
                arrival=_SDT(date=(2026, 6, 25), time=(11, 0)),
                duration=120,
                plane_type="Airbus A321neo",
            ),
        ]
    return _Flight(
        type="multi" if stops else "non-stop",
        price=price,
        airlines=[airline],
        flights=legs,
        carbon=_Carbon(typical_on_route=100000, emission=103000),
    )


class _FfNotFound(Exception):
    pass


@pytest.fixture()
def fake_fast_flights(monkeypatch):
    """Install a fake ``fast_flights`` module before each test."""
    mod = types.ModuleType("fast_flights")
    mod.FlightsNotFound = _FfNotFound  # type: ignore[attr-defined]
    mod.FlightQuery = lambda **kw: kw                                        # type: ignore[attr-defined]
    mod.Passengers = lambda **kw: kw                                          # type: ignore[attr-defined]
    mod.create_filter = lambda **kw: kw                                       # type: ignore[attr-defined]

    # Hook the caller is meant to set: mod.get_flights = some_callable
    monkeypatch.setitem(sys.modules, "fast_flights", mod)
    return mod


# ── Tests ────────────────────────────────────────────────────────────────────


def test_normalises_single_priced_result(fake_fast_flights):
    fake_fast_flights.get_flights = lambda q: [_make_fake_flight(price=7876)]
    from scraper import adapter
    out = adapter.search_flights(
        origin="BOM", destination="DEL", date_str="2026-06-25",
        max_attempts=1, sleep_fn=lambda _s: None,
    )
    assert len(out) == 1
    f = out[0]
    assert f.price == 7876
    assert f.airline == "SpiceJet"
    assert f.stops == 0
    assert f.aircraft == "Airbus A320neo"
    assert f.duration_mins == 140
    assert isinstance(f.departure_dt, datetime)
    assert f.co2_g == 103000
    assert f.co2_typical_g == 100000
    assert f.co2_delta_pct == 3   # round((103000 - 100000) / 100000 * 100)


def test_retries_then_succeeds(fake_fast_flights):
    calls = {"n": 0}

    def flaky(_q):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("network glitch")
        return [_make_fake_flight()]

    fake_fast_flights.get_flights = flaky
    from scraper import adapter
    out = adapter.search_flights(
        origin="BOM", destination="DEL", date_str="2026-06-25",
        max_attempts=3, backoff_base=0, backoff_max=0, backoff_jitter=0,
        sleep_fn=lambda _s: None,
    )
    assert len(out) == 1
    assert calls["n"] == 3


def test_propagates_error_after_max_attempts(fake_fast_flights):
    def always_fail(_q):
        raise RuntimeError("boom")

    fake_fast_flights.get_flights = always_fail
    from scraper import adapter
    with pytest.raises(adapter.AdapterError):
        adapter.search_flights(
            origin="BOM", destination="DEL", date_str="2026-06-25",
            max_attempts=2, backoff_base=0, backoff_max=0, backoff_jitter=0,
            sleep_fn=lambda _s: None,
        )


def test_empty_result_raises_flights_not_found(fake_fast_flights):
    fake_fast_flights.get_flights = lambda _q: []
    from scraper import adapter
    with pytest.raises(adapter.FlightsNotFound):
        adapter.search_flights(
            origin="BOM", destination="DEL", date_str="2026-06-25",
            max_attempts=2, backoff_base=0, backoff_max=0, backoff_jitter=0,
            sleep_fn=lambda _s: None,
        )


def test_ff_not_found_exception_propagates_as_flights_not_found(fake_fast_flights):
    def raise_nf(_q):
        raise _FfNotFound("nothing")

    fake_fast_flights.get_flights = raise_nf
    from scraper import adapter
    with pytest.raises(adapter.FlightsNotFound):
        adapter.search_flights(
            origin="BOM", destination="DEL", date_str="2026-06-25",
            max_attempts=2, backoff_base=0, backoff_max=0, backoff_jitter=0,
            sleep_fn=lambda _s: None,
        )


def test_multi_leg_layover_extraction(fake_fast_flights):
    fake_fast_flights.get_flights = lambda _q: [_make_fake_flight(stops=1)]
    from scraper import adapter
    [f] = adapter.search_flights(
        origin="BOM", destination="DEL", date_str="2026-06-25",
        max_attempts=1, sleep_fn=lambda _s: None,
    )
    assert f.stops == 1
    assert f.layover_city == "HYD"
    # Departure leg arrives 8:25, second leg departs 9:00 → 35 min layover.
    assert f.layover_duration_mins == 35


def test_price_none_when_zero_or_missing(fake_fast_flights):
    f0 = _make_fake_flight(price=0)
    fake_fast_flights.get_flights = lambda _q: [f0]
    from scraper import adapter
    [n] = adapter.search_flights(
        origin="BOM", destination="DEL", date_str="2026-06-25",
        max_attempts=1, sleep_fn=lambda _s: None,
    )
    assert n.price is None


def test_backoff_called_between_attempts(fake_fast_flights):
    """Confirm we actually sleep between attempts."""
    calls = {"n": 0}

    def flaky(_q):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("once")
        return [_make_fake_flight()]

    sleeps = []
    fake_fast_flights.get_flights = flaky
    from scraper import adapter
    adapter.search_flights(
        origin="BOM", destination="DEL", date_str="2026-06-25",
        max_attempts=3, backoff_base=2.0, backoff_max=10.0, backoff_jitter=0.0,
        sleep_fn=lambda s: sleeps.append(s),
    )
    assert len(sleeps) == 1
    assert sleeps[0] >= 2.0
