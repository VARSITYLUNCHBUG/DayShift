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
        self._next: dict[int, float] = {}

    async def run[T](
        self, guild_id: int, call: Callable[[], Awaitable[T]], *, create: bool = False
    ) -> T:
        """Start `call` in this server's next free slot. Starts are spaced, not whole calls: a
        call that is slow, or waits out a rate limit, doesn't hold up the ones after it. A failed
        call still used its slot."""
        moment = self._clock()
        start = max(moment, self._next.get(guild_id, 0.0))
        # Reserved before sleeping, with no await in between, so concurrent callers queue up.
        self._next[guild_id] = start + (self.create_interval if create else self.action_interval)
        if start > moment:
            await self._sleep(start - moment)
        return await call()
