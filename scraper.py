"""
Google Flights data collector using the `fli` library (PyPI: `flights`).

Replaces the previous Playwright + headless-Chromium DOM scraper with direct
calls to Google Flights' reverse-engineered internal API. `fli` returns
structured flight objects (price, airline, times, stops, duration, CO2), so
there is no HTML parsing, no browser, and far less fragility.

Scrapes 70 routes/day (3-day rotation of 210 total routes)
at 6 booking horizons (1, 3, 7, 14, 30, 60 days out) = 420 scrapes/day.
Emits Best / Cheapest / Median rows per route+date (Median only when it
differs from Cheapest), or a NoFlights row when a route has no fares.

Robustness for long unattended runs:
  - Canary check at startup (fail loudly if fli is broken).
  - Success-rate gate (non-zero exit if too many scrapes error).
  - Monthly-partitioned output (temp/flights_YYYY_MM.csv).
  - Schema_Version column for vintage tracking.
"""

import csv
import os
import sys
import random
import time
import itertools
from datetime import datetime, timedelta

from sources import build_sources

# ── Config ──────────────────────────────────────────────────────────────────

DATA_DIR = "temp"

# Schema version — bump when CSV_HEADERS changes so downstream can tell
# row vintages apart over a long-running collection.
SCHEMA_VERSION = "3"

# Monthly partitioning: write temp/flights_YYYY_MM.csv instead of one
# ever-growing file, to keep each file small and git diffs clean over a year.
def current_file_path():
    return os.path.join(DATA_DIR, f"flights_{datetime.now():%Y_%m}.csv")

# Canary: a known-good route we expect to always return results. Used to decide
# whether the pipeline is healthy before committing to a full run.
#
# IMPORTANT — datacenter-IP warm-up: from a fresh datacenter IP (e.g. GitHub
# Actions), Google Flights soft-throttles the first few minutes of requests
# (empty responses) before "warming up" and serving normally. Observed ~3.5 min
# of empties then success. So the canary is PATIENT: it keeps retrying for up to
# CANARY_MAX_WAIT_S before concluding the pipeline is truly broken. Only a
# sustained failure across the whole window (the library-rot / hard-block case)
# aborts the run.
CANARY_ROUTE = ("BOM", "DEL")
CANARY_DAYS_OUT = 7
CANARY_MAX_WAIT_S = float(os.environ.get("CANARY_MAX_WAIT_S", "420"))   # ~7 min
CANARY_PROBE_INTERVAL_S = float(os.environ.get("CANARY_PROBE_INTERVAL_S", "30"))

# Fail the job if the success rate drops below this (catches partial outages,
# IP blocks, or library rot that the canary didn't catch). 0.0–1.0.
MIN_SUCCESS_RATE = float(os.environ.get("MIN_SUCCESS_RATE", "0.70"))

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
    "Schema_Version", "Scrape_Timestamp", "Days_to_Departure", "Departure_Date",
    "Day_of_Week", "Booking_Day_Of_Week",
    "Departure_Time", "Departure_ISO", "Departure_Hour",
    "Arrival_Time", "Arrival_ISO", "Is_Weekend_Departure", "Is_Overnight",
    "Source_City", "Destination_City", "Airline", "Flight_Number", "Aircraft",
    "Total_Duration_Mins", "Number_of_Stops",
    "Layover_City", "Layover_Duration_Mins", "Self_Transfer",
    "CO2_Emissions_Kg", "CO2_Delta_Pct",
    "Num_Results", "Data_Source", "Flight_Category", "Price_INR"
]

# Retry settings for transient empty responses.
MAX_ATTEMPTS = 3
BACKOFF_SCHEDULE = [2, 4, 8]  # seconds before attempts 2, 3 (index by attempt-1)

# Sources are built once (in fallback order) and reused across the run.
# Override order/subset with FLIGHT_SOURCES="fli,fast-flights,playwright".
_src_env = os.environ.get("FLIGHT_SOURCES")
SOURCES = build_sources(_src_env.split(",") if _src_env else None)

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


def random_delay(min_s=None, max_s=None):
    """Polite delay between calls. GitHub Actions allows 6h/job and a full
    batch is well under that, so we space calls out generously to avoid
    looking like a bot burst from a single datacenter IP. Overridable via
    DELAY_MIN_S / DELAY_MAX_S env vars."""
    lo = float(os.environ.get("DELAY_MIN_S", min_s if min_s is not None else 8))
    hi = float(os.environ.get("DELAY_MAX_S", max_s if max_s is not None else 18))
    time.sleep(random.uniform(lo, hi))


