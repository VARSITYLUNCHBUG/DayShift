"""Counts the Discord requests that Discord counts against us.

Cloudflare bans an IP for a while once it makes 10,000 failed requests (401, 403 and 429) in ten
minutes. A 429 with `X-RateLimit-Scope: shared` doesn't count. Every response passes through an
aiohttp trace, so this sees them all, interactions and discord.py's own retries included.

The count is logged every ten minutes when it isn't zero, and an error goes to the server's error
channel (through the error log handler) once it passes WARN_AT, far below the ban.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

WINDOW_SECONDS = 600.0
WARN_AT = 1000
COUNTED = frozenset({401, 403})


class FailedRequests:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._times: deque[float] = deque()
        self._warned_at: float | None = None

    def _prune(self, moment: float) -> None:
        while self._times and moment - self._times[0] > WINDOW_SECONDS:
            self._times.popleft()

    def record(self, status: int, scope: str | None = None) -> None:
        if status not in COUNTED and not (status == 429 and scope != "shared"):
            return
        moment = self._clock()
        self._times.append(moment)
        self._prune(moment)
        if len(self._times) >= WARN_AT and (
            self._warned_at is None or moment - self._warned_at > WINDOW_SECONDS
        ):
            self._warned_at = moment
            logger.error(
                "Discord is refusing many requests: %s in the last 10 minutes. Discord bans the"
                " bot's IP for a while at 10,000.",
                len(self._times),
                extra={"failed_requests": len(self._times)},
            )

    def count(self) -> int:
        self._prune(self._clock())
        return len(self._times)

    def trace_config(self) -> aiohttp.TraceConfig:
        trace = aiohttp.TraceConfig()

        async def on_request_end(
            _session: aiohttp.ClientSession, _context: SimpleNamespace, params: Any
        ) -> None:
            response = params.response
            self.record(response.status, response.headers.get("X-RateLimit-Scope"))

        trace.on_request_end.append(on_request_end)
        return trace

    def log_summary(self) -> None:
        """The ten-minute count, when there's anything to say."""
        if failed := self.count():
            logger.info(
                "Failed Discord requests in the last 10 minutes",
                extra={"failed_requests": failed},
            )
