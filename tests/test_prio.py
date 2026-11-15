"""The priority list: who in the live queue has waited longest, shown privately by /prio.

It follows the match queue only. The Waiting Room is a public voice channel, so being in it puts
nobody on the list.
"""

from __future__ import annotations

import pytest

from bot.commands import prio as prio_commands
from bot.renderers.prio import place_text
from league.models import Community, Match, OutboxEffect, Player, PrioEntry, QueueEntry, SubOffer
from league.services import deadlines, lobby, prio, queue, subs
from tests.conftest import Clock, make_player
from tests.helpers import to_in_progress
from tests.test_bot import (
    FakeGateway,
    drain,
    wired,  # noqa: F401  (a fixture)
)


def _names(community: Community) -> list[str]:
    return [line.name for line in prio.prio_view(community.pk).lines]


@pytest.fixture
def room(league: Community) -> Community:
    return league


def _queue(community: Community, players: list[Player]) -> None:
    for player in players:
        queue.join(community.pk, player)


@pytest.mark.django_db
def test_the_queue_is_the_list_longest_wait_first(room: Community, clock: Clock) -> None:
    ann, bob = make_player(1), make_player(2)
    queue.join(room.pk, ann)
    clock.advance(30)
    queue.join(room.pk, bob)
    assert _names(room) == [ann.display_name, bob.display_name]


@pytest.mark.django_db
def test_leaving_holds_your_place_for_three_minutes(room: Community, clock: Clock) -> None:
    ann, bob = make_player(1), make_player(2)
    queue.join(room.pk, ann)
    clock.advance(30)
    queue.join(room.pk, bob)
    queue.leave(room.pk, ann)
    assert prio.GRACE_SECONDS == 180
    assert PrioEntry.objects.get(discord_user_id=ann.discord_user_id).grace_until is not None
    clock.advance(prio.GRACE_SECONDS - 10)
    queue.join(room.pk, ann)  # Back in time: the place is kept, in the queue too.
    assert _names(room) == [ann.display_name, bob.display_name]
    assert PrioEntry.objects.get(discord_user_id=ann.discord_user_id).grace_until is None
    assert list(QueueEntry.objects.values_list("player_id", flat=True)) == [ann.pk, bob.pk]


@pytest.mark.django_db
def test_the_hold_runs_out(room: Community, clock: Clock) -> None:
    ann, bob = make_player(1), make_player(2)
    queue.join(room.pk, ann)
    queue.join(room.pk, bob)
    queue.leave(room.pk, ann)
    clock.advance(prio.GRACE_SECONDS + 1)
    assert deadlines.tick() >= 1
    assert _names(room) == [bob.display_name]
    queue.join(room.pk, ann)  # Too late: the back of the list and of the queue.
    assert _names(room) == [bob.display_name, ann.display_name]
    assert list(QueueEntry.objects.values_list("player_id", flat=True)) == [bob.pk, ann.pk]


@pytest.mark.django_db
def test_an_expired_hold_the_timer_missed_isnt_kept(room: Community, clock: Clock) -> None:
    ann, bob = make_player(1), make_player(2)
    queue.join(room.pk, ann)
    queue.join(room.pk, bob)
    queue.leave(room.pk, ann)
    clock.advance(prio.GRACE_SECONDS + 1)
    queue.join(room.pk, ann)  # Before any tick: still too late.
    assert _names(room) == [bob.display_name, ann.display_name]


@pytest.mark.django_db
def test_staff_removal_and_clear_hold_nothing(room: Community) -> None:
    ann, bob = make_player(1), make_player(2)
    _queue(room, [ann, bob])
    queue.kick(room.pk, ann)
    assert _names(room) == [bob.display_name]
    queue.clear(room.pk)
    assert _names(room) == []
    assert not PrioEntry.objects.exists()


@pytest.mark.django_db
def test_a_popped_lobby_takes_its_players_off(room: Community) -> None:
    players = [make_player(n) for n in range(1, 14)]
    _queue(room, players)  # The twelfth pops a lobby; the thirteenth waits.
    assert _names(room) == [players[12].display_name]


@pytest.mark.django_db
def test_openings_go_down_the_list(room: Community, clock: Clock) -> None:
    players = [make_player(n) for n in range(1, 15)]
    _queue(room, players[:12])
    match = Match.objects.get()
    first, second = players[12], players[13]
    queue.join(room.pk, first)
    clock.advance(5)
    queue.join(room.pk, second)
    for participant in match.participants.exclude(player=players[0]):
        lobby.mark_ready(match.pk, participant.player)
    clock.advance(3600)
    deadlines.tick()  # players[0] missed the ready check.
    offer = SubOffer.objects.get()
    assert offer.player == first and offer.source == "prio"
    subs.answer_offer(offer.pk, first, True)
    assert match.participants.filter(player=first, is_active=True).exists()
    assert _names(room) == [second.display_name]


