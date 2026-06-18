"""
Cross-process file lock for the scraper.

Why a lock at all? The cron runs once a day at a fixed hour, but operators
will run the scraper by hand for ad-hoc collection or smoke tests, and two
concurrent runs would (a) write interleaved rows into the same monthly CSV
and (b) double-charge the rotation counter. The lock makes "second run
detects first is in progress and exits" the deterministic behaviour.

Implementation: a hold-file opened in append mode with an advisory
``fcntl.flock(LOCK_EX | LOCK_NB)``. The kernel releases the lock automatically
when the file descriptor closes — including on `kill -9` and OOMs — so there
is no PID-management or stale-lock cleanup needed.

The lock file's contents are a single line of debug metadata:
``<pid> <iso-utc> <hostname>``. It's there for ``ps``/``ls`` ergonomics, NOT
for ownership logic — that's the OS's job.
"""

from __future__ import annotations

import fcntl
import os
import socket
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Generator


class LockBusy(RuntimeError):
    """Raised when another process already holds the lock."""


@contextmanager
def acquire(path: Path) -> Generator[Path, None, None]:
    """Hold an exclusive lock on ``path`` for the duration of the ``with`` block.

    On contention raises ``LockBusy`` immediately (no wait/poll — daily cron
    should not stack runs). On entry writes a small breadcrumb into the file
    so an operator inspecting it knows which run is holding it.

    The directory is created if missing; the file persists between runs (it's
    the lock target, not run state).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o640)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            # Try to read who's holding it for a friendly error message.
            try:
                with open(path, "r", encoding="utf-8") as f:
                    held_by = f.read().strip()
            except OSError:
                held_by = "<unknown>"
            raise LockBusy(
                f"another scraper run is already in progress (lock={path}, holder={held_by})"
            ) from e

        # Write breadcrumb — truncate first so we don't keep appending across runs.
        os.ftruncate(fd, 0)
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        breadcrumb = f"{os.getpid()} {stamp} {socket.gethostname()}\n"
        os.write(fd, breadcrumb.encode("utf-8"))
        os.fsync(fd)

        yield path

    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(fd)
