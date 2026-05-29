"""
Global SSE broadcaster. Import `notify` anywhere and call it to push
an update to all connected clients.
"""
import asyncio
from typing import Set

_queues: Set[asyncio.Queue] = set()


def notify():
    """Push a refresh signal to all connected SSE clients (fire-and-forget)."""
    dead = set()
    for q in _queues:
        try:
            q.put_nowait("refresh")
        except asyncio.QueueFull:
            dead.add(q)
    _queues.difference_update(dead)


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=10)
    _queues.add(q)
    return q


def unsubscribe(q: asyncio.Queue):
    _queues.discard(q)
