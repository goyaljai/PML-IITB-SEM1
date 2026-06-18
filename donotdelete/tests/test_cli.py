"""CLI argument parsing — separate from main() so we don't need a live API."""

from __future__ import annotations

from unittest import mock

import pytest

from scraper.cli import _parse_horizons, _parse_routes, _parse_route_slice


def test_parse_routes_basic():
    assert _parse_routes("BOM:DEL") == [("BOM", "DEL")]
    assert _parse_routes("BOM:DEL,DEL:BOM") == [("BOM", "DEL"), ("DEL", "BOM")]


def test_parse_routes_strips_and_uppercases():
    assert _parse_routes(" bom : del , del : bom ") == [("BOM", "DEL"), ("DEL", "BOM")]


def test_parse_routes_rejects_empty():
    with pytest.raises(Exception):
        _parse_routes("")
    with pytest.raises(Exception):
        _parse_routes(",,")


def test_parse_routes_rejects_no_colon():
    with pytest.raises(Exception):
        _parse_routes("BOM-DEL")


def test_parse_routes_rejects_empty_side():
    with pytest.raises(Exception):
        _parse_routes("BOM:")
    with pytest.raises(Exception):
        _parse_routes(":DEL")


def test_parse_horizons():
    assert _parse_horizons("1,3,7") == [1, 3, 7]
    assert _parse_horizons("60") == [60]


def test_parse_route_slice_valid_and_invalid():
    assert _parse_route_slice("3/8") == (3, 8)
    assert _parse_route_slice("1/1") == (1, 1)
    for bad in ("0/8", "9/8", "3/0", "abc", "3"):
        with pytest.raises(SystemExit):
            _parse_route_slice(bad)


# ── commit_below_gate behaviour ─────────────────────────────────────────────
# These drive main() with a mocked adapter + canary so no live API is needed.

from datetime import datetime  # noqa: E402

from scraper import cli  # noqa: E402
from scraper.adapter import AdapterError, NormalizedFlight  # noqa: E402


def _mixed_flight(price=7876):
    return NormalizedFlight(
        price=price, airline="IndiGo", airlines=("IndiGo",), flight_number="",
        aircraft="A320", departure_dt=datetime(2026, 6, 25, 6, 5),
        arrival_dt=datetime(2026, 6, 25, 8, 25), duration_mins=140, stops=0,
        layover_city="", layover_duration_mins=None, self_transfer=False,
        co2_g=103000, co2_typical_g=100000, co2_delta_pct=3,
    )


def _run_main_with_yaml(tmp_path, commit_below_gate: bool, adapter_side_effect):
    """Write a config that forces a below-gate run, mock canary+adapter, run main()."""
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    # min_success_rate 0.99 => almost any error trips the gate.
    (cfg_dir / "scraper.yaml").write_text(
        "min_success_rate: 0.99\n"
        f"commit_below_gate: {'true' if commit_below_gate else 'false'}\n"
        "delay_min_seconds: 0\ndelay_max_seconds: 0\n"
        "long_pause_every_routes: 0\n"
    )
    (tmp_path / "data").mkdir()
    (tmp_path / "logs").mkdir()
    argv = ["--base-dir", str(tmp_path), "--no-canary",
            "--routes", "BOM:DEL,DEL:BOM", "--horizons", "1", "--no-advance"]
    with mock.patch("scraper.adapter.search_flights", side_effect=adapter_side_effect):
        return cli.main(argv)


def test_below_gate_commits_when_flag_true(tmp_path):
    """One route prices, one errors → fare_rate 50% < 99% gate, but rows>0.
    With commit_below_gate=True the run returns OK (0), not EXIT_GATE (3)."""
    calls = {"n": 0}
    def side_effect(**kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return [_mixed_flight()]
        raise AdapterError("simulated upstream error")
    rc = _run_main_with_yaml(tmp_path, commit_below_gate=True, adapter_side_effect=side_effect)
    assert rc == cli.EXIT_OK
    # Rows were written despite the degraded fare-rate.
    csvs = list((tmp_path / "data").glob("flights_*.csv"))
    assert csvs and sum(1 for _ in csvs[0].open()) > 1  # header + ≥1 row


def test_below_gate_blocks_when_flag_false(tmp_path):
    """Same scenario, commit_below_gate=False → strict legacy EXIT_GATE."""
    calls = {"n": 0}
    def side_effect(**kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return [_mixed_flight()]
        raise AdapterError("simulated upstream error")
    rc = _run_main_with_yaml(tmp_path, commit_below_gate=False, adapter_side_effect=side_effect)
    assert rc == cli.EXIT_GATE


def test_zero_rows_still_exits_gate_even_when_flag_true(tmp_path):
    """If EVERY search errors (0 rows), even commit_below_gate=True returns EXIT_GATE."""
    def side_effect(**kw):
        raise AdapterError("everything is broken")
    rc = _run_main_with_yaml(tmp_path, commit_below_gate=True, adapter_side_effect=side_effect)
    assert rc == cli.EXIT_GATE
