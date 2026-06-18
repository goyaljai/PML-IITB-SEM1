"""
Shared pytest fixtures.

Importantly we make ``sys.path`` include ``donotdelete/`` so ``from scraper
import …`` works whether pytest is launched from the repo root or from
``donotdelete/``. This matches how the real cron invokes the package.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure ``donotdelete/`` is importable regardless of pytest's cwd.
_HERE = Path(__file__).resolve()
_DONOTDELETE = _HERE.parent.parent
sys.path.insert(0, str(_DONOTDELETE))

import pytest  # noqa: E402  (must come after sys.path tweak)


@pytest.fixture()
def tmp_base(tmp_path: Path) -> Path:
    """A throwaway base dir laid out like the real ``donotdelete/`` tree."""
    for sub in ("data", "logs", "config", "state"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.fixture()
def fake_config(tmp_base: Path):
    """A minimal Config that points at the throwaway dirs."""
    from scraper.config import Config
    return Config(
        cities={"Mumbai": "BOM", "Delhi": "DEL", "Bengaluru": "BLR"},
        days_out=[1, 3],
        batches=3,
        data_dir=tmp_base / "data",
        log_dir=tmp_base / "logs",
        state_dir=tmp_base / "data",
        lock_file=tmp_base / ".lock",
        target_runtime_seconds=60,
        delay_min_seconds=0,
        delay_max_seconds=0,
        long_pause_every_routes=0,
        long_pause_min_seconds=0,
        long_pause_max_seconds=0,
        max_attempts=2,
        backoff_base_seconds=0.0,
        backoff_max_seconds=0.0,
        backoff_jitter_seconds=0.0,
        api_timeout_seconds=5,
        min_plausible_price_inr=1000,
        max_plausible_price_inr=200000,
        canary_route=("BOM", "DEL"),
        canary_days_out=7,
        canary_max_wait_seconds=1,
        canary_probe_interval_seconds=0,
        canary_attempts=1,
        min_success_rate=0.5,
        log_level="WARNING",
        log_retention_days=1,
        cabin="economy",
        adults=1,
        currency="INR",
        base_dir=tmp_base,
    )
