# Flight dataset — schema v4

`data/flights_YYYY_MM.csv` is monthly-partitioned, append-only, and tracked
via Git LFS. Every row is one (search, derived-category) tuple: a single
fast-flights search emits up to **three rows** (`Best`, `Cheapest`, `Median`)
or one `NoFlights` marker when the route returns zero priced flights for the
queried date.

**v4 is additive over v3.** The first 29 columns are byte-identical (same
order, same names, same semantics) so old data and new data concatenate
cleanly under one `pandas.read_csv` call. Columns 30–33 are new in v4.

Bump the schema version (`schema.SCHEMA_VERSION` in code) whenever:
  * a column is added, removed, or renamed, OR
  * a column's value semantics change.

## Columns

| # | Column | Type | v3 / v4 | Description |
|---|---|---|---|---|
| 1 | `Schema_Version` | int | v3+ | Schema vintage of the row. `3` for legacy, `4` for the current scraper. Use `Schema_Version >= 3` to keep all production data. |
| 2 | `Scrape_Timestamp` | datetime (local) | v3+ | When the search was issued. **Local time**, no offset stored — the VPS should run on a stable timezone (IST recommended; documented in `OPERATIONS.md`). Compare with `Run_Id` (UTC) when in doubt. |
| 3 | `Days_to_Departure` | int | v3+ | Booking horizon: `Departure_Date - Scrape_Timestamp.date()`. Always one of {1, 3, 7, 14, 30, 60}. |
| 4 | `Departure_Date` | date `YYYY-MM-DD` | v3+ | Travel date queried. |
| 5 | `Day_of_Week` | str | v3+ | Departure day-of-week (`Monday`…`Sunday`). Pre-derived. |
| 6 | `Booking_Day_Of_Week` | str | v3+ | DOW of `Scrape_Timestamp`. Captures weekday-vs-weekend booking effects. |
| 7 | `Departure_Time` | str | v3+ | Local clock time, e.g. `6:05 AM`. Empty for `NoFlights`. |
| 8 | `Departure_ISO` | datetime ISO 8601 | v3+ | `2026-06-25T06:05:00` — unambiguous parse target. |
| 9 | `Departure_Hour` | int | v3+ | 0–23 in local time. Red-eye vs peak signal. |
| 10 | `Arrival_Time` | str | v3+ | Local clock time. |
| 11 | `Arrival_ISO` | datetime ISO 8601 | v3+ | |
| 12 | `Is_Weekend_Departure` | 0/1 | v3+ | 1 iff Saturday or Sunday. |
| 13 | `Is_Overnight` | 0/1 | v3+ | 1 iff arrival calendar date > departure calendar date. |
| 14 | `Source_City` | str (IATA) | v3+ | Origin code, e.g. `BOM`. |
| 15 | `Destination_City` | str (IATA) | v3+ | Destination code. |
| 16 | `Airline` | str | v3+ | Primary marketing airline. Empty for `NoFlights`. |
| 17 | `Flight_Number` | str | v3+ | First-leg flight number from `fli` (v3). **fast-flights does not expose this — always empty in v4**, documented as known-null-from-source. |
| 18 | `Aircraft` | str | v3+ | First-leg plane type, e.g. `Airbus A320neo`. May be empty if the source didn't decode it. |
| 19 | `Total_Duration_Mins` | int | v3+ | Itinerary duration in minutes (sum over legs). |
| 20 | `Number_of_Stops` | int | v3+ | 0 = nonstop, n = n stops. |
| 21 | `Layover_City` | str (IATA) | v3+ | First layover airport code (empty if nonstop). |
| 22 | `Layover_Duration_Mins` | int | v3+ | First layover length, minutes. Empty if nonstop. |
| 23 | `Self_Transfer` | 0/1 | v3+ | Itinerary requires a self-transfer. `fli` exposed this; **fast-flights does not — always 0 in v4** (known-null-from-source). |
| 24 | `CO2_Emissions_Kg` | int | v3+ | Per-passenger CO₂ in **kilograms** (source emits grams; pipeline divides). Empty if source did not provide it. |
| 25 | `CO2_Delta_Pct` | int | v3+ | Signed % above/below `Carbon_Typical_g` for the route. Empty if either component is missing. |
| 26 | `Num_Results` | int | v3+ | How many priced flights the underlying search returned. Proxy for route demand/supply thickness. `0` for `NoFlights`. |
| 27 | `Data_Source` | str | v3+ | Which adapter produced the row. Values: `fast-flights` (v4), `fli` / `playwright` (legacy v3). v4 always emits `fast-flights` (also for `NoFlights` — fixing a v3 bug where `NoFlights` rows had empty `Data_Source`). |
| 28 | `Flight_Category` | str | v3+ | One of: `Best`, `Cheapest`, `Median`, `NoFlights`. |
| 29 | `Price_INR` | int | v3+ | Fare in INR (no discount factor). Empty for `NoFlights`. **Pre-validated** to be within `[1_000, 200_000]` — anything outside is dropped as a parsing artefact. |
| 30 | `Carbon_Typical_g` | int | **v4** | "Typical" CO₂ per passenger on the route, **grams**. Source-truth value used to derive `CO2_Delta_Pct`; exposed in v4 so downstream isn't limited to the derived percentage. |
| 31 | `Currency` | str | **v4** | Always `INR` in v4. Explicit for multi-currency future-proofing. |
| 32 | `Cabin_Class` | str | **v4** | Always `economy` in v4. Explicit for multi-cabin future-proofing. |
| 33 | `Run_Id` | str | **v4** | UTC stamp `YYYYMMDDTHHMMSSZ` shared by every row produced by a single cron invocation. Used to correlate CSV rows ↔ log lines ↔ lock-file breadcrumb. |

## Row patterns

| Category | Emitted when | Price | Layover fields | Aircraft / DOW / hour |
|---|---|---|---|---|
| `Best` | Result list non-empty | first result's price | first result's | first result's |
| `Cheapest` | Result list has ≥ 1 priced flight | min(price) | min-priced flight's | min-priced flight's |
| `Median` | Cheapest's price differs from median's | midpoint of sorted prices | median flight's | median flight's |
| `NoFlights` | Result list is empty after retries | **empty** | empty | empty |

`Median` is the price at index `len(priced_results) // 2` after sorting by
price ascending. It's intentionally a row from the actual result list (not a
synthetic price interpolation), so all the structured fields (airline,
duration, aircraft, etc.) are real.

## Constants for downstream

```python
# Programmatic source-of-truth — keep these in sync with code via `from scraper.schema import …`
SCHEMA_VERSION   = 4
CSV_HEADERS      = (...)  # 33 columns, see scraper/schema.py
FLIGHT_CATEGORIES = {"Best", "Cheapest", "Median", "NoFlights"}
DATA_SOURCES     = {"fast-flights", "fli", "playwright"}
```

## Reading the dataset

```python
import pandas as pd
import glob
import os

files = sorted(glob.glob("donotdelete/data/flights_*.csv"))
df = pd.concat((pd.read_csv(f) for f in files), ignore_index=True)
# Drop legacy contamination (the v3 fli ₹69 glitch) for forecasting:
df = df[(df.Schema_Version >= 4) | (df.Price_INR.fillna(0).between(1_000, 200_000))]
```
