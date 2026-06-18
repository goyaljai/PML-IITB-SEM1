"""
Structured logging for the scraper.

Two outputs by default:
  * stderr — for ``cron``/``systemd`` to capture into MAILTO / journal.
  * ``logs/scraper-YYYY-MM-DD.log`` — daily-rotating, retained for
    ``log_retention_days`` (default 30) so a year-long unattended deployment
    doesn't fill the disk.

The format is grep-friendly: ISO-8601 timestamp, level, logger name, then
message. The ``Run_Id`` (UTC stamp) is attached as a ``extra={"run_id": ...}``
field via a filter so it appears on every line — useful when correlating logs
with rows in the CSV (which carry the same Run_Id).
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path

LOG_FORMAT = (
    "[%(asctime)s.%(msecs)03dZ] "
    "[%(levelname)-5s] "
    "[%(name)-12s] "
    "[run=%(run_id)s] "
    "%(message)s"
)
DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"


class _RunIdFilter(logging.Filter):
    """Inject the active run id into every record (falls back to ``-``)."""

    def __init__(self, run_id: str) -> None:
        super().__init__()
        self.run_id = run_id

    def filter(self, record: logging.LogRecord) -> bool:  # type: ignore[override]
        if not hasattr(record, "run_id"):
            record.run_id = self.run_id
        return True


def setup(
    log_dir: Path,
    level: str = "INFO",
    run_id: str = "-",
    retention_days: int = 30,
) -> logging.Logger:
    """Configure the root logger for the scraper process.

    Safe to call once per process. Subsequent calls are no-ops (we detect
    existing handlers via a tag on the logger).
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Avoid duplicate handlers on re-import / re-entry.
    if getattr(root, "_scraper_configured", False):
        return root

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
    formatter.converter = _utc_struct_time  # type: ignore[assignment]

    # ── stderr handler ────────────────────────────────────────────────────
    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(formatter)
    stream.addFilter(_RunIdFilter(run_id))
    root.addHandler(stream)

    # ── rotating file handler ─────────────────────────────────────────────
    log_path = log_dir / "scraper.log"
    file_handler = logging.handlers.TimedRotatingFileHandler(
        filename=log_path,
        when="midnight",
        interval=1,
        backupCount=max(retention_days, 1),
        utc=True,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.addFilter(_RunIdFilter(run_id))
    # Suffix becomes scraper.log.YYYY-MM-DD after rotation.
    file_handler.suffix = "%Y-%m-%d"
    root.addHandler(file_handler)

    root._scraper_configured = True  # type: ignore[attr-defined]
    root.debug("Logging configured: dir=%s level=%s retention=%dd", log_dir, level, retention_days)
    return root


def _utc_struct_time(timestamp: float) -> "os.times_result":  # type: ignore[name-defined]
    """Convert seconds-since-epoch to a UTC struct_time (logger formatter hook)."""
    import time
    return time.gmtime(timestamp)


def get(name: str) -> logging.Logger:
    """Convenience wrapper to keep logger names short and consistent."""
    return logging.getLogger(name)
