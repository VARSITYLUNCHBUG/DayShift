"""The effect worker gives each lane its own task, so one slow match, or one server's stuck
panel, never stalls another."""

from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest

from bot import client as client_module
from bot.effects import worker as worker_module
from bot.effects.handlers import Env
from bot.effects.worker import EffectWorker


async def settle(condition: Callable[[], bool], timeout: float = 15.0) -> None:
    """Yield to the loop until `condition` holds. Generous, for a busy machine; it returns as soon
    as the condition holds."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not condition():
        assert loop.time() < deadline, "timed out waiting"
        await asyncio.sleep(0.01)


def fake_effect(
    pk: int, match_id: int | None, kind: str, *, lane: str = "", community_id: int = 1
) -> Any:
    return SimpleNamespace(
        pk=pk,
        match_id=match_id,
        kind=kind,
        lane=lane,
        community_id=community_id,
        community=None,
        match=None,
    )


class Outbox:
    """Stands in for the database: hands out pending effects in order, per lane."""

    def __init__(self, *effects: Any) -> None:
        self.pending = list(effects)
        self.done: list[int] = []

    def due_by_match(self) -> list[list[Any]]:
        groups: dict[Any, list[Any]] = {}
        for effect in self.pending:
            groups.setdefault(worker_module.effects.lane_of(effect), []).append(effect)
        return list(groups.values())

    def mark_started(self, effect_id: int) -> bool:
        return any(effect.pk == effect_id for effect in self.pending)

    def mark_done(self, effect_id: int, *_: object) -> None:
        self.pending = [effect for effect in self.pending if effect.pk != effect_id]
        self.done.append(effect_id)


@pytest.fixture
def outbox(monkeypatch: pytest.MonkeyPatch) -> Outbox:
    box = Outbox()
    monkeypatch.setattr(worker_module.effects, "due_by_match", box.due_by_match)
    monkeypatch.setattr(worker_module.effects, "next_due_at", lambda _after: None)
    monkeypatch.setattr(worker_module.effects, "mark_started", box.mark_started)
    monkeypatch.setattr(worker_module.effects, "mark_done", box.mark_done)
    return box


@pytest.fixture
def slow_and_fast(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """A `slow` effect that waits until released, and a `fast` one that records its run."""
    state = SimpleNamespace(release=None, fast_ran=None, slow_calls=0, order=[])

    async def slow(env: Env) -> None:
        state.slow_calls += 1
        state.order.append(env.effect.pk)
        await state.release.wait()

    async def fast(env: Env) -> None:
        state.order.append(env.effect.pk)
        state.fast_ran.set()

    monkeypatch.setitem(worker_module.HANDLERS, "slow", slow)
    monkeypatch.setitem(worker_module.HANDLERS, "fast", fast)
    return state


def test_a_slow_match_does_not_hold_up_another_match(
    outbox: Outbox, slow_and_fast: SimpleNamespace
) -> None:
    outbox.pending = [fake_effect(1, 101, "slow"), fake_effect(2, 202, "fast")]

    async def scenario() -> None:
        slow_and_fast.release = asyncio.Event()
        slow_and_fast.fast_ran = asyncio.Event()
        worker = EffectWorker(gateway=None)  # type: ignore[arg-type]
        assert await worker.dispatch() == 2
        # Match 202 finishes while match 101 is still stuck on its Discord call.
        await asyncio.wait_for(slow_and_fast.fast_ran.wait(), timeout=15)
        # Marking it done runs on the DB thread, and its lane closes after that, back on the loop.
        await settle(lambda: worker.busy_matches == {101})
        assert outbox.done == [2]
        slow_and_fast.release.set()
        await worker.run_once()
        assert worker.busy_matches == set()

    asyncio.run(scenario())
    assert outbox.done == [2, 1]


def _run_slow_then_fast(outbox: Outbox, state: SimpleNamespace, stuck_lane: object) -> None:
    """Effect 1 hangs; effect 2, in another lane, must finish while it does."""

    async def scenario() -> None:
        state.release = asyncio.Event()
        state.fast_ran = asyncio.Event()
        worker = EffectWorker(gateway=None)  # type: ignore[arg-type]
        assert await worker.dispatch() == 2
        # Generous: on a busy machine the other lane can take a moment to be scheduled.
        await asyncio.wait_for(state.fast_ran.wait(), timeout=15)
        await settle(lambda: worker.busy_matches == {stuck_lane})
        assert outbox.done == [2]
        state.release.set()
        await worker.run_once()

    asyncio.run(scenario())
    assert outbox.done == [2, 1]


def test_one_servers_panel_does_not_hold_up_anothers(
    outbox: Outbox, slow_and_fast: SimpleNamespace
) -> None:
    """Work outside a match used to share one lane across every server."""
    outbox.pending = [
        fake_effect(1, None, "slow", community_id=1),
        fake_effect(2, None, "fast", community_id=2),
    ]
    _run_slow_then_fast(outbox, slow_and_fast, "slow:1")


def test_a_named_lane_runs_apart_from_others(
    outbox: Outbox, slow_and_fast: SimpleNamespace
) -> None:
    outbox.pending = [
        fake_effect(1, None, "slow", lane="staff_alerts:7"),
        fake_effect(2, None, "fast", lane="staff_alerts:8"),
    ]
    _run_slow_then_fast(outbox, slow_and_fast, "staff_alerts:7")


def test_lane_keys() -> None:
    lane_key = worker_module.effects.lane_key
    assert lane_key(101, "", "render_board", 1) == 101
    assert lane_key(101, "ignored", "render_board", 1) == 101  # A match's lane always wins.
    assert lane_key(None, "staff_alerts:7", "post_staff_alert", 1) == "staff_alerts:7"
    # Rows written before lanes existed have a blank lane: one per kind and server.
    assert lane_key(None, "", "render_queue", 3) == "render_queue:3"
    assert lane_key(101, "", "create_team_voice", 1) == "voice:101"
    assert lane_key(101, "", "team_move_player", 1) == "voice:101"
    assert lane_key(101, "", "cleanup_voice", 1) == "voice:101"
    # deadlock-api's slow reads and long waits never hold up the match's board.
    assert lane_key(101, "", "check_match_api", 1) == "api:101"
    assert lane_key(101, "", "create_api_lobby", 1) == "api:101"
    assert lane_key(101, "", "fetch_api_match_id", 1) == "api:101"
    # Replaced board and grid messages go one at a time, off the board's path.
    assert lane_key(101, "", "delete_message", 1) == "deletes:101"


def test_slow_voice_setup_does_not_block_its_own_match_board(
    outbox: Outbox, slow_and_fast: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(worker_module.HANDLERS, "create_team_voice", worker_module.HANDLERS["slow"])
    monkeypatch.setitem(worker_module.HANDLERS, "render_board", worker_module.HANDLERS["fast"])
    outbox.pending = [fake_effect(1, 101, "create_team_voice"), fake_effect(2, 101, "render_board")]

    async def scenario() -> None:
        slow_and_fast.release = asyncio.Event()
        slow_and_fast.fast_ran = asyncio.Event()
        worker = EffectWorker(gateway=None)  # type: ignore[arg-type]
        assert await worker.dispatch() == 2
        await asyncio.wait_for(slow_and_fast.fast_ran.wait(), 15)
        assert not slow_and_fast.release.is_set()
        slow_and_fast.release.set()
        await worker.run_once()

    asyncio.run(scenario())


def test_a_busy_match_keeps_its_effects_in_order(
    outbox: Outbox, slow_and_fast: SimpleNamespace
) -> None:
    outbox.pending = [fake_effect(1, 101, "slow")]

    async def scenario() -> None:
        slow_and_fast.release = asyncio.Event()
        slow_and_fast.fast_ran = asyncio.Event()
        worker = EffectWorker(gateway=None)  # type: ignore[arg-type]
        await worker.dispatch()
        await asyncio.sleep(0)
        # New work for the same match arrives mid-call. It must wait, not start a second lane.
        outbox.pending.append(fake_effect(2, 101, "fast"))
        assert await worker.dispatch() == 0
        assert slow_and_fast.slow_calls == 1
        assert not slow_and_fast.fast_ran.is_set()
        slow_and_fast.release.set()
        await worker.drain()

    asyncio.run(scenario())
    assert slow_and_fast.slow_calls == 1
    assert slow_and_fast.order == [1, 2]
    assert outbox.done == [1, 2]


def test_a_finished_lane_wakes_the_loop(outbox: Outbox, slow_and_fast: SimpleNamespace) -> None:
    outbox.pending = [fake_effect(1, None, "fast")]
    woken: list[bool] = []

    async def scenario() -> None:
        slow_and_fast.fast_ran = asyncio.Event()
        worker = EffectWorker(gateway=None, on_lane_done=lambda: woken.append(True))  # type: ignore[arg-type]
        await worker.run_once()

    asyncio.run(scenario())
    assert woken == [True]


def test_a_crashed_lane_is_logged_and_frees_its_match(
    outbox: Outbox, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    async def boom(env: Env) -> None:
        raise RuntimeError("handler blew up")

    def broken_mark_retry(*_: object) -> None:
        raise RuntimeError("database is down")

    monkeypatch.setitem(worker_module.HANDLERS, "boom", boom)
    monkeypatch.setattr(worker_module.effects, "mark_retry", broken_mark_retry)
    outbox.pending = [fake_effect(1, 101, "boom")]

    async def scenario() -> EffectWorker:
        worker = EffectWorker(gateway=None)  # type: ignore[arg-type]
        await worker.dispatch()
        await settle(lambda: not worker.busy_matches)
        return worker

    worker = asyncio.run(scenario())
    assert worker.busy_matches == set()
    assert "Effect lane crashed" in caplog.text


def test_sigterm_shuts_the_bot_down_like_ctrl_c(monkeypatch: pytest.MonkeyPatch) -> None:
    installed: list[object] = []
    monkeypatch.setattr(client_module.settings, "DISCORD_TOKEN", "test-token")
    monkeypatch.setattr(
        client_module.DayShiftBot,
        "run",
        lambda self, *a, **k: installed.append(signal.getsignal(signal.SIGTERM)),
    )
    previous = signal.getsignal(signal.SIGTERM)
    try:
        client_module.run()
        assert installed == [client_module._stop_on_sigterm]
        with pytest.raises(KeyboardInterrupt):
            signal.raise_signal(signal.SIGTERM)
    finally:
        signal.signal(signal.SIGTERM, previous)
        logging.getLogger().removeHandler(client_module.discord_error_handler)