@pytest.mark.django_db
def test_a_held_place_isnt_offered_an_opening(room: Community, clock: Clock) -> None:
    players = [make_player(n) for n in range(1, 15)]
    _queue(room, players[:12])
    match = Match.objects.get()
    away, here = players[12], players[13]
    queue.join(room.pk, away)
    queue.join(room.pk, here)
    queue.leave(room.pk, away)  # Stepped out: their place is held, but they aren't asked.
    for participant in match.participants.exclude(player=players[0]):
        lobby.mark_ready(match.pk, participant.player)
    clock.advance(60)
    match.deadline_at = match.created_at
    match.save(update_fields=["deadline_at"])
    deadlines.tick()
    assert SubOffer.objects.get().player == here


@pytest.mark.django_db
def test_a_sub_comes_off_the_list(room: Community) -> None:
    players = [make_player(n) for n in range(1, 13)]
    _queue(room, players)
    match = to_in_progress(Match.objects.get())
    sub = make_player(40)
    queue.join(room.pk, sub)
    leaving = match.participants.exclude(is_captain=True).filter(is_active=True).first()
    assert leaving is not None
    lobby.swap_player(match, leaving, sub, ready=True)
    assert _names(room) == []


@pytest.mark.django_db
def test_a_cancelled_lobby_puts_its_players_back_at_their_place(
    room: Community, clock: Clock
) -> None:
    players = [make_player(n) for n in range(1, 13)]
    for player in players:
        queue.join(room.pk, player)
        clock.advance(1)
    later = make_player(40)
    queue.join(room.pk, later)
    match = Match.objects.get()
    for participant in match.participants.all():
        lobby.mark_ready(match.pk, participant.player)
    lobby.void_live(
        Match.objects.get(pk=match.pk), source="staff", actor=None, reason="test", requeue=True
    )
    names = _names(room)
    assert names[-1] == later.display_name  # The lobby's players are ahead of a later joiner.
    assert set(names[:-1]) == {player.display_name for player in players}


@pytest.mark.django_db
def test_prio_shows_your_own_place_and_hold(room: Community, clock: Clock) -> None:
    ann, bob, cal = make_player(1), make_player(2), make_player(3)
    _queue(room, [ann, bob])
    place = prio.place_of(room.pk, bob.discord_user_id)
    assert place is not None and (place.position, place.total) == (2, 2)
    text = place_text(place, 7002)
    assert "**#2** of 2" in text and "<t:" in text and ":R>" in text
    queue.leave(room.pk, ann)
    held = prio.place_of(room.pk, ann.discord_user_id)
    assert held is not None and held.held_until is not None
    assert "is held until" in place_text(held, 7002)
    assert prio.place_of(room.pk, cal.discord_user_id) is None
    assert "not in the queue" in place_text(None, 7002) and "<#7002>" in place_text(None, 7002)


@pytest.mark.django_db
def test_nothing_is_posted_for_the_list(league: Community) -> None:
    ann = make_player(1)
    queue.join(league.pk, ann)
    queue.leave(league.pk, ann)
    kinds = set(OutboxEffect.objects.values_list("kind", flat=True))
    assert not {"render_prio", "delete_prio_message"} & kinds
    assert _names(league) == [ann.display_name]


@pytest.mark.django_db
def test_a_match_in_another_server_doesnt_take_you_off_this_list(room: Community) -> None:
    from league.services import community as community_service

    other = community_service.ensure(1234, "Another server")
    players = [make_player(n) for n in range(1, 13)]
    queue.join(room.pk, players[0])
    _queue(other, players[1:])  # Not a full lobby over there, so nothing pops.
    assert _names(room) == [players[0].display_name]


# --- With the outbox ------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_the_prio_command_answers_only_the_caller(wired: Community) -> None:  # noqa: F811
    from tests.test_handlers import fake_interaction, replies, run_command

    ann = make_player(1)
    queue.join(wired.pk, ann)
    interaction = fake_interaction(ann)
    run_command(prio_commands.prio_command, interaction)
    assert "**#1** of 1" in replies(interaction)[0]
    assert interaction.followup.send.call_args.kwargs.get("ephemeral") is True


@pytest.mark.django_db(transaction=True)
def test_sitting_in_the_waiting_room_puts_nobody_on(wired: Community) -> None:  # noqa: F811
    from tests.test_bot import WAITING_ROOM

    gateway = FakeGateway()
    gateway.voice.setdefault(WAITING_ROOM, set()).update({1, 2, 3})
    drain(gateway)
    assert _names(wired) == []