def _fmt_time(dt):
    """Format a datetime as e.g. '7:00 AM'. Returns '' if dt is falsy."""
    if not dt:
        return ""
    # %-I is platform-dependent; strip a leading zero manually for portability.
    return dt.strftime("%I:%M %p").lstrip("0")


# ── Core search ───────────────────────────────────────────────────────────────

def _search_route_multisource(src, dest, days_out):
    """Try each source in fallback order; return (flights, source_name, errored).
    Retries each source on transient empties before falling through to the next.
    `errored` is True only when EVERY source raised an exception (a real outage)
    rather than cleanly returning no flights — so callers can tell "route has no
    fares" apart from "the pipeline is broken"."""
    target_date = (datetime.now() + timedelta(days=days_out)).strftime("%Y-%m-%d")
    any_clean_empty = False  # at least one source returned cleanly (no exception)
    for source in SOURCES:
        raised_every_attempt = True
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                flights = source.search(src, dest, target_date)
                raised_every_attempt = False  # got a clean answer (possibly empty)
                if flights:
                    return flights, source.name, False
            except Exception as e:  # noqa: BLE001 - try the next source, never abort
                if attempt == MAX_ATTEMPTS:
                    print(f"     [{source.name}] error after {MAX_ATTEMPTS} tries: {e!r}")
            if attempt < MAX_ATTEMPTS:
                time.sleep(BACKOFF_SCHEDULE[attempt - 1])
        if not raised_every_attempt:
            any_clean_empty = True
        # this source gave nothing — fall through to the next
    # errored = no source ever returned cleanly (all raised) → genuine outage
    return [], None, (not any_clean_empty)


def _flight_to_row(flight, src, dest, days_out, category, num_results, data_source):
    """Map a NormalizedFlight to a CSV row dict matching CSV_HEADERS."""
    today = datetime.now()
    target_date = today + timedelta(days=days_out)

    dep_dt = flight.departure_dt
    arr_dt = flight.arrival_dt
    departure_hour = dep_dt.hour if dep_dt else ""

    # Overnight: arrival calendar date later than departure calendar date.
    is_overnight = bool(dep_dt and arr_dt and arr_dt.date() > dep_dt.date())

    return {
        "Schema_Version": SCHEMA_VERSION,
        "Scrape_Timestamp": today.strftime("%Y-%m-%d %H:%M:%S"),
        "Days_to_Departure": days_out,
        "Departure_Date": target_date.strftime("%Y-%m-%d"),
        "Day_of_Week": target_date.strftime("%A"),
        "Booking_Day_Of_Week": today.strftime("%A"),
        "Departure_Time": _fmt_time(dep_dt),
        "Departure_ISO": dep_dt.isoformat() if dep_dt else "",
        "Departure_Hour": departure_hour,
        "Arrival_Time": _fmt_time(arr_dt),
        "Arrival_ISO": arr_dt.isoformat() if arr_dt else "",
        "Is_Weekend_Departure": int(target_date.weekday() >= 5),
        "Is_Overnight": int(is_overnight),
        "Source_City": src,
        "Destination_City": dest,
        "Airline": flight.airline or "",
        "Flight_Number": flight.flight_number or "",
        "Aircraft": flight.aircraft or "",
        "Total_Duration_Mins": flight.duration_mins if flight.duration_mins is not None else "",
        "Number_of_Stops": flight.stops,
        "Layover_City": flight.layover_city or "",
        "Layover_Duration_Mins": flight.layover_duration_mins if flight.layover_duration_mins is not None else "",
        "Self_Transfer": int(bool(flight.self_transfer)),
        # CO2 stored as kilograms (sources provide grams).
        "CO2_Emissions_Kg": round(flight.co2_g / 1000) if flight.co2_g is not None else 0,
        "CO2_Delta_Pct": flight.co2_delta_pct if flight.co2_delta_pct is not None else "",
        "Num_Results": num_results,
        "Data_Source": data_source,
        "Flight_Category": category,
        "Price_INR": int(flight.price) if flight.price is not None else None,
    }


