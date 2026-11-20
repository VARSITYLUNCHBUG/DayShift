"""Where a click's time goes, and the bot's loops doing less while it waits: the timing summary,
the effect loop sleeping until the next delayed effect, and the deadline loop popping only full
queues."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterator
from datetime import timedelta

import pytest
from django.db import connections

from bot.client import EFFECT_IDLE_SECONDS, EFFECT_MIN_WAIT_SECONDS, effect_wait
from bot.db import db
from league import timings
from league.models import Community, Match, QueueEntry
from league.services import deadlines, effects, queue, runtime
from league.services.common import add_effect, now
from tests.conftest import make_player


@pytest.fixture(autouse=True)
def _empty_timings() -> Iterator[None]:
    timings.summary()
    yield
    timings.summary()


def test_only_a_call_that_ran_slowly_is_warned_about(caplog: pytest.LogCaptureFixture) -> None:
    """Calls queued behind a slow one waited, but didn't run slowly: only the slow one is named."""
    from league import asyncdb

    def queued() -> None: ...

    def slow() -> None: ...

    with caplog.at_level("WARNING", logger="league.asyncdb"):
        asyncdb._record(queued, wait=2.0, run=0.01)
        asyncdb._record(slow, wait=0.0, run=asyncdb.SLOW_SECONDS + 0.1)
    warned = [record.call for record in caplog.records if record.msg == "Slow database call"]  # type: ignore[attr-defined]
    assert warned == [asyncdb._name(slow)]
    assert timings.summary()["db.wait"]["count"] == 2


# --- The summary -------------------------------------------------------------------------------


def test_the_summary_reports_nearest_rank_percentiles_and_empties() -> None:
    for milliseconds in range(1, 101):
        timings.record("db.wait", milliseconds / 1000)
    timings.record("effect.run:render_board", 0.25)

    assert timings.summary() == {
        "db.wait": {"count": 100, "p50_ms": 50.0, "p95_ms": 95.0, "max_ms": 100.0},
        "effect.run:render_board": {"count": 1, "p50_ms": 250.0, "p95_ms": 250.0, "max_ms": 250.0},
    }
    assert timings.summary() == {}


def test_a_window_keeps_only_its_latest_samples() -> None:
    for _ in range(timings.WINDOW):
        timings.record("db.run", 1.0)
    timings.record("db.run", 0.0)

    assert timings.summary()["db.run"]["count"] == timings.WINDOW


@pytest.fixture
def close_db_thread() -> Iterator[None]:
    yield
    # The DB thread holds its own connection, which would block dropping the test DB.
    asyncio.run(db(connections.close_all))


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("close_db_thread")
def test_every_database_call_is_timed() -> None:
    assert asyncio.run(db(lambda: 7)) == 7

    summary = timings.summary()
    assert summary["db.wait"]["count"] == 1
    assert summary["db.run"]["count"] == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("close_db_thread")
def test_a_call_is_timed_on_the_thread_not_when_the_loop_gets_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A loop busy for 0.3 s after the call ends: that's the loop's time, not the query's."""

    async def scenario() -> None:
        async def busy_loop() -> None:
            await asyncio.sleep(0.01)
            time.sleep(0.3)  # Holds the event loop while the result is waiting.

        blocker = asyncio.create_task(busy_loop())
        # Ends at about 0.05 s, while the loop is held until about 0.31 s.
        await db(lambda: time.sleep(0.05))
        await blocker

    asyncio.run(scenario())
    run = timings.summary()["db.run"]["max_ms"]
    assert 40 < run < 200


# --- The effect loop's sleep -------------------------------------------------------------------


def test_the_effect_loop_polls_when_nothing_is_delayed() -> None:
    assert effect_wait(None) == EFFECT_IDLE_SECONDS


def test_the_effect_loop_sleeps_until_the_next_delayed_effect() -> None:
    moment = now()
    assert effect_wait(moment + timedelta(seconds=0.4), moment) == pytest.approx(0.4)


def test_a_far_off_effect_still_leaves_the_fallback_poll() -> None:
    moment = now()
    assert effect_wait(moment + timedelta(minutes=5), moment) == EFFECT_IDLE_SECONDS


def test_an_effect_due_already_never_spins_the_loop() -> None:
    moment = now()
    assert effect_wait(moment - timedelta(seconds=1), moment) == EFFECT_MIN_WAIT_SECONDS


@pytest.mark.django_db
def test_the_next_due_effect_is_the_earliest_still_delayed(league: Community) -> None:
    soon, later = now() + timedelta(seconds=1), now() + timedelta(seconds=30)
    add_effect(league, "render_queue", lane="a", run_after=later)
    add_effect(league, "render_queue", lane="b", run_after=soon)
    add_effect(league, "render_queue", lane="c")  # Due now: the worker runs it, not waits.

    assert effects.next_due_at(now()) == soon


@pytest.mark.django_db
def test_nothing_delayed_means_no_next_due(league: Community) -> None:
    add_effect(league, "render_queue")
    assert effects.next_due_at(now()) is None


@pytest.mark.django_db
def test_an_effect_due_since_the_last_look_is_next(league: Community) -> None:
    """It fell due after the dispatch looked: due already, so the loop looks again at once rather
    than waiting out the fallback poll."""
    looked = now() - timedelta(seconds=1)
    fell_due = looked + timedelta(milliseconds=500)
    add_effect(league, "render_queue", lane="a", run_after=fell_due)
    add_effect(league, "render_queue", lane="b", run_after=now() + timedelta(seconds=30))

    assert effects.next_due_at(looked) == fell_due
    assert effect_wait(fell_due) == EFFECT_MIN_WAIT_SECONDS


@pytest.mark.django_db
def test_an_effect_due_at_the_last_look_was_in_it(league: Community) -> None:
    """Due by then, so the dispatch saw it: it runs, or waits on a busy lane or a retry, which
    wake the worker themselves. Returning it would spin the loop while its lane is busy."""
    looked = now()
    add_effect(league, "render_queue", run_after=looked)

    assert effects.next_due_at(looked) is None


# --- The deadline loop's queue pops ------------------------------------------------------------


@pytest.mark.django_db
def test_no_queue_means_no_pop(league: Community) -> None:
    assert queue.full_queues() == []


@pytest.mark.django_db
def test_a_short_queue_is_not_popped(league: Community) -> None:
    for number in range(1, 12):
        queue.join(league.pk, make_player(number))
    assert queue.full_queues() == []


@pytest.mark.django_db
def test_a_full_queue_waits_for_a_slot_then_pops(league: Community) -> None:
    runtime.update(league, max_concurrent_matches=1)
    for number in range(1, 25):
        queue.join(league.pk, make_player(number))
    assert Match.objects.count() == 1
    # Held back by capacity, so it stays on the list every pass until a slot frees up.
    assert queue.full_queues() == [league.pk]
    assert deadlines.tick() == 0

    runtime.update(league, max_concurrent_matches=2)
    # The pop counts as fired, so the bot wakes its effect worker for the new lobby at once.
    assert deadlines.tick() == 1
    assert Match.objects.count() == 2
    assert QueueEntry.objects.count() == 0
