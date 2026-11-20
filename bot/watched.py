"""Which channels' chat and voice events the bot acts on, kept in memory.

Every message in the server and every voice join reaches the bot. Only a few channels matter:
live match text channels, the channels scrims run in, the Waiting Room and live team voices. A
trip to the database for each of the rest would queue behind real work on the one shared
database thread, button presses included, so they're dropped here instead.

The list is reloaded after the effects that create or remove those channels, after a scrim
starts or /setup runs, and every half minute regardless. Until the first load, every event is
let through, as before.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from bot.db import db
from league.services import effects

logger = logging.getLogger(__name__)

REFRESH_SECONDS = 30.0
# Effects after which the list may have changed.
CHANGES_CHANNELS = frozenset(
    {
        "create_lobby",
        "create_team_voice",
        "restart_voice",
        "cleanup_voice",
        "delete_text_channel",
        "render_board",  # A scrim's first board, or its last, in a public channel.
    }
)


class ChannelWatch:
    def __init__(self) -> None:
        self._text: frozenset[int] = frozenset()
        self._voice: frozenset[int] = frozenset()
        self.loaded = False
        self._dirty = asyncio.Event()

    def chat_matters(self, channel_id: int) -> bool:
        return not self.loaded or channel_id in self._text

    def voice_matters(self, channel_id: int) -> bool:
        return not self.loaded or channel_id in self._voice

    def set(self, watched: effects.WatchedChannels) -> None:
        self._text, self._voice, self.loaded = watched.text, watched.voice, True

    def request_refresh(self, kind: str | None = None) -> None:
        """Reload soon. With `kind`, only if that effect could have changed the list."""
        if kind is None or kind in CHANGES_CHANNELS:
            self._dirty.set()

    async def refresh(self) -> None:
        self.set(await db(effects.watched_channels))

    async def run(self) -> None:
        """Reload when asked, and every REFRESH_SECONDS anyway."""
        while True:
            self._dirty.clear()
            try:
                await self.refresh()
            except Exception:
                logger.warning("Couldn't reload the watched channels", exc_info=True)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._dirty.wait(), REFRESH_SECONDS)
