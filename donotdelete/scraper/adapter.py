"""
fast-flights adapter.

Wraps the third-party ``fast_flights`` package behind a tight, normalised
interface that the rest of the pipeline talks to. The goals:

  * **One library, no fallbacks.** v3 had three sources; v4 has one (fast-flights,
    pinned to "latest" via the cron's pre-run ``pip install --upgrade``). If
    fast-flights breaks, the run exits red — silent fallback to a different
    library would mask the breakage and let bad data in.
  * **Retries with backoff and jitter.** Transient errors (network blip, an
    intermittent Google rate-limit response) get up to N retries with
    exponential backoff. Persistent errors propagate.
  * **Per-call timeout.** A hung call (Google returning a slow-loris response)
    can't stall the full daily run.
  * **Normalised output.** The rest of the pipeline never imports
    ``fast_flights`` directly, so a future library swap touches this file only.
"""

from __future__ import annotations

import logging
import random
import signal
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Generator, Iterable, Optional

# Lazy import of fast_flights — kept inside functions so the rest of the
# package is importable for tests/mocking even if fast_flights isn't installed.

log = logging.getLogger("adapter")


# ── Normalised flight model ─────────────────────────────────────────────────


@dataclass(frozen=True)
class NormalizedFlight:
    """Source-agnostic flight record. The pipeline never sees a fast_flights
    object — only this. If we ever swap libraries, this file is the only
    place that changes."""

    price: Optional[int]                  # INR, integer rupees (None = unpriced)
    airline: str                          # primary airline name
    airlines: tuple[str, ...]             # full list (multi-carrier itineraries)
    flight_number: str                    # not exposed by fast-flights → ""
    aircraft: str                         # first-leg plane_type (e.g. "Airbus A320neo")
    departure_dt: Optional[datetime]
    arrival_dt: Optional[datetime]
    duration_mins: Optional[int]          # total itinerary duration
    stops: int                            # 0 = nonstop, n = n stops
    layover_city: str                     # IATA code of the first layover (empty if nonstop)
    layover_duration_mins: Optional[int]  # in minutes; None when unknown
    self_transfer: bool                   # not exposed by fast-flights → always False
    co2_g: Optional[int]                  # grams CO₂ per passenger
    co2_typical_g: Optional[int]          # grams; what's "typical" on this route
    co2_delta_pct: Optional[int]          # derived: % above/below typical


# ── Exceptions ──────────────────────────────────────────────────────────────


class AdapterError(RuntimeError):
    """Any failure from the adapter layer. Subclasses give more detail."""


class APITimeout(AdapterError):
    """The underlying API call exceeded the configured per-call timeout."""


class FlightsNotFound(AdapterError):
    """Search returned cleanly but with zero flights — a valid 'no fares' signal,
    not an outage. Raised so the pipeline can treat it differently from errors."""


# ── Internal: SIGALRM-based call timeout ────────────────────────────────────


@contextmanager
def _call_timeout(seconds: int) -> Generator[None, None, None]:
    """POSIX SIGALRM-based timeout. Active only in the main thread; safe for
    cron use (single-threaded process). On non-main threads it degrades to
    no-op rather than crashing.
    """
    if seconds <= 0:
        yield
        return

    try:
        import threading
        if threading.current_thread() is not threading.main_thread():
            # SIGALRM only works in the main thread; tests may run us in workers.
            yield
            return
    except Exception:
        yield
        return

    def _handler(signum, frame):  # noqa: ANN001
        raise APITimeout(f"fast-flights call exceeded {seconds}s")

    previous = signal.signal(signal.SIGALRM, _handler)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


# ── Internal: SimpleDatetime → datetime ─────────────────────────────────────


def _to_datetime(sdt) -> Optional[datetime]:  # noqa: ANN001 - external type
    """Convert fast-flights ``SimpleDatetime`` (date=(y,m,d), time=(h,m)) to
    a ``datetime``. Returns ``None`` if the value is missing or malformed."""
    if sdt is None:
        return None
    try:
        y, m, d = sdt.date
        hh, mm = sdt.time
        return datetime(y, m, d, hh, mm)
    except Exception:  # noqa: BLE001 - normalise any malformed payload
        return None


# ── Internal: normalise a fast-flights row ──────────────────────────────────


