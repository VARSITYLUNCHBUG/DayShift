"""Database calls from the websocket, on threads of their own.

`league.asyncdb.db` runs everything on Django's one sync thread, which the web's ordinary views
also use. Snapshot rebuilds come in bursts (one change can refresh a dozen pages), so they get a
separate pool sized by `WEB_DB_THREADS` and can't hold up a sign-in or an upload. Each thread
keeps its own connection, retired around every call as `db()` does.
"""

from __future__ import annotations

import asyncio
import functools
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from django.conf import settings
from django.db import close_old_connections, connections

_pool: ThreadPoolExecutor | None = None
_lock = threading.Lock()


def _executor() -> ThreadPoolExecutor:
    global _pool
    with _lock:
        if _pool is None:
            _pool = ThreadPoolExecutor(
                max_workers=settings.WEB_DB_THREADS, thread_name_prefix="web-db"
            )
        return _pool


async def web_db[**P, T](fn: Callable[P, T], /, *args: P.args, **kwargs: P.kwargs) -> T:
    def call() -> T:
        close_old_connections()
        try:
            return fn(*args, **kwargs)
        finally:
            close_old_connections()

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor(), functools.partial(call))


def shutdown() -> None:
    """Stop the pool and close every thread's connection. Tests call this, so a test database
    isn't left with open sessions; the process never needs to."""
    global _pool
    with _lock:
        pool, _pool = _pool, None
    if pool is None:
        return
    # One task per thread: each waits for the others, so no thread can take two of them.
    size = pool._max_workers
    barrier = threading.Barrier(size)

    def close() -> None:
        connections.close_all()
        barrier.wait(timeout=10)

    for _ in range(size):
        pool.submit(close)
    pool.shutdown(wait=True)