def _median_by_price(flights):
    """Return the median-priced NormalizedFlight from a list (by price)."""
    priced = [f for f in flights if f.price is not None]
    if not priced:
        return None
    priced.sort(key=lambda f: f.price)
    return priced[len(priced) // 2]


def scrape_flight(src, dest, days_out):
    """
    Search a route+date via the multi-source layer (one call, best-sorted).
    Derives Best / Cheapest / Median from the single result list — half the
    API calls of the old two-search approach. Returns a list of CSV row dicts;
    a NoFlights row if the route genuinely has no fares.
    """
    flights, data_source, errored = _search_route_multisource(src, dest, days_out)

    if errored:
        # Every source raised — a real outage, NOT a route with no fares.
        print(f"  ❌ All sources errored for {src}→{dest} +{days_out}d")
        return None

    # Only flights with an actual price are usable. If a source returned rows
    # but none has a price, treat it as no-fares (don't emit a priceless Best).
    priced = [f for f in flights if f.price is not None]
    if not priced:
        print(f"  ⚪ No fares for {src}→{dest} +{days_out}d (recorded as NoFlights)")
        return [_no_flight_row(src, dest, days_out)]

    num_results = len(priced)
    best = flights[0] if flights[0].price is not None else priced[0]  # Google's "best"
    cheapest = min(priced, key=lambda f: f.price)
    median = _median_by_price(priced)

    rows = [_flight_to_row(best, src, dest, days_out, "Best", num_results, data_source)]
    rows.append(_flight_to_row(cheapest, src, dest, days_out, "Cheapest", num_results, data_source))
    # Median only when it's a genuinely different price from Cheapest.
    if median is not None and median.price != cheapest.price:
        rows.append(_flight_to_row(median, src, dest, days_out, "Median", num_results, data_source))

    bp, cp = best.price, cheapest.price
    mp = median.price if median else None
    print(f"  ✅ {src}→{dest} +{days_out}d [{data_source}]: "
          f"Best {int(bp) if bp is not None else '—'} | Cheapest {int(cp)} | "
          f"Median {int(mp) if mp is not None else '—'}  ({num_results} results)")
    return rows


# ── CSV Writer ──────────────────────────────────────────────────────────────

def ensure_csv(path):
    """Create data dir and the given month's CSV with headers if absent."""
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(path):
        with open(path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
            writer.writeheader()


def extend_rows(rows, path):
    """Append rows to the given month's CSV (ensuring it exists first)."""
    ensure_csv(path)
    with open(path, 'a', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        writer.writerows(rows)


def _no_flight_row(src, dest, days_out):
    """A row recording that a route genuinely returned no flights — absence
    is itself a useful signal for the model."""
    today = datetime.now()
    target_date = today + timedelta(days=days_out)
    row = {h: "" for h in CSV_HEADERS}
    row.update({
        "Schema_Version": SCHEMA_VERSION,
        "Scrape_Timestamp": today.strftime("%Y-%m-%d %H:%M:%S"),
        "Days_to_Departure": days_out,
        "Departure_Date": target_date.strftime("%Y-%m-%d"),
        "Day_of_Week": target_date.strftime("%A"),
        "Booking_Day_Of_Week": today.strftime("%A"),
        "Is_Weekend_Departure": int(target_date.weekday() >= 5),
        "Source_City": src,
        "Destination_City": dest,
        "Num_Results": 0,
        "Flight_Category": "NoFlights",
        "Price_INR": "",
    })
    return row


# ── Main ────────────────────────────────────────────────────────────────────

def run_canary():
    """Patiently confirm the pipeline can fetch a known-good route before
    committing to a full run. Retries for up to CANARY_MAX_WAIT_S to absorb the
    datacenter-IP warm-up period (fresh IPs get empty responses for the first
    few minutes, then start working). Returns True as soon as any source serves
    fares; False only if the entire window elapses with nothing — the genuine
    library-rot / hard-block signal."""
    src, dest = CANARY_ROUTE
    print(f"🐤 Canary check: {src}→{dest} +{CANARY_DAYS_OUT}d "
          f"(sources: {', '.join(s.name for s in SOURCES) or 'NONE'}; "
          f"patient up to {int(CANARY_MAX_WAIT_S)}s) ...")
    if not SOURCES:
        print("   ❌ Canary FAILED — no flight sources could be initialised.")
        return False

    deadline = time.monotonic() + CANARY_MAX_WAIT_S
    attempt = 0
    while True:
        attempt += 1
        flights, used, _errored = _search_route_multisource(src, dest, CANARY_DAYS_OUT)
        priced = [f for f in (flights or []) if f.price is not None]
        if priced:
            cheapest = int(min(f.price for f in priced))
            print(f"   ✅ Canary OK via [{used}] on attempt {attempt} "
                  f"({len(flights)} results, cheapest ₹{cheapest})")
            return True
        if time.monotonic() >= deadline:
            break
        print(f"   … attempt {attempt} empty (likely IP warm-up); "
              f"retrying in {int(CANARY_PROBE_INTERVAL_S)}s")
        time.sleep(CANARY_PROBE_INTERVAL_S)

    print(f"   ❌ Canary FAILED — no fares for a known-good route after "
          f"{int(CANARY_MAX_WAIT_S)}s across all sources. Pipeline likely "
          f"broken (protocol change) or IP hard-blocked.")
    return False


def main():
    # Canary first — before touching rotation state — so CANARY_ONLY recovery
    # checks don't perturb the batch counter. Abort if every source is broken,
    # so we never commit a silently-empty dataset and the job shows red.
    healthy = run_canary()
    if os.environ.get("CANARY_ONLY"):
        # Used by the workflow's recovery step to test a freshly-upgraded library
        # without running a full scrape. Exit 0 if healthy, non-zero otherwise.
        sys.exit(0 if healthy else 2)
    if not healthy:
        sys.exit(2)

    routes, batch_index = get_todays_routes()

    global DAYS_OUT
    if os.environ.get("TEST_RUN"):
        print("🧪 Running in TEST_RUN mode (1 route, 1 horizon)")
        routes = routes[:1]
        DAYS_OUT = [1]

    out_path = current_file_path()
    ensure_csv(out_path)

    total_scrapes = len(routes) * len(DAYS_OUT)
    print("\n🛫 Flight Scraper Starting (multi-source: "
          f"{', '.join(s.name for s in SOURCES)})")
    print(f"   Routes today: {len(routes)} (batch {batch_index + 1}/3)")
    print(f"   Horizons: {DAYS_OUT}")
    print(f"   Total scrapes: {total_scrapes}")
    print(f"   Output file: {out_path}")
    print()

    success_count = 0   # scrapes that yielded ≥1 flight row
    noflight_count = 0  # scrapes that returned a NoFlights row (valid, but no fares)
    fail_count = 0      # scrapes that errored out entirely

    for i, (src, dest) in enumerate(routes):
        print(f"\n[{i+1}/{len(routes)}] Route: {src} → {dest}")

        for days in DAYS_OUT:
            results = scrape_flight(src, dest, days)
            if results:
                extend_rows(results, out_path)
                if results[0].get("Flight_Category") == "NoFlights":
                    noflight_count += 1
                else:
                    success_count += 1
            else:
                fail_count += 1

            random_delay()

    attempted = success_count + noflight_count + fail_count
    # The meaningful health signal is the fraction of scrapes that returned
    # actual FARES. Counting NoFlights as "ok" would let a total source breakage
    # (every route empty) stay green — exactly the silent failure we must catch.
    # So the gate is on fares only; NoFlights and errors both fall below it.
    fare_rate = (success_count / attempted) if attempted else 0.0

    print(f"\n{'='*50}")
    print("🏁 Scraping Complete!")
    print(f"   ✅ With fares:  {success_count}")
    print(f"   ⚪ No flights:  {noflight_count}")
    print(f"   ❌ Errored:     {fail_count}")
    print(f"   📊 Fare rate: {fare_rate*100:.1f}%  (threshold {MIN_SUCCESS_RATE*100:.0f}%)")
    print(f"   📁 Data saved to: {out_path}")

    # Fail-loud gate: a low fare rate means a partial outage / IP block /
    # library rot. Exit non-zero so the GitHub Actions run shows red.
    if attempted and fare_rate < MIN_SUCCESS_RATE:
        print(f"\n⛔ Fare rate {fare_rate*100:.1f}% below threshold "
              f"{MIN_SUCCESS_RATE*100:.0f}% — failing the job for visibility.")
        sys.exit(3)


if __name__ == "__main__":
    main()
