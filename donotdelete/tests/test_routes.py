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


def test_batch_slice_partitions_exactly():
    """The union of all slices equals the input, in order, with no overlap."""
    batch = routes.all_routes(CITIES_15)  # 210 routes
    n = 8
    reassembled = []
    for i in range(1, n + 1):
        reassembled.extend(routes.batch_slice(batch, i, n))
    assert reassembled == batch  # exact partition, order preserved


def test_batch_slice_last_absorbs_remainder():
    batch = [("A", "B")] * 70  # 70 not divisible by 8
    n = 8
    sizes = [len(routes.batch_slice(batch, i, n)) for i in range(1, n + 1)]
    assert sum(sizes) == 70
    # First 7 slices equal-size (70//8 = 8), last absorbs remainder (70-56=14).
    assert sizes[:-1] == [8] * 7
    assert sizes[-1] == 14


def test_batch_slice_single_slice_is_whole_batch():
    batch = routes.all_routes(CITIES_15)
    assert routes.batch_slice(batch, 1, 1) == batch


def test_batch_slice_rejects_bad_index():
    batch = routes.all_routes(CITIES_15)
    with pytest.raises(ValueError):
        routes.batch_slice(batch, 0, 8)      # below range
    with pytest.raises(ValueError):
        routes.batch_slice(batch, 9, 8)      # above range
    with pytest.raises(ValueError):
        routes.batch_slice(batch, 1, 0)      # bad count


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


import datetime as _dt


def test_batch_index_is_pure_date_function():
    """batch_index = (date - epoch) days % n_batches — deterministic, stateless."""
    # Epoch itself → index 0.
    assert routes.batch_index_for_date(routes.ROTATION_EPOCH, 3) == 0
    # Consecutive days step 0,1,2,0,1,2…
    seq = [routes.batch_index_for_date(routes.ROTATION_EPOCH + _dt.timedelta(days=i), 3)
           for i in range(7)]
    assert seq == [0, 1, 2, 0, 1, 2, 0]
    assert routes.batch_index_for_date(routes.ROTATION_EPOCH, 0 + 1) == 0  # n=1 always 0


def test_batch_index_rejects_bad_n():
    with pytest.raises(ValueError):
        routes.batch_index_for_date(routes.ROTATION_EPOCH, 0)


def test_current_batch_is_date_based(tmp_path):
    """current_batch derives the batch from the injected date — no state file."""
    day0 = routes.ROTATION_EPOCH               # index 0
    day1 = routes.ROTATION_EPOCH + _dt.timedelta(days=1)  # index 1
    b0 = routes.current_batch(CITIES_15, 3, tmp_path, today=day0)
    b1 = routes.current_batch(CITIES_15, 3, tmp_path, today=day1)
    assert b0.index == 0
    assert b1.index == 1
    assert len(b0.routes) == 70
    # No state file is created — rotation is stateless.
    assert not (tmp_path / routes.BATCH_STATE_FILENAME).exists()


def test_current_batch_defaults_to_utc_today(tmp_path):
    """With no injected date it uses UTC 'today' and returns a valid batch."""
    b = routes.current_batch(CITIES_15, 3, tmp_path)
    assert 0 <= b.index < 3
    assert len(b.routes) == 70


def test_past_failure_cannot_change_future_batch(tmp_path):
    """The core guarantee: a given date ALWAYS maps to the same batch,
    regardless of any prior run, state file, or 'failure'. The past cannot
    break the future."""
    day = routes.ROTATION_EPOCH + _dt.timedelta(days=100)
    expected = routes.current_batch(CITIES_15, 3, tmp_path, today=day).index
    # Simulate arbitrary prior 'history' / leftover legacy state — must not matter.
    (tmp_path / routes.BATCH_STATE_FILENAME).write_text("999", encoding="utf-8")
    again = routes.current_batch(CITIES_15, 3, tmp_path, today=day).index
    assert again == expected


def test_three_consecutive_days_cover_universe(tmp_path):
    """Any 3 consecutive days collect all 210 routes exactly once — guaranteed
    no matter what happened before."""
    start = routes.ROTATION_EPOCH + _dt.timedelta(days=500)
    seen = []
    for i in range(3):
        b = routes.current_batch(CITIES_15, 3, tmp_path, today=start + _dt.timedelta(days=i))
        seen.extend(b.routes)
    assert sorted(seen) == sorted(routes.all_routes(CITIES_15))
    assert len(seen) == len(set(seen))  # no dupes


def test_advance_batch_is_noop_shim(tmp_path):
    """advance_batch no longer drives rotation; it's an inert shim returning -1
    and writing no state."""
    assert routes.advance_batch(tmp_path) == -1
    assert not (tmp_path / routes.BATCH_STATE_FILENAME).exists()
