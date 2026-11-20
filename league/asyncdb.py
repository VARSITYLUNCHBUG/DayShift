"""The one async-to-sync boundary. Services stay synchronous because Django has no async atomic().

Every database call runs on one shared thread, which keeps transactions simple at this scale.
A long-lived process must also retire stale connections itself; Django only does that for you
inside the request cycle.

The bot and the web process both call services through here, so it lives outside `bot/`.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from asgiref.sync import sync_to_async
from django.db import close_old_connections

from league import timings

logger = logging.getLogger(__name__)

# A call that ran longer than this is logged on its own, with its name. Its wait for the thread
# doesn't count: that is the call ahead of it being slow, and that one is logged itself.
SLOW_SECONDS = 0.5


def _name(fn: Callable[..., Any]) -> str:
    module = getattr(fn, "__module__", "") or ""
    return f"{module.rsplit('.', 1)[-1]}.{getattr(fn, '__qualname__', repr(fn))}"


async def db[**P, T](fn: Callable[P, T], /, *args: P.args, **kwargs: P.kwargs) -> T:
    """Run `fn` on the database thread. Times the wait for the thread and the call itself
    (`league.timings`: `db.wait`, `db.run`), since every call shares that one thread.

    Both are taken on the thread: `db.run` ends when the call does, so the event loop's delay in
    picking the result up is neither, and a slow loop isn't mistaken for a slow query."""
    submitted = time.perf_counter()
    started: float | None = None
    finished: float | None = None

    def call() -> T:
        nonlocal started, finished
        started = time.perf_counter()
        close_old_connections()
        try:
            return fn(*args, **kwargs)
        finally:
            close_old_connections()
            finished = time.perf_counter()

    wrapped: Callable[[], Any] = sync_to_async(call, thread_sensitive=True)
    try:
        return await wrapped()
    finally:
        if started is not None and finished is not None:
            _record(fn, started - submitted, finished - started)


def _record(fn: Callable[..., Any], wait: float, run: float) -> None:
    """One call's times, and a warning for a slow one. A call cancelled before the thread got
    to it ran nothing, so it isn't recorded."""
    timings.record("db.wait", wait)
    timings.record("db.run", run)
    if run > SLOW_SECONDS:
        logger.warning(
            "Slow database call",
            extra={
                "call": _name(fn),
                "wait_ms": round(wait * 1000),
                "run_ms": round(run * 1000),
            },
        )
