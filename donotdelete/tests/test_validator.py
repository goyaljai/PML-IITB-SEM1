"""Per-row validation rules."""

from __future__ import annotations

import pytest

from scraper.schema import CSV_HEADERS, SCHEMA_VERSION
from scraper.validator import validate_row

MIN_INR = 1000.0
MAX_INR = 200000.0


def _row(**overrides) -> dict:
    base = {h: "" for h in CSV_HEADERS}
    base.update({
        "Schema_Version": SCHEMA_VERSION,
        "Scrape_Timestamp": "2026-06-18 14:00:00",
        "Days_to_Departure": 7,
        "Departure_Date": "2026-06-25",
        "Day_of_Week": "Thursday",
        "Booking_Day_Of_Week": "Thursday",
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


def test_valid_priced_row():
    ok, reason = validate_row(_row(), min_price_inr=MIN_INR, max_price_inr=MAX_INR)
    assert ok, reason


def test_valid_no_flights_row():
    r = _row(Flight_Category="NoFlights", Price_INR="", Num_Results=0)
    ok, reason = validate_row(r, min_price_inr=MIN_INR, max_price_inr=MAX_INR)
    assert ok, reason


@pytest.mark.parametrize("missing", ["Schema_Version", "Source_City", "Price_INR"])
def test_rejects_missing_field(missing):
    r = _row()
    del r[missing]
    ok, reason = validate_row(r, min_price_inr=MIN_INR, max_price_inr=MAX_INR)
    assert not ok and missing in reason


def test_rejects_wrong_schema_version():
    ok, reason = validate_row(_row(Schema_Version=3), min_price_inr=MIN_INR, max_price_inr=MAX_INR)
    assert not ok and "Schema_Version" in reason


@pytest.mark.parametrize("origin, dest", [("bom", "del"), ("BO", "DEL"), ("BOMB", "DEL"), ("", "DEL")])
def test_rejects_non_iata_route(origin, dest):
    ok, _ = validate_row(_row(Source_City=origin, Destination_City=dest),
                         min_price_inr=MIN_INR, max_price_inr=MAX_INR)
    assert not ok


def test_rejects_same_origin_dest():
    ok, reason = validate_row(_row(Source_City="BOM", Destination_City="BOM"),
                              min_price_inr=MIN_INR, max_price_inr=MAX_INR)
    assert not ok and "source == destination" in reason


def test_rejects_bad_departure_date():
    ok, _ = validate_row(_row(Departure_Date="2026/06/25"), min_price_inr=MIN_INR, max_price_inr=MAX_INR)
    assert not ok


def test_rejects_unknown_category():
    ok, _ = validate_row(_row(Flight_Category="OnSale"), min_price_inr=MIN_INR, max_price_inr=MAX_INR)
    assert not ok


def test_rejects_unknown_data_source():
    ok, _ = validate_row(_row(Data_Source="hand-entered"), min_price_inr=MIN_INR, max_price_inr=MAX_INR)
    assert not ok


def test_priced_row_must_have_price():
    ok, reason = validate_row(_row(Price_INR=""), min_price_inr=MIN_INR, max_price_inr=MAX_INR)
    assert not ok and "empty Price_INR" in reason


@pytest.mark.parametrize("price", [69, 999, 200001, 1_000_000])
def test_priced_row_must_be_in_band(price):
    ok, reason = validate_row(_row(Price_INR=price), min_price_inr=MIN_INR, max_price_inr=MAX_INR)
    assert not ok and "Price_INR" in reason


def test_priced_row_band_inclusive():
    ok, _ = validate_row(_row(Price_INR=1000), min_price_inr=MIN_INR, max_price_inr=MAX_INR)
    assert ok
    ok, _ = validate_row(_row(Price_INR=200000), min_price_inr=MIN_INR, max_price_inr=MAX_INR)
    assert ok


def test_no_flights_row_must_have_empty_price():
    r = _row(Flight_Category="NoFlights", Price_INR=5000)
    ok, reason = validate_row(r, min_price_inr=MIN_INR, max_price_inr=MAX_INR)
    assert not ok and "NoFlights" in reason


def test_rejects_negative_days():
    ok, _ = validate_row(_row(Days_to_Departure=-1), min_price_inr=MIN_INR, max_price_inr=MAX_INR)
    assert not ok


def test_rejects_non_int_days():
    ok, _ = validate_row(_row(Days_to_Departure="seven"), min_price_inr=MIN_INR, max_price_inr=MAX_INR)
    assert not ok


def test_legacy_v3_data_source_is_accepted_for_concat():
    # v3 historical rows passing through validate_row (hypothetical replay) should
    # not be rejected on Data_Source alone, even though new rows only emit v4.
    r = _row(Data_Source="fli")
    ok, _ = validate_row(r, min_price_inr=MIN_INR, max_price_inr=MAX_INR)
    assert ok
