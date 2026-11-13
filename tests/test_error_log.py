"""The error channel: each server sees only its own errors; the operator sees everything."""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot import error_log
from bot.db import db
from bot.error_log import DiscordErrorHandler, ErrorReport, ErrorSink, build_report
from league import log_context

OPERATOR = 9000
GUILD_A, GUILD_B = 1, 2
CHANNEL_A = 9001


def _record(message: str = "boom", *, exc: bool = True, **extra: Any) -> logging.LogRecord:
    exc_info = None
    if exc:
        try:
            raise RuntimeError("the reason")
        except RuntimeError:
            exc_info = sys.exc_info()
    record = logging.LogRecord("league.test", logging.ERROR, __file__, 1, message, (), exc_info)
    record.__dict__.update(extra)
    return record


class FakeClient:
    def __init__(self, *, failing: bool = False) -> None:
        self.sent: list[tuple[int, str]] = []
        self.failing = failing

    def get_channel(self, channel_id: int) -> Any:
        channel = MagicMock()

        async def send(text: str, **kwargs: Any) -> None:
            if self.failing:
                logging.getLogger("discord.http").error("send failed")  # Must not loop back.
                raise RuntimeError("Discord is down")
            assert kwargs["allowed_mentions"].everyone is False
            self.sent.append((channel_id, text))

        channel.send = send
        return channel

    fetch_channel = AsyncMock()


def _sink(client: FakeClient, channels: dict[int, int | None], **kwargs: Any) -> ErrorSink:
    async def lookup(guild_id: int) -> int | None:
        return channels.get(guild_id)

    return ErrorSink(client, lookup, kwargs.get("operator", OPERATOR), **kwargs.get("extra", {}))  # type: ignore[arg-type]


def test_a_servers_error_goes_to_its_own_channel_and_the_operator() -> None:
    client = FakeClient()
    sink = _sink(client, {GUILD_A: CHANNEL_A})
    with log_context.bind(guild=GUILD_A, match=7):
        report = build_report(_record())
    asyncio.run(sink.handle(report))
    (channel_a, summary), (operator, full) = client.sent
    assert channel_a == CHANNEL_A and operator == OPERATOR
    assert "RuntimeError: the reason" in summary and "Traceback" not in summary
    assert "match=7" in summary
    assert "Traceback" in full and full.rstrip().endswith("```")


def test_another_servers_error_never_reaches_this_channel() -> None:
    client = FakeClient()
    sink = _sink(client, {GUILD_A: CHANNEL_A, GUILD_B: None})
    asyncio.run(sink.handle(build_report(_record(guild=GUILD_B))))
    assert [channel for channel, _ in client.sent] == [OPERATOR]


def test_an_error_with_no_server_only_goes_to_the_operator_if_set() -> None:
    client = FakeClient()
    asyncio.run(_sink(client, {GUILD_A: CHANNEL_A}).handle(build_report(_record())))
    assert [channel for channel, _ in client.sent] == [OPERATOR]
    client = FakeClient()
    asyncio.run(_sink(client, {}, operator=None).handle(build_report(_record())))
    assert client.sent == []


def test_explicit_guild_wins_over_the_context() -> None:
    with log_context.bind(guild=GUILD_B):
        report = build_report(_record(guild=GUILD_A))
    assert report.guild_id == GUILD_A


def test_bursts_are_capped_then_counted() -> None:
    client = FakeClient()
    now = [0.0]
    sink = _sink(client, {GUILD_A: CHANNEL_A}, operator=None, extra={"clock": lambda: now[0]})
    report = build_report(_record(guild=GUILD_A))

    async def scenario() -> None:
        for _ in range(error_log.BURST_LIMIT + 5):
            await sink.handle(report)
        now[0] += error_log.BURST_WINDOW_SECONDS + 1
        await sink.handle(report)

    asyncio.run(scenario())
    assert len(client.sent) == error_log.BURST_LIMIT + 1
    assert client.sent[-1][1].startswith("-# 5 more errors weren't posted.")


def test_a_failing_post_does_not_feed_itself() -> None:
    client = FakeClient(failing=True)
    handler = DiscordErrorHandler()
    root = logging.getLogger()

    async def scenario() -> asyncio.Queue[ErrorReport]:
        handler.bind(asyncio.get_running_loop())
        root.addHandler(handler)
        try:
            await _sink(client, {GUILD_A: CHANNEL_A}).handle(build_report(_record(guild=GUILD_A)))
            await asyncio.sleep(0)
        finally:
            root.removeHandler(handler)
        assert handler.queue is not None
        return handler.queue

    queue = asyncio.run(scenario())
    assert queue.empty()  # The sink's own "send failed" was dropped.


def test_the_handler_hands_records_to_the_loop_from_any_thread() -> None:
    handler = DiscordErrorHandler()

    async def scenario() -> ErrorReport:
        handler.bind(asyncio.get_running_loop())
        with log_context.bind(guild=GUILD_A):
            await asyncio.to_thread(handler.emit, _record())  # Copies the context, like db().
        assert handler.queue is not None
        return await asyncio.wait_for(handler.queue.get(), 2)

    assert asyncio.run(scenario()).guild_id == GUILD_A


def test_the_queue_keeps_the_newest_when_full(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(error_log, "QUEUE_SIZE", 2)
    handler = DiscordErrorHandler()

    async def scenario() -> list[str]:
        handler.bind(asyncio.get_running_loop())
        for n in range(4):
            handler.emit(_record(f"error {n}", exc=False))
        await asyncio.sleep(0)
        assert handler.queue is not None
        return [handler.queue.get_nowait().summary for _ in range(handler.queue.qsize())]

    summaries = asyncio.run(scenario())
    assert len(summaries) == 2 and "error 3" in summaries[-1]


def test_long_tracebacks_keep_their_fence_closed() -> None:
    report = build_report(_record("x" * 5000))
    assert len(report.full) <= error_log.MAX_LENGTH + 20
    assert report.full.rstrip().endswith("```")
    assert len(report.summary) <= error_log.MAX_LENGTH + 20


def test_context_does_not_leak_out_of_a_db_call() -> None:
    def inner() -> dict[str, Any]:
        with log_context.bind(guild=GUILD_B):
            pass
        return dict(log_context.current())

    async def scenario() -> tuple[dict[str, Any], dict[str, Any]]:
        with log_context.bind(guild=GUILD_A):
            seen = await db(inner)
            after = dict(log_context.current())
        return seen, after

    seen, after = asyncio.run(scenario())
    assert seen == {"guild": GUILD_A}
    assert after == {"guild": GUILD_A}
    assert dict(log_context.current()) == {}


def test_worker_retries_are_warnings_not_errors(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from types import SimpleNamespace

    from bot.effects import worker as worker_module

    async def boom(env: Any) -> None:
        raise RuntimeError("try again")

    monkeypatch.setitem(worker_module.HANDLERS, "boom", boom)
    monkeypatch.setattr(worker_module.effects, "mark_started", lambda *_: True)
    monkeypatch.setattr(worker_module.effects, "mark_retry", lambda *_: "pending")
    effect = SimpleNamespace(
        pk=1, match_id=None, kind="boom", lane="", community_id=1, community=None, match=None
    )
    worker = worker_module.EffectWorker(gateway=None)  # type: ignore[arg-type]
    with caplog.at_level(logging.WARNING):
        asyncio.run(worker._run_effect(effect))  # type: ignore[arg-type]
    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]
    assert any(record.message == "Effect raised" for record in caplog.records)
