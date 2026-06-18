"""End-to-end pipeline behaviour with a mocked adapter."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from unittest import mock

import pytest

from scraper import pipeline
from scraper.adapter import AdapterError, FlightsNotFound, NormalizedFlight
from scraper.schema import CSV_HEADERS, SCHEMA_VERSION


def _flight(price: int, airline: str = "IndiGo") -> NormalizedFlight:
    return NormalizedFlight(
        price=price, airline=airline, airlines=(airline,),
        flight_number="", aircraft="Airbus A320neo",
        departure_dt=datetime(2026, 6, 25, 6, 5),
        arrival_dt=datetime(2026, 6, 25, 8, 25),
        duration_mins=140, stops=0,
        layover_city="", layover_duration_mins=None,
        self_transfer=False, co2_g=103000, co2_typical_g=100000, co2_delta_pct=3,
    )


def test_run_writes_best_cheapest_median_and_advances_nothing_in_override(fake_config):
    flights = [_flight(7876), _flight(9000, "Air India"), _flight(11000, "SpiceJet")]
    with mock.patch("scraper.adapter.search_flights", return_value=flights):
        summary, out_path = pipeline.run(
            fake_config,
            run_id="20260618T140000Z",
            routes_override=[("BOM", "DEL")],
            days_out_override=[1],
            sleep_fn=lambda _s: None,
        )
    assert summary.attempted == 1
    assert summary.with_fares == 1
    assert summary.errored == 0
    with out_path.open() as f:
        rows = list(csv.DictReader(f))
    cats = [r["Flight_Category"] for r in rows]
    assert cats == ["Best", "Cheapest", "Median"]
    assert int(rows[0]["Price_INR"]) == 7876
    assert int(rows[1]["Price_INR"]) == 7876
    assert int(rows[2]["Price_INR"]) == 9000          # median = sorted[1]
    # v4-specific columns are populated.
    for r in rows:
        assert r["Currency"] == "INR"
        assert r["Cabin_Class"] == "economy"
        assert r["Run_Id"] == "20260618T140000Z"
        assert r["Schema_Version"] == str(SCHEMA_VERSION)


def test_run_skips_median_when_equal_to_cheapest(fake_config):
    """Two flights at the same minimum price → no Median row (it would duplicate Cheapest)."""
    flights = [_flight(7876), _flight(7876, "Air India")]
    with mock.patch("scraper.adapter.search_flights", return_value=flights):
        _, out_path = pipeline.run(
            fake_config,
            run_id="run-eq",
            routes_override=[("BOM", "DEL")],
            days_out_override=[1],
            sleep_fn=lambda _s: None,
        )
    with out_path.open() as f:
        cats = [r["Flight_Category"] for r in csv.DictReader(f)]
    assert "Median" not in cats


def test_run_writes_no_flights_row_for_empty(fake_config):
    with mock.patch("scraper.adapter.search_flights", side_effect=FlightsNotFound("none")):
        summary, out_path = pipeline.run(
            fake_config,
            run_id="run-nf",
            routes_override=[("BOM", "DEL")],
            days_out_override=[1],
            sleep_fn=lambda _s: None,
        )
    assert summary.attempted == 1
    assert summary.no_flights == 1
    assert summary.with_fares == 0
    with out_path.open() as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["Flight_Category"] == "NoFlights"
    assert rows[0]["Price_INR"] == ""
    assert rows[0]["Data_Source"] == "fast-flights"  # v4 fixes the v3 empty-source bug


def test_run_counts_errors_separately(fake_config):
    with mock.patch("scraper.adapter.search_flights", side_effect=AdapterError("boom")):
        summary, _ = pipeline.run(
            fake_config,
            run_id="run-err",
            routes_override=[("BOM", "DEL")],
            days_out_override=[1, 3],
            sleep_fn=lambda _s: None,
        )
    assert summary.attempted == 2
    assert summary.errored == 2
    assert summary.with_fares == 0


def test_implausible_price_is_dropped_at_validation(fake_config):
    """Defence-in-depth: even if the adapter returns a bogus price, the
    validator catches it before it hits the CSV."""
    flights = [_flight(69)]  # the legacy fli glitch value
    with mock.patch("scraper.adapter.search_flights", return_value=flights):
        summary, out_path = pipeline.run(
            fake_config,
            run_id="run-bog",
            routes_override=[("BOM", "DEL")],
            days_out_override=[1],
            sleep_fn=lambda _s: None,
        )
    # The search counted as with_fares (it returned a row), but every row was dropped.
    assert summary.rows_dropped >= 1
    assert summary.rows_written == 0
    # CSV exists with just the header row.
    with out_path.open() as f:
        rows = list(csv.DictReader(f))
    assert rows == []


def test_passes_quality_gate_logic():
    s = pipeline.RunSummary(attempted=10, with_fares=7)
    assert pipeline.passes_quality_gate(s, 0.6) is True
    assert pipeline.passes_quality_gate(s, 0.8) is False
    # No attempts → gate fails (we never want to commit a zero-work run as "OK").
    assert pipeline.passes_quality_gate(pipeline.RunSummary(), 0.0) is False


def test_budget_hit_stops_the_loop(fake_config, monkeypatch):
    """When the wall-clock budget is exceeded, the pipeline stops gracefully."""
    fake_config.target_runtime_seconds = 1
    # Force "time has run out" on the second route.
    times = iter([0.0, 0.0, 5.0, 5.0, 5.0, 5.0])
    with mock.patch("scraper.adapter.search_flights", return_value=[_flight(7876)]):
        summary, _ = pipeline.run(
            fake_config,
            run_id="run-budget",
            routes_override=[("BOM", "DEL"), ("DEL", "BOM"), ("BLR", "DEL")],
            days_out_override=[1],
            sleep_fn=lambda _s: None,
            monotonic_fn=lambda: next(times),
        )
    assert summary.budget_hit is True
    # At most the first route's calls before the budget kicked in.
    assert summary.attempted <= 2
