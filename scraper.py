"""
Google Flights data collector using the `fli` library (PyPI: `flights`).

Replaces the previous Playwright + headless-Chromium DOM scraper with direct
calls to Google Flights' reverse-engineered internal API. `fli` returns
structured flight objects (price, airline, times, stops, duration, CO2), so
there is no HTML parsing, no browser, and far less fragility.

Scrapes 70 routes/day (3-day rotation of 210 total routes)
at 6 booking horizons (1, 3, 7, 14, 30, 60 days out) = 420 scrapes/day.
Extracts BOTH the "Best" flight and the "Cheapest" flight per route+date.
"""

import csv
import os
import random
import time
import itertools
from datetime import datetime, timedelta

from fli.models import (
    Airport,
    FlightSearchFilters,
    FlightSegment,
    MaxStops,
    PassengerInfo,
    SeatType,
    SortBy,
)
from fli.search import SearchFlights

# ── Config ──────────────────────────────────────────────────────────────────

DATA_DIR = "temp"
FILE_PATH = os.path.join(DATA_DIR, "flights.csv")

CITIES = {
    "Mumbai": "BOM", "Delhi": "DEL", "Bengaluru": "BLR",
    "Hyderabad": "HYD", "Chennai": "MAA", "Kolkata": "CCU",
    "Pune": "PNQ", "Ahmedabad": "AMD", "Surat": "STV",
    "Visakhapatnam": "VTZ", "Jaipur": "JAI", "Kochi": "COK",
    "Chandigarh": "IXC", "Indore": "IDR", "Lucknow": "LKO"
}

DAYS_OUT = [1, 3, 7, 14, 30, 60]

# Price_Level (Google's Low/High/Typical trend) is intentionally dropped:
# fli does not expose it. Prices are stored as the real INR value Google
# returns (no discount factor).
#
# Schema notes for the forecasting use case:
#  - Booking-timing features (Booking_Day_Of_Week, Departure_Hour,
#    Is_Weekend_Departure, Is_Overnight) are DERIVED signals — the strongest
#    drivers of fare are *when you book* and *when you fly*, which aren't raw
#    fields in the API. We surface them as clean columns (the Printing Press
#    "expose the hidden signal" philosophy).
#  - Structured ML fields (Aircraft, Layover_*, Self_Transfer, CO2_Delta_Pct)
#    come straight from fli's decoded result.
#  - Flight_Category is Best / Cheapest / Median (median = midpoint of the
#    full cheapest-sorted result list; free, no extra API call).
CSV_HEADERS = [
    "Scrape_Timestamp", "Days_to_Departure", "Departure_Date",
    "Day_of_Week", "Booking_Day_Of_Week", "Departure_Time", "Departure_Hour",
    "Arrival_Time", "Is_Weekend_Departure", "Is_Overnight",
    "Source_City", "Destination_City", "Airline", "Flight_Number", "Aircraft",
    "Total_Duration_Mins", "Number_of_Stops",
    "Layover_City", "Layover_Duration_Mins", "Self_Transfer",
    "CO2_Emissions_Kg", "CO2_Delta_Pct",
    "Flight_Category", "Price_INR"
]

# Resolve every IATA code in CITIES to its fli Airport enum member once, at
# import time. Fail fast with a clear error if any code is unknown to fli.
def _build_airport_map():
    mapping = {}
    missing = []
    for code in CITIES.values():
        member = getattr(Airport, code, None)
        if member is None:
            missing.append(code)
        else:
            mapping[code] = member
    if missing:
        raise RuntimeError(
            f"These IATA codes are not in fli's Airport enum: {missing}. "
            "Update CITIES or check the installed `flights` version."
        )
    return mapping


CITY_TO_AIRPORT = _build_airport_map()

# Retry settings for transient empty responses from fli.
MAX_ATTEMPTS = 3
BACKOFF_SCHEDULE = [2, 4, 8]  # seconds before attempts 2, 3 (index by attempt-1)

# ── Helpers ─────────────────────────────────────────────────────────────────

def get_todays_routes():
    """
    3-day rotation matrix using a persistent counter.
    210 total routes split into 3 batches of 70.
    """
    state_file = os.path.join(DATA_DIR, "batch_state.txt")

    current_index = 0
    if os.path.exists(state_file):
        with open(state_file, "r") as f:
            try:
                current_index = int(f.read().strip())
            except ValueError:
                current_index = 0

    batch_index = current_index % 3

    codes = list(CITIES.values())
    all_routes = [(s, d) for s, d in itertools.permutations(codes, 2)]
    batch_size = len(all_routes) // 3

    start = batch_index * batch_size
    end = start + batch_size
    if batch_index == 2:
        end = len(all_routes)

    # Increment and save state for tomorrow
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(state_file, "w") as f:
        f.write(str(current_index + 1))

    return all_routes[start:end], batch_index


