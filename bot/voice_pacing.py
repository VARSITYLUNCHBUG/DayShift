"""Conservative per-server spacing for voice changes, separate from text requests.

These are application pacing choices, not Discord quotas. discord.py still handles the
actual rate-limit headers, and an API cooldown can be much longer than these intervals.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable


class VoicePacer:
    def __init__(
        self,
        create_interval: float = 5.0,
        action_interval: float = 1.0,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.create_interval = create_interval
        self.action_interval = action_interval
        self._clock = clock
        self._sleep = sleep
        self._locks: dict[int, asyncio.Lock] = {}
        self._next: dict[int, float] = {}

    async def run[T](
        self, guild_id: int, call: Callable[[], Awaitable[T]], *, create: bool = False
    ) -> T:
        lock = self._locks.setdefault(guild_id, asyncio.Lock())
        async with lock:
            wait = self._next.get(guild_id, 0) - self._clock()
            if wait > 0:
                await self._sleep(wait)
            try:
                return await call()
            finally:
                # Even a failed request consumes an attempt. Space the following operation.
                interval = self.create_interval if create else self.action_interval
                self._next[guild_id] = self._clock() + interval
