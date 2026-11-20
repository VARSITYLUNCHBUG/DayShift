"""The web process's one LISTEN connection: hears what changed and tells the hub.

A notification carries only a topic (`league.services.live`). If the connection drops, every
notification sent meanwhile is lost, so after each (re)connect the hub rebuilds everything it
serves. The first connect counts too: changes made before LISTEN took hold were never heard.

The connection runs on a thread with its own selector event loop. psycopg's async mode can't use
the Proactor loop uvicorn runs on Windows, and on its own thread a burst of snapshot work on the
main loop can't hold up reading notifications either.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable
from contextlib import suppress
from typing import Any

import psycopg
from django.db import connection

from league.services import live

logger = logging.getLogger(__name__)

BACKOFF_START = 0.5  # Seconds before the first reconnect; doubles up to BACKOFF_MAX.
BACKOFF_MAX = 10.0
# With nothing heard for this long, check the connection is still there: a dropped network
# otherwise looks exactly like a quiet league.
IDLE_CHECK = 30.0

# Django's own OPTIONS, which psycopg doesn't understand.
_DJANGO_OPTIONS = frozenset({"pool", "isolation_level", "server_side_binding", "assume_role"})


def connect_params() -> dict[str, Any]:
    """psycopg connection arguments for the database Django uses."""
    settings = connection.settings_dict
    params: dict[str, Any] = {
        "host": settings["HOST"],
        "port": settings["PORT"],
        "dbname": settings["NAME"],
        "user": settings["USER"],
        "password": settings["PASSWORD"],
    }
    params = {key: value for key, value in params.items() if value}
    options = settings.get("OPTIONS") or {}
    params.update({key: value for key, value in options.items() if key not in _DJANGO_OPTIONS})
    params.setdefault("application_name", "dayshift web listener")
    params.setdefault("connect_timeout", 10)
    return params


class Listener:
    def __init__(
        self,
        on_topic: Callable[[str], None],
        on_connect: Callable[[], None],
        params: dict[str, Any],
    ) -> None:
        # Both callbacks run on the listener's thread; they hand over to the hub's loop.
        self._on_topic = on_topic
        self._on_connect = on_connect
        self._params = params
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task[None] | None = None
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._main, name="web-listen", daemon=True)
        self.backend_pid: int | None = None  # The LISTEN session's pid while connected.

    def start(self) -> None:
        self._thread.start()
        self._ready.wait(timeout=5)

    def stop(self, timeout: float = 5.0) -> None:
        loop, task = self._loop, self._task
        if loop is not None and task is not None:
            with suppress(RuntimeError):  # The loop already finished.
                loop.call_soon_threadsafe(task.cancel)
        if self._thread.is_alive():
            self._thread.join(timeout)

    def _main(self) -> None:
        asyncio.run(self._started(), loop_factory=asyncio.SelectorEventLoop)

    async def _started(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._task = asyncio.current_task()
        self._ready.set()
        with suppress(asyncio.CancelledError):
            await self._run()

    async def _run(self) -> None:
        delay = BACKOFF_START
        while True:
            try:
                await self._listen()
            except (psycopg.Error, OSError) as error:
                logger.warning("The live listener lost its connection: %s", error)
            except Exception:
                logger.exception("The live listener failed; it will reconnect.")
            if self.backend_pid is not None:
                # It had been listening: start the backoff over.
                self.backend_pid = None
                delay = BACKOFF_START
            await asyncio.sleep(delay)
            delay = min(delay * 2, BACKOFF_MAX)

    async def _listen(self) -> None:
        conn = await psycopg.AsyncConnection.connect(autocommit=True, **self._params)
        try:
            await conn.execute(f"LISTEN {live.CHANNEL}")
            self.backend_pid = conn.info.backend_pid
            logger.info("The live listener is listening.")
            self._on_connect()
            while True:
                async for notify in conn.notifies(timeout=IDLE_CHECK):
                    self._on_topic(notify.payload)
                await conn.execute("SELECT 1")
        finally:
            await conn.close()


_current: Listener | None = None
_lock = threading.Lock()


def start(on_topic: Callable[[str], None], on_connect: Callable[[], None]) -> Listener:
    """Start the process's listener, replacing any earlier one."""
    global _current
    listener = Listener(on_topic, on_connect, connect_params())
    with _lock:
        previous, _current = _current, listener
    if previous is not None:
        previous.stop()
    listener.start()
    return listener


def stop() -> None:
    """Stop the listener and close its connection. For tests and shutdown."""
    global _current
    with _lock:
        listener, _current = _current, None
    if listener is not None:
        listener.stop()


def current() -> Listener | None:
    return _current
