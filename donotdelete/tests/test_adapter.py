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


def test_real_sigalrm_timeout_fires(fake_fast_flights):
    """The per-call SIGALRM timeout actually fires on a hung call.

    This exercises the real `_call_timeout` context manager (not mocked) by
    making `get_flights` sleep longer than the configured timeout. The first
    call should raise APITimeout; subsequent retries are short-circuited via
    max_attempts=1 so the test runs quickly.
    """
    import time
    fake_fast_flights.get_flights = lambda _q: time.sleep(10)  # hang past the timeout
    from scraper import adapter
    t0 = time.monotonic()
    with pytest.raises(adapter.AdapterError):
        adapter.search_flights(
            origin="BOM", destination="DEL", date_str="2026-06-25",
            timeout_seconds=1,
            max_attempts=1, backoff_base=0, backoff_max=0, backoff_jitter=0,
            sleep_fn=lambda _s: None,
        )
    elapsed = time.monotonic() - t0
    # SIGALRM should fire within ~1s; allow 3s grace for slow CI.
    assert elapsed < 3.0, f"timeout did not fire within budget (elapsed {elapsed:.2f}s)"


def test_to_datetime_on_the_hour_one_element_time():
    """REGRESSION: fast-flights omits minutes for on-the-hour times, sending
    ``time=[17]`` (5:00 PM) instead of ``time=[17, 0]``. The old strict
    ``hh, mm = sdt.time`` unpack raised ValueError → the time silently became
    empty, so every on-the-hour flight (often the Median row) lost its
    Departure/Arrival time columns. We now default the missing minutes to 0."""
    from scraper.adapter import _to_datetime

    on_hour = _SDT(date=[2026, 7, 19], time=[17])      # 5:00 PM, minutes omitted
    dt = _to_datetime(on_hour)
    assert dt == datetime(2026, 7, 19, 17, 0)

    with_min = _SDT(date=[2026, 7, 19], time=[17, 45])  # 5:45 PM, both fields
    assert _to_datetime(with_min) == datetime(2026, 7, 19, 17, 45)

    # Defensive: empty / short / missing payloads still degrade to None.
    assert _to_datetime(None) is None
    assert _to_datetime(_SDT(date=[2026, 7], time=[17, 0])) is None  # bad date


def test_to_datetime_missing_hour_is_honest_blank():
    """REGRESSION: fast-flights sometimes emits a garbled time where the HOUR
    element is None (observed live: AMD->DEL IndiGo ₹4814 had time=[None, 5]).
    We must NOT fabricate an hour by zero-filling — an unknown hour means an
    unknown time, so _to_datetime returns None (the row keeps its real price but
    an honest blank time) rather than inventing 00:05."""
    from scraper.adapter import _to_datetime

    assert _to_datetime(_SDT(date=[2026, 6, 26], time=[None, 5])) is None   # hour None → blank
    assert _to_datetime(_SDT(date=[2026, 6, 26], time=[])) is None          # no time → blank
    assert _to_datetime(_SDT(date=[2026, 6, 26], time=[None])) is None      # hour None → blank
    # Minute None but hour present → minute defaults to 0 (still truthful).
    assert _to_datetime(_SDT(date=[2026, 6, 26], time=[9, None])) == datetime(2026, 6, 26, 9, 0)


def test_on_the_hour_flight_keeps_times(fake_fast_flights):
    """End-to-end: an on-the-hour flight normalises with real departure/arrival
    datetimes rather than None."""
    f = _make_fake_flight()
    f.flights[0].departure = _SDT(date=(2026, 6, 25), time=(17,))   # 5 PM exactly
    f.flights[0].arrival = _SDT(date=(2026, 6, 25), time=(20,))     # 8 PM exactly
    fake_fast_flights.get_flights = lambda _q: [f]
    from scraper import adapter
    [n] = adapter.search_flights(
        origin="BOM", destination="DEL", date_str="2026-06-25",
        max_attempts=1, sleep_fn=lambda _s: None,
    )
    assert n.departure_dt == datetime(2026, 6, 25, 17, 0)
    assert n.arrival_dt == datetime(2026, 6, 25, 20, 0)


def test_parser_patch_resilient_to_bad_flight():
    """The monkeypatched parse_js keeps good flights when one entry is malformed.

    Builds minimal stand-in fast_flights submodules (parser/exceptions/model)
    so _install_parser_patch can install its resilient parse_js, then feeds a
    synthetic payload with one valid flight and one whose price path
    (k[1][0][1]) is missing — the upstream bug that discards the whole page.
    The patched parser must return the 1 good flight, not crash."""
    import json
    import types as _t
    from scraper import adapter

    # ---- minimal model layer (records, just enough fields) ----
    model = _t.ModuleType("fast_flights.model")
    class _Rec:
        def __init__(self, **k): self.__dict__.update(k)
    for name in ("Airline", "Airport", "Alliance", "CarbonEmission",
                 "Flights", "JsMetadata", "SimpleDatetime", "SingleFlight"):
        setattr(model, name, type(name, (_Rec,), {}))
    exc = _t.ModuleType("fast_flights.exceptions")
    class _NF(Exception): ...
    exc.FlightsNotFound = _NF
    parser = _t.ModuleType("fast_flights.parser")
    class ResultList(list): ...
    parser.ResultList = ResultList
    parser.parse_js = lambda js: (_ for _ in ()).throw(AssertionError("orig called"))
    pkg = _t.ModuleType("fast_flights")

    import sys as _sys
    saved = {k: _sys.modules.get(k) for k in
             ("fast_flights", "fast_flights.parser", "fast_flights.exceptions", "fast_flights.model")}
    _sys.modules.update({"fast_flights": pkg, "fast_flights.parser": parser,
                         "fast_flights.exceptions": exc, "fast_flights.model": model})
    adapter._PARSER_PATCHED = False
    try:
        adapter._install_parser_patch()
        assert parser.parse_js.__name__ == "_resilient_parse_js"

        # One good flight (full path) + one bad (k[1] empty → IndexError upstream).
        good_sf = [None, None, None, "BLR", "Bengaluru", "Indore", "IDR", None,
                   [9, 5], None, [11, 0]] + [None] * 9 + [[2026, 6, 26], [2026, 6, 26]]
        good_flight = ["nonstop", ["Air India"], [good_sf] ] + [None] * 19 + [[None]*9]
        good_k = [good_flight, [[None, 7804]]]
        bad_k = [["x", ["Y"], []], []]            # k[1][0][1] → IndexError
        payload = [None, None, None, [[good_k, bad_k]], None, None, None,
                   [None, [[], []]]]
        js = "xx data:" + json.dumps(payload) + ",end"
        out = parser.parse_js(js)
        assert len(out) == 1                      # bad one skipped, good one kept
        assert out[0].price == 7804
    finally:
        adapter._PARSER_PATCHED = False
        for k, v in saved.items():
            if v is None:
                _sys.modules.pop(k, None)
            else:
                _sys.modules[k] = v


def test_parser_patch_idempotent_and_graceful(monkeypatch):
    """Patch install is idempotent and no-ops cleanly if the library is absent."""
    import sys as _sys
    from scraper import adapter
    # Library not importable → graceful no-op, marks done, never raises.
    monkeypatch.setitem(_sys.modules, "fast_flights", None)
    adapter._PARSER_PATCHED = False
    adapter._install_parser_patch()   # must not raise
    assert adapter._PARSER_PATCHED is True
    adapter._install_parser_patch()   # idempotent second call
    adapter._PARSER_PATCHED = False   # reset for other tests


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
