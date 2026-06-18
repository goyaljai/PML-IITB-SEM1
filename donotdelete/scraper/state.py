"""
Per-run state — currently just the ``Run_Id`` generator.

The Run_Id is a UTC stamp like ``20260618T030000Z`` that appears in every CSV
row produced by a single cron invocation. It correlates rows with log lines
and with the lock-file breadcrumb, which makes post-hoc debugging easy ("what
went wrong on the 2026-06-18 03:00 run?").
"""

from __future__ import annotations

from datetime import datetime, timezone


def new_run_id(now: datetime | None = None) -> str:
    """Compact, sortable UTC timestamp suitable for filenames and grep."""
    when = now or datetime.now(timezone.utc)
    return when.strftime("%Y%m%dT%H%M%SZ")
