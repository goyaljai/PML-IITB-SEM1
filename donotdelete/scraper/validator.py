"""
Per-row validation.

Every row produced by the pipeline passes through ``validate_row`` before it
reaches the CSV writer. Invalid rows are dropped and logged — *never* written.
The dataset is append-only, so a single bad row stays in the file forever once
written; it is cheaper to be strict here than to clean up later.

Rules (all keyed on a row dict whose keys match ``schema.CSV_HEADERS``):
  1. Every header in CSV_HEADERS is present (no missing keys, even if empty).
  2. ``Schema_Version`` matches the current version.
  3. ``Source_City`` and ``Destination_City`` are non-empty IATA-shaped (3 ALPHA).
  4. ``Source_City != Destination_City``.
  5. ``Days_to_Departure`` is a non-negative int.
  6. ``Departure_Date`` parses as YYYY-MM-DD.
  7. ``Flight_Category`` is one of the known categorical values.
  8. ``Data_Source`` is one of the known categorical values.
  9. For priced categories (Best/Cheapest/Median): ``Price_INR`` is an integer
     inside the plausibility band [min, max].
 10. For NoFlights: ``Price_INR`` MUST be empty (we encode "no fare" as missing).

Returns ``(ok: bool, reason: str)``. ``reason`` is "" when ``ok=True``.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Mapping

from .schema import CSV_HEADERS, DATA_SOURCES, FLIGHT_CATEGORIES, SCHEMA_VERSION

IATA_RE = re.compile(r"^[A-Z]{3}$")

PRICED_CATEGORIES = frozenset({"Best", "Cheapest", "Median"})


def validate_row(
    row: Mapping[str, Any],
    *,
    min_price_inr: float,
    max_price_inr: float,
) -> tuple[bool, str]:
    """Return (True, "") if the row is writeable; otherwise (False, reason)."""

    # Rule 1 — every header must be present (DictWriter would still work, but
    # missing keys often indicate a code-path bug we want to surface fast).
    missing = [h for h in CSV_HEADERS if h not in row]
    if missing:
        return False, f"missing fields: {missing}"

    # Rule 2 — schema version.
    if str(row["Schema_Version"]) != str(SCHEMA_VERSION):
        return False, f"Schema_Version != {SCHEMA_VERSION}: got {row['Schema_Version']!r}"

    # Rule 3/4 — IATA-shaped origin/destination, different.
    # Strict: codes must already be uppercase. The pipeline always writes
    # uppercase (from the cities config) — lowercase is a code-path bug.
    src = str(row["Source_City"] or "")
    dst = str(row["Destination_City"] or "")
    if not IATA_RE.match(src) or not IATA_RE.match(dst):
        return False, f"non-IATA route: {src!r} → {dst!r}"
    if src == dst:
        return False, f"source == destination: {src}"

    # Rule 5 — non-negative integer horizon.
    try:
        days = int(row["Days_to_Departure"])
    except (ValueError, TypeError):
        return False, f"Days_to_Departure not int: {row['Days_to_Departure']!r}"
    if days < 0:
        return False, f"Days_to_Departure < 0: {days}"

    # Rule 6 — departure date parses.
    try:
        datetime.strptime(str(row["Departure_Date"]), "%Y-%m-%d")
    except ValueError:
        return False, f"Departure_Date not YYYY-MM-DD: {row['Departure_Date']!r}"

    # Rule 7 — known flight category.
    cat = str(row["Flight_Category"] or "")
    if cat not in FLIGHT_CATEGORIES:
        return False, f"unknown Flight_Category: {cat!r}"

    # Rule 8 — known data source.
    src_lib = str(row["Data_Source"] or "")
    if src_lib not in DATA_SOURCES:
        return False, f"unknown Data_Source: {src_lib!r}"

    # Rules 9/10 — price semantics depend on category.
    price = row["Price_INR"]
    price_str = "" if price is None else str(price).strip()
    if cat in PRICED_CATEGORIES:
        if price_str == "":
            return False, f"{cat} row has empty Price_INR"
        try:
            p = float(price_str)
        except ValueError:
            return False, f"Price_INR not numeric: {price_str!r}"
        if not (min_price_inr <= p <= max_price_inr):
            return False, (
                f"Price_INR {p:.0f} outside plausibility band "
                f"[{min_price_inr:.0f}, {max_price_inr:.0f}] — likely parsing artefact"
            )
    elif cat == "NoFlights":
        if price_str != "":
            return False, f"NoFlights row should have empty Price_INR, got {price_str!r}"

    return True, ""
