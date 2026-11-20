"""The queue's idle timeout: a "Still queueing?" DM, then out with no penalty.

Someone who queues and walks away would otherwise sit there until the queue pops, miss the ready
check and get its cooldown. Both timers are runtime settings: 90 minutes, with the DM 5 before.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from django.core.exceptions import ValidationError

from bot.routing import registered_actions
from league.domain import copy
from league.domain.errors import InvalidAction
from league.models import Community, Match, OutboxEffect, Player, PrioEntry, QueueEntry
from league.services import deadlines, lobby, penalties, queue, runtime
from tests.conftest import Clock, make_player
from tests.test_bot import (
    QUEUE_CHANNEL,
    FakeGateway,
    all_custom_ids,
    assert_within_limits,
    drain,
    wired,  # noqa: F401  (a fixture)
)

MINUTE = 60
IDLE = 90 * MINUTE
WARN = 5 * MINUTE


def _queued(community: Community) -> list[int]:
    return list(QueueEntry.objects.filter(community=community).values_list("player_id", flat=True))


def _effects(kind: str) -> list[OutboxEffect]:
    return list(OutboxEffect.objects.filter(kind=kind).order_by("pk"))


@pytest.mark.django_db
def test_the_timers_default_to_90_minutes_and_a_dm_5_before(league: Community) -> None:
    settings = runtime.of(league)
    assert (settings.queue_idle_minutes, settings.queue_warn_minutes) == (90, 5)


@pytest.mark.django_db
def test_asked_at_85_minutes_then_out_at_90_with_no_penalty(
    league: Community, clock: Clock
) -> None:
    ann, bob = make_player(1), make_player(2)
    queue.join(league.pk, ann)
    clock.advance(10 * MINUTE)
    queue.join(league.pk, bob)

    clock.advance(IDLE - WARN - 10 * MINUTE - 1)
    deadlines.tick()
    assert _effects("queue_check_in") == []

    clock.advance(1)
    deadlines.tick()
    (check_in,) = _effects("queue_check_in")
    assert check_in.payload["discord_user_id"] == ann.discord_user_id
    assert QueueEntry.objects.get(player=ann).warned_at is not None
    deadlines.tick()
    assert len(_effects("queue_check_in")) == 1, "Asked once, not every tick"

    clock.advance(WARN - 1)
    deadlines.tick()
    assert _queued(league) == [ann.pk, bob.pk]

    clock.advance(1)
    deadlines.tick()
    assert _queued(league) == [bob.pk]
    (removed,) = _effects("queue_idle_removed")
    assert removed.payload["discord_user_id"] == ann.discord_user_id
    assert removed.payload["warned"] is True
    assert penalties.active_penalty(league, ann) is None
    # Their place is held, as for any leave.
    assert PrioEntry.objects.get(discord_user_id=ann.discord_user_id).grace_until is not None


@pytest.mark.django_db
def test_keep_me_in_restarts_the_clock_and_keeps_the_place(league: Community, clock: Clock) -> None:
    ann, bob = make_player(1), make_player(2)
    queue.join(league.pk, ann)
    queue.join(league.pk, bob)
    joined_at = QueueEntry.objects.get(player=ann).joined_at
    clock.advance(IDLE - WARN)
    deadlines.tick()

    remove_at = queue.stay(league.pk, ann)
    entry = QueueEntry.objects.get(player=ann)
    assert entry.warned_at is None and entry.joined_at == joined_at
    assert remove_at == entry.active_at + queue.idle_timeout(league.pk).idle  # type: ignore[union-attr]

    clock.advance(WARN)
    deadlines.tick()
    assert _queued(league) == [ann.pk], "Bob didn't answer; Ann did, and stays first"
    assert [e.payload["discord_user_id"] for e in _effects("queue_idle_removed")] == [
        bob.discord_user_id
    ]


@pytest.mark.django_db
def test_joining_again_in_time_gets_the_place_back(league: Community, clock: Clock) -> None:
    ann, bob = make_player(1), make_player(2)
    queue.join(league.pk, ann)
    clock.advance(MINUTE)
    queue.join(league.pk, bob)
    clock.advance(IDLE - WARN - MINUTE)
    deadlines.tick()
    clock.advance(WARN)
    deadlines.tick()
    assert _queued(league) == [bob.pk]

    clock.advance(MINUTE)
    queue.join(league.pk, ann)
    assert _queued(league) == [ann.pk, bob.pk]
    assert QueueEntry.objects.get(player=ann).warned_at is None


@pytest.mark.django_db
def test_after_downtime_the_dm_still_gets_its_full_time(league: Community, clock: Clock) -> None:
    """The bot was down past someone's idle time: they're asked first, not taken out at once."""
    ann = make_player(1)
    queue.join(league.pk, ann)
    clock.advance(3 * IDLE)
    deadlines.tick()
    assert _queued(league) == [ann.pk]
    assert len(_effects("queue_check_in")) == 1

    clock.advance(WARN - 1)
    deadlines.tick()
    assert _queued(league) == [ann.pk]
    clock.advance(1)
    deadlines.tick()
    assert _queued(league) == []


@pytest.mark.django_db
def test_with_no_dm_they_are_taken_out_at_the_idle_time(league: Community, clock: Clock) -> None:
    runtime.update(league, queue_warn_minutes=0)
    ann = make_player(1)
    queue.join(league.pk, ann)
    clock.advance(IDLE - 1)
    deadlines.tick()
    assert _queued(league) == [ann.pk]
    clock.advance(1)
    deadlines.tick()
    assert _queued(league) == []
    assert _effects("queue_check_in") == []
    assert _effects("queue_idle_removed")[0].payload["warned"] is False


@pytest.mark.django_db
def test_zero_idle_minutes_turns_it_off(league: Community, clock: Clock) -> None:
    runtime.update(league, queue_idle_minutes=0)
    ann = make_player(1)
    queue.join(league.pk, ann)
    clock.advance(10 * IDLE)
    deadlines.tick()
    assert _queued(league) == [ann.pk]
    assert queue.stay(league.pk, ann) is None


@pytest.mark.django_db
def test_the_timers_are_read_live(league: Community, clock: Clock) -> None:
    """Changing the setting applies to everyone already waiting."""
    ann = make_player(1)
    queue.join(league.pk, ann)
    clock.advance(30 * MINUTE)
    deadlines.tick()
    assert _effects("queue_check_in") == []
    runtime.update(league, queue_idle_minutes=30)
    deadlines.tick()
    assert len(_effects("queue_check_in")) == 1


@pytest.mark.django_db
def test_a_popped_lobby_drops_the_check_in(
    league: Community, players: list[Player], clock: Clock
) -> None:
    queue.join(league.pk, players[0])
    clock.advance(IDLE - WARN)
    deadlines.tick()
    entry_id = _effects("queue_check_in")[0].payload["entry_id"]
    for player in players[1:]:
        queue.join(league.pk, player)
    assert Match.objects.exists()
    assert not queue.awaiting_check_in(int(entry_id))  # The DM is skipped.
    with pytest.raises(InvalidAction) as raised:
        queue.stay(league.pk, players[0])
    assert raised.value.message == copy.NO_LONGER_QUEUED


@pytest.mark.django_db
def test_a_cancelled_lobby_requeues_with_a_fresh_clock(
    league: Community, players: list[Player], clock: Clock
) -> None:
    for player in players:
        queue.join(league.pk, player)
    match = Match.objects.get()
    match.participants.update(ready_at=clock.now())
    clock.advance(IDLE)
    before = clock.now()
    lobby.void_live(Match.objects.lock(match.pk), source="staff", reason="test", requeue=True)
    assert QueueEntry.objects.filter(active_at__gte=before).count() == len(players)
    deadlines.tick()
    assert _effects("queue_check_in") == []


def test_the_dm_must_come_before_the_idle_time() -> None:
    from league.models import RuntimeSettings

    RuntimeSettings(queue_idle_minutes=30, queue_warn_minutes=10).clean()
    RuntimeSettings(queue_idle_minutes=0, queue_warn_minutes=10).clean()
    with pytest.raises(ValidationError):
        RuntimeSettings(queue_idle_minutes=10, queue_warn_minutes=10).clean()


# --- Discord ---------------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_the_check_in_dm_has_working_buttons(wired: Community, clock: Clock) -> None:  # noqa: F811
    ann = make_player(1)
    queue.join(wired.pk, ann)
    clock.advance(IDLE - WARN)
    deadlines.tick()
    gateway = FakeGateway()
    drain(gateway)
    (_user_id, view) = next(dm for dm in gateway.dms if dm[0] == ann.discord_user_id)
    assert_within_limits(view)
    text = str(view.to_components())
    assert "Still queueing?" in text and "Test" in text
    assert f"channels/{wired.discord_guild_id}/{QUEUE_CHANNEL}" in text
    ids = all_custom_ids(view.to_components())
    assert f"dl:v1:queue_stay:0:{wired.pk}" in ids
    assert all(custom_id.split(":")[2] in registered_actions() for custom_id in ids)

    clock.advance(WARN)
    deadlines.tick()
    drain(gateway)
    assert "Taken out of the queue" in str(gateway.dms[-1][1].to_components())


@pytest.mark.django_db(transaction=True)
def test_closed_dms_still_take_them_out_on_time(wired: Community, clock: Clock) -> None:  # noqa: F811
    ann = make_player(1)
    queue.join(wired.pk, ann)
    gateway = FakeGateway(closed_dms={ann.discord_user_id})
    clock.advance(IDLE - WARN)
    deadlines.tick()
    drain(gateway)
    clock.advance(WARN)
    deadlines.tick()
    drain(gateway)
    assert _queued(wired) == []
    assert not OutboxEffect.objects.filter(kind__startswith="queue_", status="failed").exists()


@pytest.mark.django_db(transaction=True)
def test_pressing_keep_me_in_answers_in_the_dm(wired: Community, clock: Clock) -> None:  # noqa: F811
    from tests.test_handlers import click, fake_interaction, replies

    ann = make_player(1)
    queue.join(wired.pk, ann)
    clock.advance(IDLE - WARN)
    deadlines.tick()

    press = fake_interaction(ann, guild=False)
    press.edit_original_response = AsyncMock()
    click(press, "queue_stay", 0, str(wired.pk))
    assert replies(press) == []
    answered = press.edit_original_response.call_args.kwargs["view"]
    assert "staying in the queue" in str(answered.to_components())
    assert QueueEntry.objects.get(player=ann).warned_at is None

    leave = fake_interaction(ann, guild=False)
    leave.edit_original_response = AsyncMock()
    click(leave, "queue_leave", 0, str(wired.pk))
    assert _queued(wired) == []

    late = fake_interaction(ann, guild=False)
    late.edit_original_response = AsyncMock()
    click(late, "queue_stay", 0, str(wired.pk))
    view = late.edit_original_response.call_args.kwargs["view"]
    assert "no longer in the queue" in str(view.to_components())
