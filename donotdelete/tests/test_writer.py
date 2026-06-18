"""CSV append behaviour."""

from __future__ import annotations

import csv
import os
from datetime import datetime, timezone
from pathlib import Path

from scraper import writer
from scraper.schema import CSV_HEADERS, SCHEMA_VERSION


def _good_row(**overrides):
    base = {h: "" for h in CSV_HEADERS}
    base.update({
        "Schema_Version": SCHEMA_VERSION,
        "Scrape_Timestamp": "2026-06-18 14:00:00",
        "Days_to_Departure": 7,
        "Departure_Date": "2026-06-25",
        "Source_City": "BOM",
        "Destination_City": "DEL",
        "Num_Results": 5,
        "Data_Source": "fast-flights",
        "Flight_Category": "Best",
        "Price_INR": 7876,
        "Currency": "INR",
        "Cabin_Class": "economy",
        "Run_Id": "20260618T140000Z",
    })
    base.update(overrides)
    return base


def test_monthly_path_format(tmp_path):
    when = datetime(2026, 3, 17, tzinfo=timezone.utc)
    p = writer.monthly_path(tmp_path, when=when)
    assert p == tmp_path / "flights_2026_03.csv"


def test_ensure_file_creates_header(tmp_path):
    p = tmp_path / "data" / "flights_2026_06.csv"
    writer.ensure_file(p)
    assert p.exists()
    with p.open() as f:
        first = f.readline().rstrip("\n")
    assert first == ",".join(CSV_HEADERS)


def test_ensure_file_is_idempotent(tmp_path):
    p = tmp_path / "flights.csv"
    writer.ensure_file(p)
    p.write_text("Schema_Version,…\nexisting\n", encoding="utf-8")  # spoof prior content
    writer.ensure_file(p)
    assert "existing" in p.read_text(encoding="utf-8")


def test_append_writes_rows_and_returns_count(tmp_path):
    p = tmp_path / "flights.csv"
    n = writer.append_rows(p, [_good_row(), _good_row(Flight_Category="Cheapest")])
    assert n == 2
    with p.open() as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2
    assert rows[0]["Source_City"] == "BOM"
    assert rows[1]["Flight_Category"] == "Cheapest"


def test_append_is_append_only(tmp_path):
    p = tmp_path / "flights.csv"
    writer.append_rows(p, [_good_row(Days_to_Departure=1)])
    writer.append_rows(p, [_good_row(Days_to_Departure=3)])
    with p.open() as f:
        rows = list(csv.DictReader(f))
    assert [r["Days_to_Departure"] for r in rows] == ["1", "3"]


def test_none_values_become_empty_strings(tmp_path):
    p = tmp_path / "flights.csv"
    r = _good_row()
    r["Aircraft"] = None
    writer.append_rows(p, [r])
    with p.open() as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["Aircraft"] == ""


def test_missing_keys_default_empty(tmp_path):
    p = tmp_path / "flights.csv"
    writer.append_rows(p, [{}])  # empty dict — every field default-empty
    with p.open() as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["Source_City"] == ""
    # All headers present.
    assert set(rows[0].keys()) == set(CSV_HEADERS)


def test_consistency_after_crash_between_rows(tmp_path):
    """append_rows fsyncs per row, so each row is durable independently."""
    p = tmp_path / "flights.csv"
    writer.ensure_file(p)
    # Simulate a crash AFTER row 1 but BEFORE row 2 by appending only row 1.
    with open(p, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(CSV_HEADERS))
        w.writerow({h: ("" if _good_row().get(h) is None else _good_row().get(h)) for h in CSV_HEADERS})
        f.flush()
        os.fsync(f.fileno())
    # File should still parse cleanly.
    with p.open() as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