def random_delay(min_s=2, max_s=5):
    """Polite delay between routes. fli already rate-limits internally
    (10 req/s token bucket), so this can be short."""
    time.sleep(random.uniform(min_s, max_s))


def _fmt_time(dt):
    """Format a datetime as e.g. '7:00 AM'. Returns '' if dt is falsy."""
    if not dt:
        return ""
    # %-I is platform-dependent; strip a leading zero manually for portability.
    return dt.strftime("%I:%M %p").lstrip("0")


# ── Core search ───────────────────────────────────────────────────────────────

def _build_filters(src_code, dest_code, days_out, sort_by):
    """Construct a one-way FlightSearchFilters for the given route/date/sort."""
    target_date = (datetime.now() + timedelta(days=days_out)).strftime("%Y-%m-%d")
    return FlightSearchFilters(
        passenger_info=PassengerInfo(adults=1),
        flight_segments=[
            FlightSegment(
                departure_airport=[[CITY_TO_AIRPORT[src_code], 0]],
                arrival_airport=[[CITY_TO_AIRPORT[dest_code], 0]],
                travel_date=target_date,
            )
        ],
        seat_type=SeatType.ECONOMY,
        stops=MaxStops.ANY,
        sort_by=sort_by,
    )


def _search_with_retry(filters):
    """Run a search, retrying on empty result OR exception (fli returns
    transient empties). Returns the FULL list of FlightResults, or None."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            results = SearchFlights().search(filters)
            if results:
                return results
        except Exception as e:  # noqa: BLE001 - one bad route must not abort the run
            if attempt == MAX_ATTEMPTS:
                print(f"     search error after {MAX_ATTEMPTS} attempts: {e!r}")
        if attempt < MAX_ATTEMPTS:
            time.sleep(BACKOFF_SCHEDULE[attempt - 1])
    return None


def _flight_to_row(flight, src, dest, days_out, category):
    """Map a fli FlightResult to a CSV row dict matching CSV_HEADERS."""
    today = datetime.now()
    target_date = today + timedelta(days=days_out)
    first_leg = flight.legs[0] if flight.legs else None
    last_leg = flight.legs[-1] if flight.legs else None

    airline = flight.primary_airline_name
    if not airline and first_leg is not None:
        airline = first_leg.airline.value

    # Departure hour (numeric) — red-eye vs peak is a strong fare signal.
    dep_dt = first_leg.departure_datetime if first_leg else None
    departure_hour = dep_dt.hour if dep_dt else ""

    # Overnight: arrival calendar date later than departure calendar date,
    # or any leg flagged overnight by fli.
    is_overnight = False
    if first_leg and last_leg and first_leg.departure_datetime and last_leg.arrival_datetime:
        is_overnight = last_leg.arrival_datetime.date() > first_leg.departure_datetime.date()
    is_overnight = is_overnight or any(getattr(leg, "overnight", False) for leg in flight.legs)

    # First layover (if any) — long/overnight layovers correlate with cheaper fares.
    layover_city = ""
    layover_duration = ""
    if flight.layovers:
        lo = flight.layovers[0]
        layover_city = lo.city or (lo.airport.value if lo.airport else "")
        layover_duration = lo.duration

    # Aircraft type from the first leg.
    aircraft = (first_leg.aircraft if first_leg else "") or ""

    return {
        "Scrape_Timestamp": today.strftime("%Y-%m-%d %H:%M:%S"),
        "Days_to_Departure": days_out,
        "Departure_Date": target_date.strftime("%Y-%m-%d"),
        "Day_of_Week": target_date.strftime("%A"),
        "Booking_Day_Of_Week": today.strftime("%A"),
        "Departure_Time": _fmt_time(dep_dt) if first_leg else "",
        "Departure_Hour": departure_hour,
        "Arrival_Time": _fmt_time(last_leg.arrival_datetime) if last_leg else "",
        "Is_Weekend_Departure": int(target_date.weekday() >= 5),
        "Is_Overnight": int(is_overnight),
        "Source_City": src,
        "Destination_City": dest,
        "Airline": airline or "",
        "Flight_Number": (first_leg.flight_number if first_leg else "") or "",
        "Aircraft": aircraft,
        "Total_Duration_Mins": flight.duration,
        "Number_of_Stops": flight.stops,
        "Layover_City": layover_city,
        "Layover_Duration_Mins": layover_duration,
        "Self_Transfer": int(bool(flight.self_transfer)),
        # fli returns CO2 in grams; store as kilograms (rounded).
        "CO2_Emissions_Kg": round(flight.co2_emissions_g / 1000) if flight.co2_emissions_g is not None else 0,
        "CO2_Delta_Pct": flight.co2_emissions_delta_pct if flight.co2_emissions_delta_pct is not None else "",
        "Flight_Category": category,
        "Price_INR": int(flight.price) if flight.price is not None else None,
    }


def _median_by_price(results):
    """Return the median-priced FlightResult from a list (by price)."""
    priced = [r for r in results if r.price is not None]
    if not priced:
        return None
    priced.sort(key=lambda r: r.price)
    return priced[len(priced) // 2]


def scrape_flight(src, dest, days_out):
    """
    Search a route+date on Google Flights via fli.
    Returns [best, cheapest, median] rows (whichever resolve), or None.
    Median is the midpoint of the cheapest-sorted result list — it gives the
    model a sense of the price *distribution*, free (no extra API call).
    """
    best_list = _search_with_retry(_build_filters(src, dest, days_out, SortBy.BEST))
    cheapest_list = _search_with_retry(_build_filters(src, dest, days_out, SortBy.CHEAPEST))

    best = best_list[0] if best_list else None
    cheapest = cheapest_list[0] if cheapest_list else None
    median = _median_by_price(cheapest_list) if cheapest_list else None

    rows = []
    if best is not None:
        rows.append(_flight_to_row(best, src, dest, days_out, "Best"))
    if cheapest is not None:
        rows.append(_flight_to_row(cheapest, src, dest, days_out, "Cheapest"))
    if median is not None:
        rows.append(_flight_to_row(median, src, dest, days_out, "Median"))

    if not rows:
        print(f"  ❌ No results for {src}→{dest} +{days_out}d")
        return None

    bp = best.price if best else None
    cp = cheapest.price if cheapest else None
    mp = median.price if median else None
    print(f"  ✅ {src}→{dest} +{days_out}d: "
          f"Best {int(bp) if bp else '—'} | Cheapest {int(cp) if cp else '—'} | "
          f"Median {int(mp) if mp else '—'}")
    return rows


# ── CSV Writer ──────────────────────────────────────────────────────────────

def ensure_csv():
    """Create data dir and CSV with headers if they don't exist."""
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(FILE_PATH):
        with open(FILE_PATH, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
            writer.writeheader()


def extend_rows(rows):
    """Append multiple rows to the CSV."""
    with open(FILE_PATH, 'a', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        writer.writerows(rows)


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    ensure_csv()
    routes, batch_index = get_todays_routes()

    global DAYS_OUT
    if os.environ.get("TEST_RUN"):
        print("🧪 Running in TEST_RUN mode (1 route, 1 horizon)")
        routes = routes[:1]
        DAYS_OUT = [1]

    total_scrapes = len(routes) * len(DAYS_OUT)

    print("🛫 Flight Scraper Starting (fli / Google Flights API)")
    print(f"   Routes today: {len(routes)} (batch {batch_index + 1}/3)")
    print(f"   Horizons: {DAYS_OUT}")
    print(f"   Total scrapes: {total_scrapes}")
    print()

    success_count = 0
    fail_count = 0

    for i, (src, dest) in enumerate(routes):
        print(f"\n[{i+1}/{len(routes)}] Route: {src} → {dest}")

        for days in DAYS_OUT:
            results = scrape_flight(src, dest, days)
            if results:
                extend_rows(results)
                success_count += 1
            else:
                fail_count += 1

            random_delay()

    print(f"\n{'='*50}")
    print("🏁 Scraping Complete!")
    print(f"   ✅ Success: {success_count}")
    print(f"   ❌ Failed:  {fail_count}")
    success_rate = (success_count / (success_count + fail_count) * 100) if (success_count + fail_count) > 0 else 0.0
    print(f"   📊 Success rate: {success_rate:.1f}%")
    print(f"   📁 Data saved to: {FILE_PATH}")


if __name__ == "__main__":
    main()
