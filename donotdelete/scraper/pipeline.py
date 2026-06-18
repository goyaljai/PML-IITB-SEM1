"""
Main scrape pipeline.

Responsibilities, in order:
  1. Read the current rotation batch (PURE READ — counter is NOT advanced here).
  2. Run the startup canary; abort if the API is broken.
  3. For each (route, horizon) in the batch:
       - search fast-flights
       - derive Best / Cheapest / Median (or a NoFlights marker)
       - validate every row
       - append valid rows to ``data/flights_YYYY_MM.csv``
       - sleep a random delay (with longer pauses every N routes)
       - honour the wall-clock budget; stop early if exceeded
  4. Compute the fare-rate gate; if below the threshold, exit with a non-zero
     status code AND do not advance the rotation counter.
  5. On success: advance the rotation counter so tomorrow's run gets the
     next batch.

This file is intentionally the only place ``schema.SCHEMA_VERSION`` is read
into output rows — every row goes through ``_make_row`` so a schema bump is
one constant change.
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from . import adapter, routes, writer
from .adapter import AdapterError, APITimeout, FlightsNotFound, NormalizedFlight
from .config import Config
from .schema import SCHEMA_VERSION
from .validator import validate_row

log = logging.getLogger("pipeline")


@dataclass
class RunSummary:
    """Tallies for the post-run gate and operator visibility."""

    attempted: int = 0      # (route, horizon) pairs we tried to scrape
    with_fares: int = 0     # successful with ≥ 1 priced row
    no_flights: int = 0     # empty (NoFlights row written)
    errored: int = 0        # adapter raised after all retries
    rows_written: int = 0
    rows_dropped: int = 0   # validation failures
    budget_hit: bool = False

    @property
    def fare_rate(self) -> float:
        return self.with_fares / self.attempted if self.attempted else 0.0


# ── Row construction ────────────────────────────────────────────────────────


def _fmt_clock(dt: datetime | None) -> str:
    """Cross-platform '%I:%M %p' that strips leading zero (06:05 AM → 6:05 AM)."""
    if not dt:
        return ""
    return dt.strftime("%I:%M %p").lstrip("0")


def _make_row(
    flight: NormalizedFlight | None,
    *,
    origin: str,
    destination: str,
    days_out: int,
    category: str,
    num_results: int,
    run_id: str,
    cabin: str,
    currency: str,
) -> dict[str, object]:
    """Construct a row dict matching ``schema.CSV_HEADERS`` exactly.

    Passing ``flight=None`` produces a NoFlights row — the booking-context
    fields are still filled in (Schema_Version, route, dates, NoFlights tag),
    but the flight-specific fields are empty strings.
    """
    now = datetime.now(timezone.utc).astimezone()
    target_date = now + timedelta(days=days_out)
    is_weekend = int(target_date.weekday() >= 5)

    base: dict[str, object] = {
        "Schema_Version": SCHEMA_VERSION,
        "Scrape_Timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
        "Days_to_Departure": days_out,
        "Departure_Date": target_date.strftime("%Y-%m-%d"),
        "Day_of_Week": target_date.strftime("%A"),
        "Booking_Day_Of_Week": now.strftime("%A"),
        "Departure_Time": "",
        "Departure_ISO": "",
        "Departure_Hour": "",
        "Arrival_Time": "",
        "Arrival_ISO": "",
        "Is_Weekend_Departure": is_weekend,
        "Is_Overnight": 0,
        "Source_City": origin,
        "Destination_City": destination,
        "Airline": "",
        "Flight_Number": "",
        "Aircraft": "",
        "Total_Duration_Mins": "",
        "Number_of_Stops": "",
        "Layover_City": "",
        "Layover_Duration_Mins": "",
        "Self_Transfer": "",
        "CO2_Emissions_Kg": "",
        "CO2_Delta_Pct": "",
        "Num_Results": num_results,
        "Data_Source": "fast-flights",
        "Flight_Category": category,
        "Price_INR": "",
        # v4 additions
        "Carbon_Typical_g": "",
        "Currency": currency,
        "Cabin_Class": cabin,
        "Run_Id": run_id,
    }

    if flight is None:
        # NoFlights row — keep base as-is, with the empties.
        base["Number_of_Stops"] = ""
        return base

    dep = flight.departure_dt
    arr = flight.arrival_dt
    is_overnight = int(bool(dep and arr and arr.date() > dep.date()))

    base.update({
        "Departure_Time": _fmt_clock(dep),
        "Departure_ISO": dep.isoformat() if dep else "",
        "Departure_Hour": dep.hour if dep else "",
        "Arrival_Time": _fmt_clock(arr),
        "Arrival_ISO": arr.isoformat() if arr else "",
        "Is_Overnight": is_overnight,
        "Airline": flight.airline or "",
        "Flight_Number": flight.flight_number or "",
        "Aircraft": flight.aircraft or "",
        "Total_Duration_Mins": flight.duration_mins if flight.duration_mins is not None else "",
        "Number_of_Stops": flight.stops,
        "Layover_City": flight.layover_city or "",
        "Layover_Duration_Mins":
            flight.layover_duration_mins if flight.layover_duration_mins is not None else "",
        "Self_Transfer": int(bool(flight.self_transfer)),
        "CO2_Emissions_Kg":
            round(flight.co2_g / 1000) if flight.co2_g is not None else "",
        "CO2_Delta_Pct": flight.co2_delta_pct if flight.co2_delta_pct is not None else "",
        "Price_INR": flight.price if flight.price is not None else "",
        "Carbon_Typical_g": flight.co2_typical_g if flight.co2_typical_g is not None else "",
    })
    return base


# ── Per-search row derivation ───────────────────────────────────────────────


def _median_by_price(flights: list[NormalizedFlight]) -> NormalizedFlight | None:
    priced = [f for f in flights if f.price is not None]
    if not priced:
        return None
    priced.sort(key=lambda f: f.price or 0)
    return priced[len(priced) // 2]


def _rows_for_search(
    flights: list[NormalizedFlight],
    *,
    origin: str,
    destination: str,
    days_out: int,
    run_id: str,
    cabin: str,
    currency: str,
) -> list[dict[str, object]]:
    """Best/Cheapest/Median (Median only if ≠ Cheapest) for a single search."""
    priced = [f for f in flights if f.price is not None]
    num_results = len(priced)
    if not priced:
        # Empty fast-flights result — emit a NoFlights row (the absence signal).
        return [_make_row(
            None, origin=origin, destination=destination, days_out=days_out,
            category="NoFlights", num_results=0,
            run_id=run_id, cabin=cabin, currency=currency,
        )]

    best = flights[0] if flights[0].price is not None else priced[0]
    cheapest = min(priced, key=lambda f: f.price or 0)
    median = _median_by_price(priced)

    rows = [
        _make_row(best, origin=origin, destination=destination, days_out=days_out,
                  category="Best", num_results=num_results,
                  run_id=run_id, cabin=cabin, currency=currency),
        _make_row(cheapest, origin=origin, destination=destination, days_out=days_out,
                  category="Cheapest", num_results=num_results,
                  run_id=run_id, cabin=cabin, currency=currency),
    ]
    if median is not None and median.price != cheapest.price:
        rows.append(_make_row(
            median, origin=origin, destination=destination, days_out=days_out,
            category="Median", num_results=num_results,
            run_id=run_id, cabin=cabin, currency=currency,
        ))
    return rows


# ── The run ─────────────────────────────────────────────────────────────────


def run(
    cfg: Config,
    *,
    run_id: str,
    routes_override: list[tuple[str, str]] | None = None,
    days_out_override: list[int] | None = None,
    sleep_fn=time.sleep,
    monotonic_fn=time.monotonic,
) -> tuple[RunSummary, Path]:
    """Execute one scrape cycle.

    Returns the summary and the CSV path written. Raises nothing — failures
    are reflected in the summary and via the exit code chosen by the CLI.

    Args:
        cfg:                resolved configuration
        run_id:             stamp tying CSV rows ↔ log lines for this invocation
        routes_override:    if provided, used instead of the rotation batch
                            (smoke-test / manual runs)
        days_out_override:  if provided, used instead of cfg.days_out
        sleep_fn / monotonic_fn: injectable for fast tests
    """
    out_path = writer.monthly_path(cfg.data_dir)
    writer.ensure_file(out_path)

    if routes_override is not None:
        batch_routes = list(routes_override)
        batch_index = -1
        cycle = -1
        log.info("using override routes (%d) — rotation untouched", len(batch_routes))
    else:
        batch = routes.current_batch(cfg.cities, cfg.batches, cfg.state_dir)
        batch_routes = batch.routes
        batch_index = batch.index
        cycle = batch.cycle_count

    horizons = list(days_out_override) if days_out_override is not None else list(cfg.days_out)
    summary = RunSummary()

    total_calls = len(batch_routes) * len(horizons)
    log.info(
        "scrape begin: batch=%s/%d cycle=%d routes=%d horizons=%s total_calls=%d "
        "budget=%ds delay=%.0f–%.0fs out=%s",
        batch_index + 1 if batch_index >= 0 else "OVR", cfg.batches, cycle,
        len(batch_routes), horizons, total_calls,
        cfg.target_runtime_seconds, cfg.delay_min_seconds, cfg.delay_max_seconds,
        out_path,
    )

    deadline = monotonic_fn() + cfg.target_runtime_seconds if cfg.target_runtime_seconds else None

    for route_idx, (origin, destination) in enumerate(batch_routes):
        if deadline is not None and monotonic_fn() >= deadline:
            summary.budget_hit = True
            log.warning(
                "time budget reached after %d/%d routes — stopping early",
                route_idx, len(batch_routes),
            )
            break

        log.info("[%d/%d] route %s→%s", route_idx + 1, len(batch_routes), origin, destination)

        for days in horizons:
            if deadline is not None and monotonic_fn() >= deadline:
                summary.budget_hit = True
                break

            summary.attempted += 1
            target_date = (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%d")

            try:
                results = adapter.search_flights(
                    origin=origin,
                    destination=destination,
                    date_str=target_date,
                    cabin=cfg.cabin,
                    adults=cfg.adults,
                    currency=cfg.currency,
                    timeout_seconds=cfg.api_timeout_seconds,
                    max_attempts=cfg.max_attempts,
                    backoff_base=cfg.backoff_base_seconds,
                    backoff_max=cfg.backoff_max_seconds,
                    backoff_jitter=cfg.backoff_jitter_seconds,
                    sleep_fn=sleep_fn,
                )
            except FlightsNotFound:
                # API returned cleanly but with zero flights — record the absence.
                results = []
            except APITimeout as e:
                summary.errored += 1
                log.error("  +%dd: TIMEOUT %s", days, e)
                _polite_delay(sleep_fn, cfg)
                continue
            except AdapterError as e:
                summary.errored += 1
                log.error("  +%dd: ADAPTER ERROR %s", days, e)
                _polite_delay(sleep_fn, cfg)
                continue

            rows = _rows_for_search(
                results,
                origin=origin, destination=destination, days_out=days,
                run_id=run_id, cabin=cfg.cabin, currency=cfg.currency,
            )

            # Track success kind from the FIRST row (Best, Cheapest, or NoFlights).
            kind = str(rows[0]["Flight_Category"]) if rows else "?"
            if kind == "NoFlights":
                summary.no_flights += 1
                log.info("  +%dd: no fares (NoFlights row)", days)
            else:
                summary.with_fares += 1
                priced_count = sum(1 for r in rows if r["Flight_Category"] in ("Best", "Cheapest", "Median"))
                log.info(
                    "  +%dd: %d priced rows (Best=%s, Cheapest=%s)",
                    days, priced_count, rows[0]["Price_INR"],
                    next((r["Price_INR"] for r in rows if r["Flight_Category"] == "Cheapest"), "?"),
                )

            # Validate then append.
            valid_rows: list[dict[str, object]] = []
            for r in rows:
                ok, reason = validate_row(
                    r,
                    min_price_inr=cfg.min_plausible_price_inr,
                    max_price_inr=cfg.max_plausible_price_inr,
                )
                if ok:
                    valid_rows.append(r)
                else:
                    summary.rows_dropped += 1
                    log.warning(
                        "  +%dd: row dropped (%s/%s): %s",
                        days, r.get("Flight_Category"), r.get("Data_Source"), reason,
                    )

            if valid_rows:
                summary.rows_written += writer.append_rows(out_path, valid_rows)

            _polite_delay(sleep_fn, cfg)

        # Long pause every N routes — see config.
        if cfg.long_pause_every_routes and (route_idx + 1) % cfg.long_pause_every_routes == 0:
            if deadline is not None and monotonic_fn() >= deadline:
                summary.budget_hit = True
                break
            pause = random.uniform(cfg.long_pause_min_seconds, cfg.long_pause_max_seconds)
            log.info("polite breather: sleeping %.0fs after %d routes", pause, route_idx + 1)
            sleep_fn(pause)

    log.info(
        "scrape end: attempted=%d with_fares=%d no_flights=%d errored=%d "
        "rows_written=%d rows_dropped=%d fare_rate=%.1f%% budget_hit=%s",
        summary.attempted, summary.with_fares, summary.no_flights, summary.errored,
        summary.rows_written, summary.rows_dropped, summary.fare_rate * 100, summary.budget_hit,
    )
    return summary, out_path


def _polite_delay(sleep_fn, cfg: Config) -> None:
    """Sleep a uniform-random delay in the configured band."""
    sleep_fn(random.uniform(cfg.delay_min_seconds, cfg.delay_max_seconds))


# ── Convenience for the CLI ─────────────────────────────────────────────────


def passes_quality_gate(summary: RunSummary, min_fare_rate: float) -> bool:
    """The fare-rate gate: did enough scrapes return ≥ 1 priced row?

    Returns False (i.e. "reject") only when we actually attempted scrapes — a
    canary abort that exits before the loop runs leaves attempted == 0 and we
    handle that path separately.
    """
    if summary.attempted == 0:
        return False
    return summary.fare_rate >= min_fare_rate
