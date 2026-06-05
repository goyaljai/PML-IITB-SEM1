"""
Global SSE broadcaster. Import `notify` anywhere and call it to push
an update to all connected clients.
"""
import asyncio
from typing import Set

_queues: Set[asyncio.Queue] = set()


_loop = None

def set_loop(loop):
    global _loop
    _loop = loop

def notify():
    """Push a refresh signal to all connected SSE clients (fire-and-forget)."""
    async def _do_notify():
        dead = set()
        for q in _queues:
            try:
                q.put_nowait("refresh")
            except asyncio.QueueFull:
                dead.add(q)
        _queues.difference_update(dead)
    
    if _loop is not None:
        try:
            asyncio.run_coroutine_threadsafe(_do_notify(), _loop)
        except Exception:
            pass



def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=10)
    _queues.add(q)
    return q


def unsubscribe(q: asyncio.Queue):
    _queues.discard(q)
