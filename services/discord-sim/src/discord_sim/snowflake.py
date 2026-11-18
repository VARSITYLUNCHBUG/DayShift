"""Snowflake IDs. Seeded objects get fixed IDs, everything made later is a real time-based one."""

from __future__ import annotations

import time
from collections.abc import Callable

# Every sim ID is at or above this, clear of stand-ins (< 1000) and test helpers (10_000_000+).
BASE = 1_100_000_000_000_000_000

# Fixed IDs of the seeded world, so fixtures can point at them.
OWNER_USER_ID = BASE
GUILD_ID = BASE + 1  # Also the @everyone role.
BOT_USER_ID = BASE + 2  # Also the application, as on Discord for apps made since 2018.
BOT_ROLE_ID = BASE + 3
STAFF_ROLE_ID = BASE + 4
TEXT_CATEGORY_ID = BASE + 10
GENERAL_TEXT_ID = BASE + 11
VOICE_CATEGORY_ID = BASE + 12
GENERAL_VOICE_ID = BASE + 13
SEED_USER_BASE = BASE + 100  # SIM_SEED_USERS members are BASE+100, BASE+101, ...
MAX_SEED_USERS = 9_900
RUNTIME_BASE = BASE + 10_000

DISCORD_EPOCH_MS = 1_420_070_400_000
TIMESTAMP_SHIFT = 22


class SnowflakeGenerator:
    """Hands out increasing IDs that carry their creation time, as Discord's do.

    Being time-based, an ID is never handed out twice, not even by a restarted sim talking to a
    league database that still holds Players for the old fake users. discord.py's `created_at`
    reads the real time too. Today's IDs are far above RUNTIME_BASE.
    """

    def __init__(self, start: int = RUNTIME_BASE, clock: Callable[[], float] = time.time) -> None:
        self._last = start - 1
        self._clock = clock

    def next(self) -> int:
        stamp = (int(self._clock() * 1000) - DISCORD_EPOCH_MS) << TIMESTAMP_SHIFT
        self._last = max(stamp, self._last + 1)
        return self._last
