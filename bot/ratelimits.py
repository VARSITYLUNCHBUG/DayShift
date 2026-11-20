"""Compatibility fix for discord.py 2.7's long-window wait cap.

Upstream rejects acquire() when the reset is distant, even when tokens remain. Keep its
HTTP 429 handling and actual quotas, but apply the wait cap only to an exhausted bucket.
This uses discord.py internals; regression tests cover the pinned dependency's behavior.
"""

from __future__ import annotations

import asyncio
import contextlib
from types import MethodType, TracebackType

from discord import RateLimited
from discord.http import HTTPClient, Ratelimit


class QuotaAwareRatelimit(Ratelimit):
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
        delay = max(0.0, self.expires - self._loop.time()) if self.expires else self.reset_after
        if self._max_ratelimit_timeout is not None and delay > self._max_ratelimit_timeout:
            self._wake(len(self._pending_requests), exception=RateLimited(delay))
            return  # Preserve zero remaining and its expiry: do not reset quota early.
        async with self._sleeping:
            await asyncio.sleep(delay)
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
