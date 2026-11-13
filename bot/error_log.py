"""Bebot's /seterrorchannel: the bot's ERROR logs are posted to Discord as well as stdout.

Each server's channel gets only that server's errors, as a short summary. The full traceback
goes only to the operator's channel (`ERROR_LOG_CHANNEL_ID`), which also gets errors that belong
to no server. One server can never read another's.

An error's server comes from `extra={"guild": ...}` if given, else from `league.log_context`,
which interactions, effects and deadlines bind.

The handler never touches the database or Discord itself: records can come from any thread, so
it only hands them to the bot's loop. A sink task there finds the channel and posts, with a burst
cap per channel. Anything the sink itself logs is dropped, so a failing post can't feed itself.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
import traceback
from collections import deque
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

import discord

from league import log_context

MAX_LENGTH = 1900
BURST_LIMIT = 10
BURST_WINDOW_SECONDS = 60.0
QUEUE_SIZE = 200
CHANNEL_CACHE_SECONDS = 60.0

_in_sink: ContextVar[bool] = ContextVar("error_log_sink", default=False)

ChannelLookup = Callable[[int], Awaitable[int | None]]


@dataclass(frozen=True, slots=True)
class ErrorReport:
    guild_id: int | None
    summary: str
    full: str


def _truncate(text: str, fence: bool) -> str:
    if len(text) <= MAX_LENGTH:
        return text
    cut = text[: MAX_LENGTH - 20] + "\n…(truncated)"
    return cut + "\n```" if fence else cut


def build_report(record: logging.LogRecord) -> ErrorReport:
    """A summary for the server's channel and the full report for the operator's."""
    guild = record.__dict__.get("guild") or log_context.current().get("guild")
    message = record.getMessage()
    header = f"**[{record.levelname}]** `{record.name}`: {message}"
    summary = header
    full = header
    if record.exc_info and record.exc_info[1] is not None:
        error = record.exc_info[1]
        frames = traceback.extract_tb(record.exc_info[2])
        where = ""
        if frames:
            last = frames[-1]
            where = f" at `{os.path.basename(last.filename)}:{last.lineno}`"
        summary = f"{header}\n`{type(error).__name__}: {str(error)[:200]}`{where}"
        trace = "".join(traceback.format_exception(*record.exc_info))
        full = f"{header}\n```\n{trace}\n```"
    bound = {key: value for key, value in log_context.current().items() if key != "guild"}
    if bound:
        context = " ".join(f"{key}={value}" for key, value in sorted(bound.items()))
        summary = f"{summary}\n-# {context}"
    try:
        guild_id = int(guild) if guild else None
    except (TypeError, ValueError):
        guild_id = None
    return ErrorReport(guild_id, _truncate(summary, fence=False), _truncate(full, fence=True))


class _Burst:
    """At most BURST_LIMIT posts per channel per window; the rest are counted, then reported."""

    def __init__(self) -> None:
        self._sent: dict[int, deque[float]] = {}
        self.suppressed: dict[int, int] = {}

    def allow(self, channel_id: int, moment: float) -> bool:
        sent = self._sent.setdefault(channel_id, deque())
        while sent and moment - sent[0] >= BURST_WINDOW_SECONDS:
            sent.popleft()
        if len(sent) >= BURST_LIMIT:
            self.suppressed[channel_id] = self.suppressed.get(channel_id, 0) + 1
            return False
        sent.append(moment)
        return True


class DiscordErrorHandler(logging.Handler):
    def __init__(self, level: int = logging.ERROR) -> None:
        super().__init__(level=level)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue[ErrorReport] | None = None

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._queue = asyncio.Queue(maxsize=QUEUE_SIZE)

    @property
    def queue(self) -> asyncio.Queue[ErrorReport] | None:
        return self._queue

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if _in_sink.get() or self._loop is None or self._loop.is_closed():
                return
            report = build_report(record)
            self._loop.call_soon_threadsafe(self._put, report)
        except Exception:  # A log handler must never raise.
            return

    def _put(self, report: ErrorReport) -> None:
        queue = self._queue
        if queue is None:
            return
        if queue.full():
            with contextlib.suppress(asyncio.QueueEmpty):
                queue.get_nowait()  # Keep the newest: they're the ones still relevant.
        queue.put_nowait(report)


class ErrorSink:
    """Posts queued reports. Runs as a task on the bot's loop."""

    def __init__(
        self,
        client: discord.Client,
        lookup: ChannelLookup,
        operator_channel_id: int | None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._lookup = lookup
        self._operator = operator_channel_id or None
        self._clock = clock
        self._burst = _Burst()
        self._cache: dict[int, tuple[int | None, float]] = {}

    def forget(self, guild_id: int) -> None:
        """The server changed its channel: look it up afresh."""
        self._cache.pop(guild_id, None)

    async def _guild_channel(self, guild_id: int) -> int | None:
        cached = self._cache.get(guild_id)
        moment = self._clock()
        if cached is not None and moment - cached[1] < CHANNEL_CACHE_SECONDS:
            return cached[0]
        channel_id = await self._lookup(guild_id)
        self._cache[guild_id] = (channel_id, moment)
        return channel_id

    async def _post(self, channel_id: int, text: str) -> None:
        if not self._burst.allow(channel_id, self._clock()):
            return
        suppressed = self._burst.suppressed.pop(channel_id, 0)
        if suppressed:
            text = _truncate(f"-# {suppressed} more errors weren't posted.\n{text}", fence=False)
        channel: Any = self._client.get_channel(channel_id)
        if channel is None:
            channel = await self._client.fetch_channel(channel_id)
        await channel.send(text, allowed_mentions=discord.AllowedMentions.none())

    async def handle(self, report: ErrorReport) -> None:
        token = _in_sink.set(True)
        try:
            if report.guild_id is not None:
                channel_id = await self._guild_channel(report.guild_id)
                if channel_id is not None and channel_id != self._operator:
                    with contextlib.suppress(Exception):
                        await self._post(channel_id, report.summary)
            if self._operator is not None:
                with contextlib.suppress(Exception):
                    await self._post(self._operator, report.full)
        except Exception:
            return  # Nothing here may log an error: it would only come back round.
        finally:
            _in_sink.reset(token)

    async def run(self, queue: asyncio.Queue[ErrorReport]) -> None:
        while True:
            report = await queue.get()
            await self.handle(report)


discord_error_handler = DiscordErrorHandler()
