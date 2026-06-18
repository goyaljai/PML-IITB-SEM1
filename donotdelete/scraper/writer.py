"""
CSV writer — append-only, monthly partitioned.

Each row is written individually so the on-disk dataset is *always* a consistent
prefix of what was scraped: a SIGKILL between rows leaves the file with N
complete records, never a half-line. The file is opened, the row written,
``flush`` + ``fsync`` called, file closed — every time. That's slow (a syscall
per write) but the scraper does at most a few thousand rows per day, so the
cost is irrelevant next to network latency.

Monthly partitioning (``flights_YYYY_MM.csv``) caps any single file's growth
to ~1 MB/month — small enough that ``git diff``, ``pd.read_csv``, and LFS
chunk handling all stay snappy after a year.
"""

from __future__ import annotations

import csv
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping

from .schema import CSV_HEADERS


def monthly_path(data_dir: Path, when: datetime | None = None) -> Path:
    """Return the canonical CSV path for the month containing ``when`` (UTC).

    Defaults to "right now". Centralized so tests can swap in a fixed datetime.
    """
    if when is None:
        when = datetime.now(timezone.utc)
    return Path(data_dir) / f"flights_{when:%Y_%m}.csv"


def ensure_file(path: Path) -> None:
    """Create the CSV (with header row) if it does not already exist.

    Idempotent: a no-op when the file is present. Creates parent directories
    if needed.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return
    # Open with newline="" per the csv module docs to prevent extra blank lines
    # on Windows; harmless on POSIX. The header row is always exactly the
    # canonical order of CSV_HEADERS.
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(CSV_HEADERS))
        writer.writeheader()
        f.flush()
        os.fsync(f.fileno())


def append_rows(path: Path, rows: Iterable[Mapping[str, object]]) -> int:
    """Append validated rows to ``path``. Returns the number of rows written.

    Each row is fsynced individually so a crash between rows leaves the file
    in a consistent state (N complete rows, no partial line).
    """
    path = Path(path)
    ensure_file(path)
    n = 0
    with open(path, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(CSV_HEADERS))
        for row in rows:
            writer.writerow({h: ("" if row.get(h) is None else row.get(h)) for h in CSV_HEADERS})
            f.flush()
            os.fsync(f.fileno())
            n += 1
    return n
