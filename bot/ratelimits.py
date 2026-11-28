"""Fixes to discord.py 2.7's rate limiting, and a cap on the bot's overall request rate.

- Upstream rejects acquire() when the reset is distant, even when tokens remain. Keep its
  HTTP 429 handling and actual quotas, but apply the wait cap only to an exhausted bucket.
- Upstream treats a bucket whose window has ended as full again, and lets every waiting request
  go at once. Discord's buckets refill gradually, so a burst like that draws 429s (seen in the
  load test: twelve results posts reading the archive at once). After a reset only one request
  goes; its response says how many more may follow.
- `GlobalPace` keeps bot-token requests under Discord's 50 a second for the whole process, which
  discord.py only reacts to after a global 429. A load test of twelve matches at once peaked at 53.

These use discord.py internals; regression tests cover the pinned dependency's behavior.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections import deque
from collections.abc import Awaitable, Callable
from types import MethodType, TracebackType
from typing import Any
from urllib.parse import urlsplit

from discord import RateLimited
from discord.http import HTTPClient, Ratelimit


class QuotaAwareRatelimit(Ratelimit):
    def reset(self) -> None:
        """The window has ended. Discord may have refilled only part of the bucket, so one
        request probes it, and its response's headers set how many more may go."""
        super().reset()
        self.remaining = min(self.remaining, 1)

    async def acquire(self) -> None:
        self._last_request = self._loop.time()
        if self.is_expired():
            self.reset()

        while self.remaining <= 0:
            if self.is_expired():
                self.reset()
                continue
            delay = max(0.0, self.expires - self._loop.time()) if self.expires else None
            if (
                self._max_ratelimit_timeout is not None
                and delay is not None
                and delay > self._max_ratelimit_timeout
            ):
                raise RateLimited(delay)

            future = self._loop.create_future()
            self._pending_requests.append(future)
            try:
                while not future.done():
                    wait = max(0.0, self.expires - self._loop.time()) if self.expires else 30.0
                    await asyncio.wait([future], timeout=wait)
                    if not future.done():
                        await self._refresh()
                # asyncio.wait only signals completion. It doesn't retrieve the result or
                # propagate RateLimited from _refresh, so explicitly consume the wake-up.
                future.result()
            except BaseException:
                if not future.done():
                    future.cancel()
                elif not future.cancelled():
                    future.exception()  # Also consume a wake-up racing with cancellation.
                if self.remaining > 0:
                    self._wake_next()
                raise
            finally:
                with contextlib.suppress(ValueError):  # _wake may already have removed it.
                    self._pending_requests.remove(future)

        self.remaining -= 1
        self.outgoing += 1

    async def _refresh(self) -> None:
        if self.remaining > 0:
            # A long reset window is not a reason to discard usable quota, but the quota is
            # free now: hand it to whoever is already waiting, or they'd wait on a timeout.
            self._wake(self.remaining)
            return
        if self.expires is None and self.outgoing:
            return  # A request is out probing the bucket; its response wakes the rest.
        delay = max(0.0, self.expires - self._loop.time()) if self.expires else self.reset_after
        if self._max_ratelimit_timeout is not None and delay > self._max_ratelimit_timeout:
            self._wake(len(self._pending_requests), exception=RateLimited(delay))
            return  # Preserve zero remaining and its expiry: do not reset quota early.
        async with self._sleeping:
            await asyncio.sleep(delay)
        if self.expires is None and (self.outgoing or self.remaining > 0):
            # Another waiter reset the bucket while this one waited for the lock.
            if self.remaining > 0:
                self._wake(self.remaining)
            return
        self.reset()
        self._wake(self.remaining)

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.outgoing -= 1
        tokens = self.remaining - self.outgoing
        if not self._sleeping.locked():
            if tokens <= 0:
                await self._refresh()
            elif self._pending_requests:
                self._wake(tokens)  # Available tokens do not require a rate-limit wait.


# Discord allows 50 a second. A little under leaves room for discord.py's own retries and for
# Discord counting the second differently from us.
GLOBAL_PER_SECOND = 40


def counts_globally(url: Any) -> bool:
    """Interaction responses and webhook calls don't count towards the 50 a second."""
    path = urlsplit(str(url)).path
    return "/interactions/" not in path and "/webhooks/" not in path


class GlobalPace:
    """At most `per_second` bot-token requests in any rolling second, for the whole process.
    Awaited just before each request goes out (the aiohttp trace's request start), so retries
    count and a request waiting on its own bucket holds no slot."""

    def __init__(
        self,
        per_second: int = GLOBAL_PER_SECOND,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    ) -> None:
        self.per_second = per_second
        self._clock = clock
        self._sleep = sleep
        self._sent: deque[float] = deque()
        self._lock = asyncio.Lock()
        self.delayed = 0  # Requests held back since the last look, for the usage summary.

    async def wait(self, url: Any) -> None:
        if not counts_globally(url):
            return
        async with self._lock:
            held = False
            while True:
                moment = self._clock()
                while self._sent and moment - self._sent[0] >= 1.0:
                    self._sent.popleft()
                if len(self._sent) < self.per_second:
                    self._sent.append(moment)
                    self.delayed += held
                    return
                held = True
                await self._sleep(1.0 - (moment - self._sent[0]))

    def take_delayed(self) -> int:
        """How many requests waited for the pace since the last call."""
        delayed, self.delayed = self.delayed, 0
        return delayed


def _get_ratelimit(http: HTTPClient, key: str) -> Ratelimit:
    if key not in http._buckets:
        http._buckets[key] = QuotaAwareRatelimit(http.max_ratelimit_timeout)
        http._try_clear_expired_ratelimits()
    return http._buckets[key]


def install(http: HTTPClient) -> None:
    """Replace only this bot's bucket factory, before it has logged in or made requests."""
    if http._buckets:
        raise RuntimeError("Install rate-limit compatibility before connecting to Discord")
    http.get_ratelimit = MethodType(_get_ratelimit, http)  # type: ignore[method-assign]
