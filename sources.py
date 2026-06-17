"""
Multi-source flight data layer.

Each "source" wraps one way of getting Google Flights data behind a common
interface and returns a list of `NormalizedFlight`. The scraper tries sources
in order and uses the first that answers — so if one library breaks (e.g.
Google changes its protocol and `fli` stops decoding), collection continues
via the next source instead of going dark.

Sources (in fallback order):
  1. FliSource         — `fli` / `flights` (protobuf API). Primary.
  2. FastFlightsSource — `fast-flights` (different protobuf impl). Fallback 2A.
  3. PlaywrightSource  — headless-browser DOM scrape. Last resort 2B.

Adapters isolate each library's quirks; one breaking never touches the others.
Heavy/optional deps (fli, fast_flights, playwright) are imported lazily inside
each adapter so a missing/broken library only disables that one source.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


# ── Normalized model ──────────────────────────────────────────────────────────

@dataclass
class NormalizedFlight:
    """Source-agnostic flight record. All sources map their results to this so
    the scraper / CSV logic never sees library-specific objects."""
    price: Optional[float]            # in INR
    airline: str
    flight_number: str
    aircraft: str
    departure_dt: Optional[datetime]
    arrival_dt: Optional[datetime]
    duration_mins: Optional[int]
    stops: int
    layover_city: str
    layover_duration_mins: Optional[int]
    self_transfer: bool
    co2_g: Optional[int]              # grams
    co2_delta_pct: Optional[int]      # % vs typical (None if unknown)


class FlightSource:
    """Common contract. `search` returns a list of NormalizedFlight (best-sorted
    where the source supports it), or None on empty/error."""
    name: str = "base"

    def search(self, src_iata: str, dest_iata: str, date_str: str):
        raise NotImplementedError


def _simpledt_to_datetime(sdt):
    """fast-flights SimpleDatetime(date=[y,m,d], time=[H,M]) -> datetime."""
    if sdt is None:
        return None
    try:
        y, m, d = sdt.date
        hh, mm = sdt.time
        return datetime(y, m, d, hh, mm)
    except Exception:
        return None


# ── Source 1: fli (primary) ─────────────────────────────────────────────────────

class FliSource(FlightSource):
    name = "fli"

    def __init__(self):
        # Lazy imports so a broken/missing fli only disables this source.
        from fli.models import (
            Airport, FlightSearchFilters, FlightSegment, MaxStops,
            PassengerInfo, SeatType, SortBy,
        )
        from fli.search import SearchFlights
        self._A = Airport
        self._Filters = FlightSearchFilters
        self._Segment = FlightSegment
        self._MaxStops = MaxStops
        self._Pax = PassengerInfo
        self._Seat = SeatType
        self._SortBy = SortBy
        self._Search = SearchFlights

    def search(self, src_iata, dest_iata, date_str):
        src = getattr(self._A, src_iata, None)
        dest = getattr(self._A, dest_iata, None)
        if src is None or dest is None:
            return None
        filters = self._Filters(
            passenger_info=self._Pax(adults=1),
            flight_segments=[self._Segment(
                departure_airport=[[src, 0]],
                arrival_airport=[[dest, 0]],
                travel_date=date_str,
            )],
            seat_type=self._Seat.ECONOMY,
            stops=self._MaxStops.ANY,
            sort_by=self._SortBy.BEST,   # best-sorted; cheapest = min(price)
        )
        results = self._Search().search(filters)
        if not results:
            return None
        return [self._normalize(r) for r in results]

    def _normalize(self, r):
        first = r.legs[0] if r.legs else None
        airline = r.primary_airline_name or (
            first.airline.value if (first and first.airline) else "")
        layover_city = ""
        layover_dur = None
        if r.layovers:
            lo = r.layovers[0]
            layover_city = lo.city or (lo.airport.value if lo.airport else "")
            layover_dur = lo.duration
        return NormalizedFlight(
            price=r.price,
            airline=airline or "",
            flight_number=(first.flight_number if first else "") or "",
            aircraft=(first.aircraft if first else "") or "",
            departure_dt=first.departure_datetime if first else None,
            arrival_dt=(r.legs[-1].arrival_datetime if r.legs else None),
            duration_mins=r.duration,
            stops=r.stops,
            layover_city=layover_city,
            layover_duration_mins=layover_dur,
            self_transfer=bool(r.self_transfer),
            co2_g=r.co2_emissions_g,
            co2_delta_pct=r.co2_emissions_delta_pct,
        )


# ── Source 2A: fast-flights (fallback) ──────────────────────────────────────────

class FastFlightsSource(FlightSource):
    name = "fast-flights"

    def __init__(self):
        from fast_flights import (
            FlightQuery, Passengers, create_filter, get_flights,
        )
        self._FlightQuery = FlightQuery
        self._Passengers = Passengers
        self._create_filter = create_filter
        self._get_flights = get_flights

    def search(self, src_iata, dest_iata, date_str):
        q = self._create_filter(
            flights=[self._FlightQuery(
                date=date_str, from_airport=src_iata, to_airport=dest_iata,
            )],
            seat="economy",
            trip="one-way",
            passengers=self._Passengers(adults=1),
            currency="INR",
        )
        res = self._get_flights(q)
        flights = getattr(res, "flights", res)
        if not flights:
            return None
        return [self._normalize(f) for f in flights]

    def _normalize(self, f):
        legs = getattr(f, "flights", []) or []
        first = legs[0] if legs else None
        last = legs[-1] if legs else None
        stops = max(len(legs) - 1, 0)

        # Layover = the connection airport between leg 0 and leg 1 (if any).
        layover_city = ""
        layover_dur = None
        if len(legs) >= 2 and first is not None:
            arr0 = _simpledt_to_datetime(first.arrival)
            dep1 = _simpledt_to_datetime(legs[1].departure)
            if first.to_airport is not None:
                layover_city = getattr(first.to_airport, "code", "") or ""
            if arr0 and dep1:
                layover_dur = int((dep1 - arr0).total_seconds() // 60)

        airlines = getattr(f, "airlines", None) or []
        airline = airlines[0] if airlines else ""
        carbon = getattr(f, "carbon", None)
        co2_g = getattr(carbon, "emission", None) if carbon else None
        co2_typ = getattr(carbon, "typical_on_route", None) if carbon else None
        co2_delta = None
        if co2_g is not None and co2_typ:
            co2_delta = round((co2_g - co2_typ) / co2_typ * 100)

        return NormalizedFlight(
            price=getattr(f, "price", None),
            airline=airline,
            flight_number=getattr(f, "type", "") or "",  # airline code (no number exposed)
            aircraft=(getattr(first, "plane_type", "") if first else "") or "",
            departure_dt=_simpledt_to_datetime(first.departure) if first else None,
            arrival_dt=_simpledt_to_datetime(last.arrival) if last else None,
            duration_mins=sum(getattr(l, "duration", 0) or 0 for l in legs) or None,
            stops=stops,
            layover_city=layover_city,
            layover_duration_mins=layover_dur,
            self_transfer=False,  # not exposed
            co2_g=co2_g,
            co2_delta_pct=co2_delta,
        )


# ── Source 2B: Playwright DOM scrape (last resort) ──────────────────────────────

class PlaywrightSource(FlightSource):
    """Last-resort headless-browser scraper. Imports Playwright lazily so the
    dependency is only needed if/when both API sources fail. Kept intentionally
    minimal: returns the visible flight cards' airline/price/stops/duration."""
    name = "playwright"

    def search(self, src_iata, dest_iata, date_str):
        try:
            import re
            from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
        except Exception:
            return None  # Playwright/Chromium not installed → source unavailable.

        q = f"Flights from {src_iata} to {dest_iata} on {date_str}"
        url = (f"https://www.google.com/travel/flights?q={q.replace(' ', '%20')}"
               f"&curr=INR&hl=en&gl=IN&tt=o")

        flights = []
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=[
                    "--no-sandbox", "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                ])
                ctx = browser.new_context(
                    viewport={"width": 1366, "height": 768},
                    user_agent=("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
                    locale="en-IN", timezone_id="Asia/Kolkata",
                )
                ctx.add_init_script(
                    "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
                page = ctx.new_page()
                page.goto(url, timeout=45000, wait_until="domcontentloaded")
                try:
                    page.wait_for_selector("li.pIav2d, div[data-resultid], ul.Rk10dc li",
                                           timeout=20000)
                except PWTimeout:
                    browser.close()
                    return None
                cards = page.query_selector_all("li.pIav2d, div[data-resultid], ul.Rk10dc > li")
                for c in cards:
                    txt = c.inner_text()
                    pm = re.search(r"₹\s*([\d,]+)", txt)
                    price = int(pm.group(1).replace(",", "")) if pm else None
                    if price is None:
                        continue
                    dur = 0
                    dm = re.search(r"(\d+)\s*hr(?:\s*(\d+)\s*min)?", txt)
                    if dm:
                        dur = int(dm.group(1)) * 60 + (int(dm.group(2)) if dm.group(2) else 0)
                    stops = 0 if "nonstop" in txt.lower() else (
                        int(re.search(r"(\d+)\s*stop", txt.lower()).group(1))
                        if re.search(r"(\d+)\s*stop", txt.lower()) else 0)
                    airline = ""
                    for line in (l.strip() for l in txt.split("\n") if l.strip()):
                        if (not re.match(r"^\d{1,2}:\d{2}", line) and "₹" not in line
                                and "hr" not in line and "stop" not in line.lower()
                                and 2 < len(line) < 40):
                            airline = line
                            break
                    flights.append(NormalizedFlight(
                        price=price, airline=airline, flight_number="", aircraft="",
                        departure_dt=None, arrival_dt=None, duration_mins=dur or None,
                        stops=stops, layover_city="", layover_duration_mins=None,
                        self_transfer=False, co2_g=None, co2_delta_pct=None,
                    ))
                browser.close()
        except Exception:
            return None
        return flights or None


# ── Registry ────────────────────────────────────────────────────────────────────

def build_sources(names=None):
    """Instantiate sources in fallback order. A source whose library is missing
    or fails to construct is skipped (logged by caller), not fatal."""
    order = names or ["fli", "fast-flights", "playwright"]
    classes = {
        "fli": FliSource,
        "fast-flights": FastFlightsSource,
        "playwright": PlaywrightSource,
    }
    built = []
    for n in order:
        cls = classes.get(n)
        if cls is None:
            continue
        try:
            built.append(cls())
        except Exception as e:  # noqa: BLE001
            print(f"   ⚠️  source '{n}' unavailable at init: {e!r}")
    return built
