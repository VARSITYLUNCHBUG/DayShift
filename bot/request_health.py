"""Counts the Discord requests that Discord counts against us.

Cloudflare bans an IP for a while once it makes 10,000 failed requests (401, 403 and 429) in ten
minutes. A 429 with `X-RateLimit-Scope: shared` doesn't count. Every response passes through an
aiohttp trace, so this sees them all, interactions and discord.py's own retries included.

The invalid count is logged every ten minutes when it isn't zero, and an error goes to the
server's error channel once it passes WARN_AT. Every minute, request totals by method, route and
status are logged with the last observed rate-limit headers. These are observations, not a
live quota: Discord has separate buckets and may impose additional resource limits.
"""

from __future__ import annotations

import logging
import re
import time
from collections import Counter, deque
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlsplit

import aiohttp

from league import timings

logger = logging.getLogger(__name__)

WINDOW_SECONDS = 600.0
WARN_AT = 1000
COUNTED = frozenset({401, 403})


def request_route(url: Any) -> str:
    """Group IDs without logging interaction/webhook tokens, invite codes or query strings."""
    parts = re.sub(r"^/api(?:/v\d+)?/", "/", urlsplit(str(url)).path).strip("/").split("/")
    if parts[0] in {"interactions", "webhooks"} and len(parts) > 2:
        parts[2] = ":token"
    if parts[0] == "invites" and len(parts) > 1:
        parts[1] = ":code"
    return "/" + "/".join(":id" if part.isdecimal() else part for part in parts)


class FailedRequests:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._times: deque[float] = deque()
        self._warned_at: float | None = None
        self._usage_since = clock()
        self._requests: Counter[tuple[str, str, int]] = Counter()
        self._buckets: dict[tuple[str, str], dict[str, Any]] = {}
        self._network_errors: Counter[tuple[str, str, str]] = Counter()

    def response(self, method: str, url: Any, status: int, headers: Any) -> None:
        """Record actual HTTP responses, including discord.py's retry attempts."""
        route = request_route(url)
        self._requests[method, route, status] += 1
        self.record(status, headers.get("X-RateLimit-Scope"))
        details = {
            "method": method,
            "route": route,
            "status": status,
            "bucket": headers.get("X-RateLimit-Bucket"),
            "limit": headers.get("X-RateLimit-Limit"),
            "remaining": headers.get("X-RateLimit-Remaining"),
            "reset_after_seconds": headers.get("X-RateLimit-Reset-After"),
            "retry_after_seconds": headers.get("Retry-After"),
            "scope": headers.get("X-RateLimit-Scope"),
            "global_limit": headers.get("X-RateLimit-Global"),
        }
        if details["bucket"] is not None:
            # The last observed response for this route, not a live quota or a global limit.
            self._buckets[method, route] = details
        if status == 429:
            logger.warning("Discord request rate limited", extra=details)
        elif details["remaining"] == "0":
            # Routine for small buckets; the minute's usage summary carries the headers.
            logger.debug("Discord rate limit bucket exhausted", extra=details)
        else:
            logger.debug("Discord request completed", extra=details)

    def log_usage_summary(self) -> None:
        """Requests per route in this interval, with the last observed bucket headers."""
        moment = self._clock()
        if self._requests or self._network_errors:
            logger.info(
                "Discord API usage",
                extra={
                    "window_seconds": round(moment - self._usage_since, 1),
                    "requests": sum(self._requests.values()),
                    "routes": [
                        {"method": method, "route": route, "status": status, "count": count}
                        for (method, route, status), count in sorted(self._requests.items())
                    ],
                    "last_observed_buckets": list(self._buckets.values()),
                    "network_errors": [
                        {"method": method, "route": route, "error": error, "count": count}
                        for (method, route, error), count in sorted(self._network_errors.items())
                    ],
                    "invalid_requests_10m": self.count(),
                },
            )
        self._requests.clear()
        self._buckets.clear()
        self._network_errors.clear()
        self._usage_since = moment

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

        async def on_request_start(
            _session: aiohttp.ClientSession, context: SimpleNamespace, _params: Any
        ) -> None:
            context.started = time.perf_counter()

        async def on_request_end(
            _session: aiohttp.ClientSession, context: SimpleNamespace, params: Any
        ) -> None:
            response = params.response
            if response.status == 101:
                return  # The gateway's WebSocket upgrade isn't a REST rate-limit request.
            self.response(params.method, params.url, response.status, response.headers)
            started = getattr(context, "started", None)
            if started is not None:
                # Each attempt on the wire, not discord.py's waits for a rate limit between them.
                timings.record("discord.request", time.perf_counter() - started)

        async def on_request_exception(
            _session: aiohttp.ClientSession, _context: SimpleNamespace, params: Any
        ) -> None:
            self._network_errors[
                params.method, request_route(params.url), type(params.exception).__name__
            ] += 1

        trace.on_request_start.append(on_request_start)
        trace.on_request_end.append(on_request_end)
        trace.on_request_exception.append(on_request_exception)
        return trace

    def log_summary(self) -> None:
        """The ten-minute count, when there's anything to say."""
        if failed := self.count():
            logger.info(
                "Failed Discord requests in the last 10 minutes",
                extra={"failed_requests": failed},
            )
