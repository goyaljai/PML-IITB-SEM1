"""
CSV schema for the flight dataset.

Schema version 4 is **additive** over the legacy v3 schema (29 columns) used by
the old multi-source scraper — the first 29 columns are byte-compatible so a
year of v3 data and a year of v4 data concatenate cleanly under a single
``pd.read_csv``. The four v4-only columns are appended at the end:

    30. Carbon_Typical_g   — fast-flights' typical CO₂ per passenger for the route
    31. Currency           — always "INR" (explicit; future-proofs multi-currency)
    32. Cabin_Class        — always "economy" (explicit; future-proofs other classes)
    33. Run_Id             — cron run UTC stamp (e.g. 20260618T030000Z); operational tag

See ``donotdelete/docs/SCHEMA.md`` for full semantics of every field.
"""

from __future__ import annotations

# Bump when CSV_HEADERS or the meaning of a column changes.
SCHEMA_VERSION: int = 4

# Frozen column order. NEVER reorder — append-only changes only (downstream
# parsers may be column-index based). If a column becomes unused, set it to an
# empty string per row rather than dropping it.
CSV_HEADERS: tuple[str, ...] = (
    # 1–29: v3 schema (preserved verbatim)
    "Schema_Version",
    "Scrape_Timestamp",
    "Days_to_Departure",
    "Departure_Date",
    "Day_of_Week",
    "Booking_Day_Of_Week",
    "Departure_Time",
    "Departure_ISO",
    "Departure_Hour",
    "Arrival_Time",
    "Arrival_ISO",
    "Is_Weekend_Departure",
    "Is_Overnight",
    "Source_City",
    "Destination_City",
    "Airline",
    "Flight_Number",
    "Aircraft",
    "Total_Duration_Mins",
    "Number_of_Stops",
    "Layover_City",
    "Layover_Duration_Mins",
    "Self_Transfer",
    "CO2_Emissions_Kg",
    "CO2_Delta_Pct",
    "Num_Results",
    "Data_Source",
    "Flight_Category",
    "Price_INR",
    # 30–33: v4 additions
    "Carbon_Typical_g",
    "Currency",
    "Cabin_Class",
    "Run_Id",
)

# Categorical values for ``Flight_Category`` — anything else is a validation
# error.
FLIGHT_CATEGORIES: frozenset[str] = frozenset({
    "Best",        # first item in fast-flights' sorted result list
    "Cheapest",    # min(price) across the priced result list
    "Median",      # midpoint of the price-sorted priced list (only when ≠ Cheapest)
    "NoFlights",   # marker row when a route returns zero priced flights
})

# Categorical values for ``Data_Source``. v4 only emits ``fast-flights``; the
# legacy values are listed so historical (v3) rows still validate cleanly when
# downstream readers concatenate v3+v4 data.
DATA_SOURCES: frozenset[str] = frozenset({
    "fast-flights",   # v4 (only)
    "fli",            # legacy v3
    "playwright",     # legacy v3 last-resort
})
