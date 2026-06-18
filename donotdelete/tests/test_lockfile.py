"""File-lock semantics."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from scraper import lockfile


def test_acquire_release_round_trip(tmp_path):
    p = tmp_path / ".lock"
    with lockfile.acquire(p):
        assert p.exists()
        # Breadcrumb contains the holder pid.
        text = p.read_text(encoding="utf-8")
        assert text.startswith(f"{os.getpid()} ")


def test_second_acquire_in_same_process_succeeds_after_release(tmp_path):
    p = tmp_path / ".lock"
    with lockfile.acquire(p):
        pass
    # No lingering process holding it.
    with lockfile.acquire(p):
        pass


def test_second_acquire_from_a_subprocess_busy(tmp_path):
    """The lock must block ACROSS PROCESSES, not just within."""
    p = tmp_path / ".lock"
    # Helper script: acquire the lock and sleep so the parent can try.
    helper = tmp_path / "hold.py"
    helper.write_text(textwrap.dedent(f"""
        import sys, time
        sys.path.insert(0, {str(Path(__file__).resolve().parent.parent)!r})
        from scraper import lockfile
        from pathlib import Path
        with lockfile.acquire(Path({str(p)!r})):
            print("HELD", flush=True)
            time.sleep(2)
    """))
    proc = subprocess.Popen(
        [sys.executable, str(helper)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        # Wait for the child to take the lock.
        ready = False
        for _ in range(40):
            if proc.poll() is not None:
                break
            line = proc.stdout.readline() if proc.stdout else ""  # type: ignore[union-attr]
            if line.startswith("HELD"):
                ready = True
                break
            time.sleep(0.05)
        assert ready, "child never reported HELD"

        with pytest.raises(lockfile.LockBusy):
            with lockfile.acquire(p):
                pass
    finally:
        proc.wait(timeout=5)


def test_lock_is_released_on_process_death(tmp_path):
    """SIGKILL on the holder should make the lock immediately re-acquirable."""
    p = tmp_path / ".lock"
    helper = tmp_path / "hold_forever.py"
    helper.write_text(textwrap.dedent(f"""
        import sys, time
        sys.path.insert(0, {str(Path(__file__).resolve().parent.parent)!r})
        from scraper import lockfile
        from pathlib import Path
        with lockfile.acquire(Path({str(p)!r})):
            print("HELD", flush=True)
            time.sleep(30)
    """))
    proc = subprocess.Popen(
        [sys.executable, str(helper)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        for _ in range(40):
            line = proc.stdout.readline() if proc.stdout else ""  # type: ignore[union-attr]
            if line.startswith("HELD"):
                break
            time.sleep(0.05)
        # Confirm we cannot acquire while the child holds.
        with pytest.raises(lockfile.LockBusy):
            with lockfile.acquire(p):
                pass
        # Now SIGKILL the child.
        proc.kill()
        proc.wait(timeout=5)
        # The kernel should have released the advisory lock — re-acquire works.
        with lockfile.acquire(p):
            pass
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
