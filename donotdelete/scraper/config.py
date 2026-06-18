"""
Configuration loader.

All tunables live in ``donotdelete/config/scraper.yaml`` so an operator can
adjust pacing, plausibility bands, or paths without editing source. Every
setting has a hard-coded fallback in ``DEFAULTS`` so the scraper still runs if
the YAML is missing — useful for ``--smoke`` invocations and tests.

Environment-variable overrides (``SCRAPER_<KEY>``) take precedence over the
file, so a one-off cron variation can be made without committing a config
change. This is the only "magic" — there's no other source of truth besides
the YAML and the defaults below.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import timezone, tzinfo
from pathlib import Path
from typing import Any

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python < 3.9
    ZoneInfo = None  # type: ignore[assignment]

log = logging.getLogger("config")


def resolve_timezone(name: str) -> tzinfo:
    """Resolve an IANA zone name (e.g. ``Asia/Kolkata``) to a ``tzinfo``.

    Falls back to UTC — never raises — so a host missing the tz database still
    runs (it just stamps UTC). The fallback is logged so the divergence is
    visible in the run log rather than silent.
    """
    if not name or name.upper() == "UTC":
        return timezone.utc
    if ZoneInfo is None:
        log.warning("zoneinfo unavailable — display_timezone %r ignored, using UTC", name)
        return timezone.utc
    try:
        return ZoneInfo(name)
    except Exception as e:  # noqa: BLE001 - bad name / missing tzdata → UTC
        log.warning("could not resolve display_timezone %r (%s) — using UTC", name, e)
        return timezone.utc

try:
    import yaml  # PyYAML
except ImportError as e:  # pragma: no cover - dependency guaranteed in prod
    raise SystemExit(
        "PyYAML is required. Install with: pip install PyYAML"
    ) from e


# ── Defaults ─────────────────────────────────────────────────────────────────

DEFAULTS: dict[str, Any] = {
    # ── Topology ────────────────────────────────────────────────────────────
    # 15 Indian-domestic cities, preserving the historical v3 city set so old
    # data and new data share the same route universe (15 × 14 = 210 directed).
    "cities": {
        "Mumbai": "BOM",
        "Delhi": "DEL",
        "Bengaluru": "BLR",
        "Hyderabad": "HYD",
        "Chennai": "MAA",
        "Kolkata": "CCU",
        "Pune": "PNQ",
        "Ahmedabad": "AMD",
        "Surat": "STV",
        "Visakhapatnam": "VTZ",
        "Jaipur": "JAI",
        "Kochi": "COK",
        "Chandigarh": "IXC",
        "Indore": "IDR",
        "Lucknow": "LKO",
    },
    "days_out": [1, 3, 7, 14, 30, 60],

    # ── Batching ────────────────────────────────────────────────────────────
    # 3-day rotation: 210 routes split into 3 batches of 70. The counter
    # persists across runs and advances only on a successful run (fixing the
    # v3 bug where a failed run still bumped the counter).
    "batches": 3,

    # ── Paths (relative to donotdelete/) ────────────────────────────────────
    "data_dir": "data",
    "log_dir": "logs",
    "state_dir": "data",
    "lock_file": ".lock",

    # ── Pacing — target ≤ 2 h per daily batch ──────────────────────────────
    # 70 routes × 6 horizons = 420 calls. With ~15 s inter-call delay and
    # ~1.5 s API latency, expected wall-clock is ~115 min. The budget below
    # is a hard ceiling: when reached, the scraper stops, commits what it has,
    # and does NOT advance the rotation counter.
    "target_runtime_seconds": 7200,
    "delay_min_seconds": 12,
    "delay_max_seconds": 20,
    # An extra polite pause every N routes — looks less like a steady burst.
    "long_pause_every_routes": 10,
    "long_pause_min_seconds": 45,
    "long_pause_max_seconds": 90,

    # ── Per-call retry ──────────────────────────────────────────────────────
    "max_attempts": 3,
    "backoff_base_seconds": 2.0,
    "backoff_max_seconds": 30.0,
    "backoff_jitter_seconds": 1.5,
    "api_timeout_seconds": 30,

    # ── Plausibility ────────────────────────────────────────────────────────
    # Indian-domestic economy fares observed over years sit comfortably inside
    # this band. Anything outside is a parsing artefact (the fli ₹69 bug was
    # the original motivation for this filter; fast-flights is cleaner but the
    # filter remains as defence in depth).
    "min_plausible_price_inr": 1000,
    "max_plausible_price_inr": 200000,

    # ── Canary (startup health check) ───────────────────────────────────────
    "canary_route": ["BOM", "DEL"],
    "canary_days_out": 7,
    "canary_max_wait_seconds": 900,        # tolerate fresh-IP warm-up
    "canary_probe_interval_seconds": 30,
    "canary_attempts": 3,                  # within a probe, retry transient

    # ── Post-run gate ───────────────────────────────────────────────────────
    # Fraction of (route, horizon) scrapes that must return ≥ 1 priced flight.
    "min_success_rate": 0.60,
    # When True (default): a run BELOW the gate still commits whatever valid
    # rows it fetched (every written row already passed per-row validation —
    # plausible price, real route, correct schema), logging a prominent WARNING
    # instead of discarding the work. Only a run that fetched ZERO valid rows
    # exits non-zero (EXIT_GATE). When False: legacy behaviour — below the gate
    # the run exits EXIT_GATE and commits nothing. The startup canary still
    # guards against a fully-broken API regardless of this setting.
    "commit_below_gate": True,

    # ── Logging ─────────────────────────────────────────────────────────────
    "log_level": "INFO",                   # one of DEBUG/INFO/WARNING/ERROR
    "log_retention_days": 30,

    # ── Cabin / passengers (single-fare collection) ─────────────────────────
    "cabin": "economy",
    "adults": 1,
    "currency": "INR",

    # ── Display timezone ─────────────────────────────────────────────────────
    # The IANA zone used to stamp human-facing columns (Scrape_Timestamp,
    # Booking_Day_Of_Week) AND to derive the travel dates we query / record
    # (Departure_Date, Day_of_Week, Is_Weekend_Departure). Set to the data's
    # frame of reference — Asia/Kolkata (IST, UTC+5:30) — so timestamps read in
    # local time WITHOUT requiring the host clock to be changed. A single
    # resolved zone is used for both the queried date and the recorded date, so
    # the two can never disagree across a UTC midnight boundary. Falls back to
    # UTC if the zone name can't be resolved (missing tzdata).
    "display_timezone": "Asia/Kolkata",
}


# ── Loader ──────────────────────────────────────────────────────────────────


@dataclass
class Config:
    """Resolved configuration. Treat instances as immutable."""

    cities: dict[str, str]
    days_out: list[int]
    batches: int
    data_dir: Path
    log_dir: Path
    state_dir: Path
    lock_file: Path
    target_runtime_seconds: int
    delay_min_seconds: float
    delay_max_seconds: float
    long_pause_every_routes: int
    long_pause_min_seconds: float
    long_pause_max_seconds: float
    max_attempts: int
    backoff_base_seconds: float
    backoff_max_seconds: float
    backoff_jitter_seconds: float
    api_timeout_seconds: int
    min_plausible_price_inr: float
    max_plausible_price_inr: float
    canary_route: tuple[str, str]
    canary_days_out: int
    canary_max_wait_seconds: float
    canary_probe_interval_seconds: float
    canary_attempts: int
    min_success_rate: float
    commit_below_gate: bool
    log_level: str
    log_retention_days: int
    cabin: str
    adults: int
    currency: str
    display_timezone: str
    # Resolved at load time — the root directory of the scraper install.
    base_dir: Path = field(default_factory=lambda: Path.cwd())

    @property
    def display_tz(self) -> tzinfo:
        """The resolved ``tzinfo`` for ``display_timezone`` (UTC on failure)."""
        return resolve_timezone(self.display_timezone)


def _coerce_env(raw: str, default: Any) -> Any:
    """Coerce a string env var to the type of its default."""
    if isinstance(default, bool):
        return raw.lower() in {"1", "true", "yes", "on"}
    if isinstance(default, int) and not isinstance(default, bool):
        return int(raw)
    if isinstance(default, float):
        return float(raw)
    if isinstance(default, list):
        # Allow CSV ("1,3,7,14,30,60") or JSON-ish lists.
        return [int(x) if x.strip().lstrip("-").isdigit() else x.strip()
                for x in raw.split(",") if x.strip()]
    return raw


def load(config_path: Path | str | None = None, base_dir: Path | None = None) -> Config:
    """Load YAML config (if present), overlay env overrides, return Config.

    Args:
        config_path: explicit YAML path; defaults to ``<base_dir>/config/scraper.yaml``.
        base_dir:    project root (``donotdelete/``). Defaults to cwd.
    """
    base = Path(base_dir or Path.cwd()).resolve()
    yaml_path = Path(config_path) if config_path else base / "config" / "scraper.yaml"

    merged: dict[str, Any] = dict(DEFAULTS)
    if yaml_path.is_file():
        with yaml_path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"{yaml_path}: top level must be a mapping, got {type(raw).__name__}")
        merged.update(raw)

    # Env-var overrides (SCRAPER_DELAY_MIN_SECONDS=20, etc.)
    for key in list(merged):
        env_key = f"SCRAPER_{key.upper()}"
        if env_key in os.environ:
            merged[key] = _coerce_env(os.environ[env_key], DEFAULTS.get(key, ""))

    # Resolve paths and validate.
    def _path(rel: str) -> Path:
        p = Path(rel)
        return p if p.is_absolute() else base / p

    canary_route = merged["canary_route"]
    if isinstance(canary_route, str):
        canary_route = [s.strip() for s in canary_route.split(",")]
    if len(canary_route) != 2:
        raise ValueError(f"canary_route must be [origin, destination], got {canary_route!r}")

    cfg = Config(
        cities=dict(merged["cities"]),
        days_out=list(merged["days_out"]),
        batches=int(merged["batches"]),
        data_dir=_path(merged["data_dir"]),
        log_dir=_path(merged["log_dir"]),
        state_dir=_path(merged["state_dir"]),
        lock_file=_path(merged["lock_file"]),
        target_runtime_seconds=int(merged["target_runtime_seconds"]),
        delay_min_seconds=float(merged["delay_min_seconds"]),
        delay_max_seconds=float(merged["delay_max_seconds"]),
        long_pause_every_routes=int(merged["long_pause_every_routes"]),
        long_pause_min_seconds=float(merged["long_pause_min_seconds"]),
        long_pause_max_seconds=float(merged["long_pause_max_seconds"]),
        max_attempts=int(merged["max_attempts"]),
        backoff_base_seconds=float(merged["backoff_base_seconds"]),
        backoff_max_seconds=float(merged["backoff_max_seconds"]),
        backoff_jitter_seconds=float(merged["backoff_jitter_seconds"]),
        api_timeout_seconds=int(merged["api_timeout_seconds"]),
        min_plausible_price_inr=float(merged["min_plausible_price_inr"]),
        max_plausible_price_inr=float(merged["max_plausible_price_inr"]),
        canary_route=(str(canary_route[0]), str(canary_route[1])),
        canary_days_out=int(merged["canary_days_out"]),
        canary_max_wait_seconds=float(merged["canary_max_wait_seconds"]),
        canary_probe_interval_seconds=float(merged["canary_probe_interval_seconds"]),
        canary_attempts=int(merged["canary_attempts"]),
        min_success_rate=float(merged["min_success_rate"]),
        commit_below_gate=bool(merged["commit_below_gate"]),
        log_level=str(merged["log_level"]).upper(),
        log_retention_days=int(merged["log_retention_days"]),
        cabin=str(merged["cabin"]),
        adults=int(merged["adults"]),
        currency=str(merged["currency"]),
        display_timezone=str(merged["display_timezone"]),
        base_dir=base,
    )

    # Sanity bounds — catch nonsense config before the run starts.
    if cfg.delay_min_seconds < 0 or cfg.delay_max_seconds < cfg.delay_min_seconds:
        raise ValueError("delay_min_seconds ≤ delay_max_seconds and both ≥ 0")
    if cfg.max_attempts < 1:
        raise ValueError("max_attempts must be ≥ 1")
    if not (0.0 <= cfg.min_success_rate <= 1.0):
        raise ValueError("min_success_rate must be in [0, 1]")
    if cfg.min_plausible_price_inr <= 0 or cfg.max_plausible_price_inr <= cfg.min_plausible_price_inr:
        raise ValueError("0 < min_plausible_price_inr < max_plausible_price_inr required")
    return cfg
