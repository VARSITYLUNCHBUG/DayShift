"""The bot through a database outage: startup recovery waits for the database instead of leaving
a connected bot with no loops, and a failing loop logs its error once, not once a second."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.db import OperationalError

from bot import client as client_module
from bot.client import DraftBot, Heartbeat, LoopErrors, deadline_loop
from bot.effects import worker as worker_module
from league.services import deadlines

CACHED = "server login has been failing, cached error: server DNS lookup failed"


class FlakyDb:
    """`db()` that raises like a database that is down for its first `failures` calls."""

    def __init__(self, failures: int) -> None:
        self.left = failures
        self.calls: list[object] = []

    async def __call__(self, fn: object, *args: object, **kwargs: object) -> object:
        self.calls.append(fn)
        if self.left:
            self.left -= 1
            raise OperationalError(CACHED)
        return 0 if fn is deadlines.tick else []


def test_startup_recovery_waits_for_the_database_then_starts_the_loops(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    flaky = FlakyDb(failures=3)
    monkeypatch.setattr(client_module, "db", flaky)
    monkeypatch.setattr(worker_module, "db", FlakyDb(failures=0))
    monkeypatch.setattr(client_module, "STARTUP_RETRY_SECONDS", (0.01,))
    beat = tmp_path / "beat"

    async def scenario() -> set[str]:
        bot = DraftBot(beat)
        await asyncio.wait_for(bot.on_ready(), 5)
        await bot.on_ready()  # A reconnect's on_ready: nothing is started twice.
        await asyncio.sleep(0.05)
        names = [task.get_name() for task in bot._tasks]
        for task in bot._tasks:
            task.cancel()
        await asyncio.gather(*bot._tasks, return_exceptions=True)
        assert len(names) == len(set(names))
        return set(names)

    with caplog.at_level(logging.INFO, logger="bot.client"):
        assert asyncio.run(scenario()) == {"deadlines", "effects", "watchdog"}
    assert beat.exists()
    assert flaky.calls.count(deadlines.extend_past_due) == 4
    failed = [r for r in caplog.records if r.getMessage() == "Startup recovery failed, retrying"]
    assert len(failed) == 1 and failed[0].exc_info is not None  # One traceback, not three.
    done = [r for r in caplog.records if r.getMessage() == "Startup recovery done after retries"]
    assert [r.__dict__["failures"] for r in done] == [3]


def test_a_failing_deadline_loop_logs_once_then_its_recovery(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    flaky = FlakyDb(failures=5)
    monkeypatch.setattr(client_module, "db", flaky)
    monkeypatch.setattr(client_module, "DEADLINE_INTERVAL_SECONDS", 0.01)
    stop = asyncio.Event()

    async def run() -> None:
        task = asyncio.create_task(
            deadline_loop(Heartbeat(tmp_path / "beat", ("deadlines",)), stop=stop)
        )
        while len(flaky.calls) < 8:
            await asyncio.sleep(0.01)
        stop.set()
        await asyncio.wait_for(task, 5)

    with caplog.at_level(logging.INFO, logger="bot.client"):
        asyncio.run(run())
    errors = [r for r in caplog.records if r.getMessage() == "Deadline loop error"]
    assert len(errors) == 1 and errors[0].exc_info is not None
    recovered = [r for r in caplog.records if r.getMessage() == "Deadline loop error: recovered"]
    assert [r.__dict__["failures"] for r in recovered] == [5]


def test_the_same_error_is_logged_again_after_a_while_and_a_new_one_at_once(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    now = [100.0]
    monkeypatch.setattr(client_module, "time", SimpleNamespace(monotonic=lambda: now[0]))
    errors = LoopErrors("Loop error")
    with caplog.at_level(logging.INFO, logger="bot.client"):
        for _ in range(30):
            errors.failed(OperationalError(CACHED))
            now[0] += 1
        errors.failed(RuntimeError("something else"))  # A different error: logged straight away.
        now[0] += 31  # 61 s after the first one.
        errors.failed(OperationalError(CACHED))
    logged = [r.exc_info[1] for r in caplog.records if r.exc_info]
    assert [type(e) for e in logged] == [OperationalError, RuntimeError, OperationalError]
    assert errors.failures == 32