def _normalize(row) -> NormalizedFlight:  # noqa: ANN001 - external type
    legs = list(getattr(row, "flights", []) or [])
    first = legs[0] if legs else None
    last = legs[-1] if legs else None
    stops = max(len(legs) - 1, 0)

    airlines_list = tuple(getattr(row, "airlines", None) or ())
    primary = airlines_list[0] if airlines_list else ""

    # Layover city = the connecting airport (i.e. arrival of leg 0).
    layover_city = ""
    layover_duration = None
    if len(legs) >= 2 and first is not None:
        if first.to_airport is not None:
            layover_city = getattr(first.to_airport, "code", "") or ""
        arr0 = _to_datetime(first.arrival)
        dep1 = _to_datetime(legs[1].departure)
        if arr0 and dep1:
            layover_duration = max(int((dep1 - arr0).total_seconds() // 60), 0)

    carbon = getattr(row, "carbon", None)
    co2_g = getattr(carbon, "emission", None) if carbon else None
    co2_typical = getattr(carbon, "typical_on_route", None) if carbon else None
    co2_delta_pct = None
    if isinstance(co2_g, (int, float)) and isinstance(co2_typical, (int, float)) and co2_typical:
        co2_delta_pct = round((co2_g - co2_typical) / co2_typical * 100)

    # Total duration: prefer sum-of-legs over a top-level duration (sources
    # differ here; sum-of-legs matches the legacy v3 mapping).
    duration_mins: Optional[int] = None
    leg_durs = [int(getattr(leg, "duration", 0) or 0) for leg in legs]
    if any(leg_durs):
        duration_mins = sum(leg_durs)

    price_raw = getattr(row, "price", None)
    price = int(price_raw) if isinstance(price_raw, (int, float)) and price_raw > 0 else None

    return NormalizedFlight(
        price=price,
        airline=primary,
        airlines=airlines_list,
        flight_number="",  # fast-flights does not expose per-leg flight numbers
        aircraft=(getattr(first, "plane_type", "") if first else "") or "",
        departure_dt=_to_datetime(first.departure) if first else None,
        arrival_dt=_to_datetime(last.arrival) if last else None,
        duration_mins=duration_mins,
        stops=stops,
        layover_city=layover_city,
        layover_duration_mins=layover_duration,
        self_transfer=False,
        co2_g=int(co2_g) if isinstance(co2_g, (int, float)) else None,
        co2_typical_g=int(co2_typical) if isinstance(co2_typical, (int, float)) else None,
        co2_delta_pct=co2_delta_pct,
    )


# ── Public: search ──────────────────────────────────────────────────────────


def search_flights(
    *,
    origin: str,
    destination: str,
    date_str: str,
    cabin: str = "economy",
    adults: int = 1,
    currency: str = "INR",
    timeout_seconds: int = 30,
    max_attempts: int = 3,
    backoff_base: float = 2.0,
    backoff_max: float = 30.0,
    backoff_jitter: float = 1.5,
    sleep_fn=time.sleep,  # injectable for tests
) -> list[NormalizedFlight]:
    """Search Google Flights for ``origin → destination`` on ``date_str``.

    Returns a list of ``NormalizedFlight``, best-sorted (Google's default
    ordering — index 0 is the "best" choice).

    Empty result (zero flights) raises ``FlightsNotFound`` so the caller can
    distinguish "route has no fares" from "API errored". A timeout raises
    ``APITimeout``. Any other persistent error raises ``AdapterError`` after
    exhausting retries.

    Retries: exponential backoff (base × 2**n) capped at ``backoff_max`` plus
    uniform random jitter, on every exception including ``FlightsNotFound``
    (the route really might be empty, but a fresh-IP warm-up empty looks
    identical — we retry once or twice and accept the empty after that).
    """
    # Lazy import — keeps the rest of the module testable without the dep.
    from fast_flights import (
        FlightQuery,
        FlightsNotFound as _FfNotFound,  # noqa: N814
        Passengers,
        create_filter,
        get_flights,
    )

    if max_attempts < 1:
        raise ValueError("max_attempts must be ≥ 1")

    last_exc: Optional[Exception] = None
    last_empty = False

    for attempt in range(1, max_attempts + 1):
        try:
            q = create_filter(
                flights=[FlightQuery(
                    date=date_str,
                    from_airport=origin,
                    to_airport=destination,
                )],
                seat=cabin,                                      # type: ignore[arg-type]
                trip="one-way",
                passengers=Passengers(adults=adults),
                currency=currency,                               # type: ignore[arg-type]
            )
            with _call_timeout(timeout_seconds):
                result = get_flights(q)
        except _FfNotFound as e:
            last_empty = True
            last_exc = FlightsNotFound(f"{origin}→{destination} {date_str}: {e}")
            log.warning(
                "fast-flights NOT_FOUND attempt %d/%d: %s→%s on %s",
                attempt, max_attempts, origin, destination, date_str,
            )
        except APITimeout as e:
            last_empty = False
            last_exc = e
            log.warning(
                "fast-flights TIMEOUT attempt %d/%d: %s→%s on %s",
                attempt, max_attempts, origin, destination, date_str,
            )
        except Exception as e:  # noqa: BLE001 - all other library errors → retry
            last_empty = False
            last_exc = AdapterError(f"fast-flights error: {type(e).__name__}: {e}")
            log.warning(
                "fast-flights ERROR attempt %d/%d: %s→%s on %s: %s",
                attempt, max_attempts, origin, destination, date_str, e,
            )
        else:
            flights = list(result) if result else []
            if flights:
                return [_normalize(f) for f in flights]
            last_empty = True
            last_exc = FlightsNotFound(f"{origin}→{destination} {date_str}: empty result")
            log.info(
                "fast-flights empty result attempt %d/%d: %s→%s on %s",
                attempt, max_attempts, origin, destination, date_str,
            )

        if attempt < max_attempts:
            delay = min(backoff_base * (2 ** (attempt - 1)), backoff_max)
            delay += random.uniform(0, backoff_jitter)
            sleep_fn(delay)

    assert last_exc is not None
    if last_empty:
        raise last_exc                                       # FlightsNotFound
    raise last_exc                                           # APITimeout or AdapterError
