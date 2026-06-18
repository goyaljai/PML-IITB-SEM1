"""Route enumeration and 3-day rotation."""

from __future__ import annotations

from pathlib import Path

import pytest

from scraper import routes


CITIES_15 = {
    "Mumbai": "BOM", "Delhi": "DEL", "Bengaluru": "BLR", "Hyderabad": "HYD",
    "Chennai": "MAA", "Kolkata": "CCU", "Pune": "PNQ", "Ahmedabad": "AMD",
    "Surat": "STV", "Visakhapatnam": "VTZ", "Jaipur": "JAI", "Kochi": "COK",
    "Chandigarh": "IXC", "Indore": "IDR", "Lucknow": "LKO",
}


def test_all_routes_is_15x14():
    r = routes.all_routes(CITIES_15)
    assert len(r) == 15 * 14
    # No self-pairs.
    assert all(s != d for s, d in r)
    # Stable across calls (sorted-by-code → permutations is deterministic).
    assert r == routes.all_routes(CITIES_15)


def test_all_routes_drops_duplicate_iata():
    """If the dict has two names mapping to the same IATA, route count is based on distinct codes."""
    dup = {"Mumbai": "BOM", "Bombay": "BOM", "Delhi": "DEL"}
    r = routes.all_routes(dup)
    assert len(r) == 2 * 1  # only BOM↔DEL


def test_batch_for_index_covers_universe():
    r = routes.all_routes(CITIES_15)
    seen = []
    for i in range(3):
        seen.extend(routes.batch_for_index(r, i, 3))
    assert sorted(seen) == sorted(r)
    # No duplicates across batches.
    assert len(seen) == len(set(seen))


def test_batch_for_index_last_absorbs_remainder():
    r = list(range(10))  # type: ignore[assignment]
    # 10 items, 3 batches → 3, 3, 4
    assert len(routes.batch_for_index(r, 0, 3)) == 3
    assert len(routes.batch_for_index(r, 1, 3)) == 3
    assert len(routes.batch_for_index(r, 2, 3)) == 4


def test_batch_for_index_validates():
    r = routes.all_routes(CITIES_15)
    with pytest.raises(ValueError):
        routes.batch_for_index(r, -1, 3)
    with pytest.raises(ValueError):
        routes.batch_for_index(r, 3, 3)
    with pytest.raises(ValueError):
        routes.batch_for_index(r, 0, 0)


def test_current_batch_starts_at_zero_when_no_state(tmp_path):
    b = routes.current_batch(CITIES_15, 3, tmp_path)
    assert b.index == 0
    assert b.cycle_count == 0
    assert len(b.routes) == 70


def test_current_batch_reads_counter(tmp_path):
    (tmp_path / routes.BATCH_STATE_FILENAME).write_text("7", encoding="utf-8")
    b = routes.current_batch(CITIES_15, 3, tmp_path)
    assert b.index == 1                # 7 % 3 == 1
    assert b.cycle_count == 7 // 3      # 2 complete cycles done


def test_current_batch_does_not_write(tmp_path):
    """current_batch is a PURE READ — fixes the v3 bug."""
    state = tmp_path / routes.BATCH_STATE_FILENAME
    state.write_text("5", encoding="utf-8")
    before = state.read_text(encoding="utf-8")
    routes.current_batch(CITIES_15, 3, tmp_path)
    assert state.read_text(encoding="utf-8") == before


def test_current_batch_handles_corrupt_state(tmp_path):
    (tmp_path / routes.BATCH_STATE_FILENAME).write_text("notanumber\n", encoding="utf-8")
    b = routes.current_batch(CITIES_15, 3, tmp_path)
    assert b.index == 0  # corrupt state → treat as 0


def test_advance_batch_increments(tmp_path):
    assert routes.advance_batch(tmp_path) == 1
    assert routes.advance_batch(tmp_path) == 2
    assert (tmp_path / routes.BATCH_STATE_FILENAME).read_text(encoding="utf-8").strip() == "2"


def test_advance_then_current_round_trip(tmp_path):
    routes.advance_batch(tmp_path)
    routes.advance_batch(tmp_path)
    routes.advance_batch(tmp_path)
    b = routes.current_batch(CITIES_15, 3, tmp_path)
    assert b.index == 0
    assert b.cycle_count == 1
