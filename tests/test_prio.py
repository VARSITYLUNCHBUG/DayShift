"""The voice priority list (/priolist): it follows the Waiting Room and the match lifecycle."""

from __future__ import annotations

import pytest

from bot.renderers.prio import prio_text, render_prio
from league.models import Community, Match, OutboxEffect, PrioEntry
from league.models.outbox import EffectStatus
from league.services import deadlines, lobby, prio, queue
from tests.conftest import Clock, make_player
from tests.helpers import finish, to_in_progress
from tests.test_bot import (
    WAITING_ROOM,
    FakeGateway,
    assert_within_limits,
    drain,
    resource,
    wired,  # noqa: F401  (a fixture)
)

ELSEWHERE = 7999


def _names(community: Community) -> list[str]:
    return [line.name for line in prio.prio_view(community.pk).lines]


def _join(community: Community, user_id: int, name: str = "") -> None:
    prio.on_voice_state(
        community.pk, WAITING_ROOM, user_id, name or f"U{user_id}", None, WAITING_ROOM
    )


def _leave(community: Community, user_id: int) -> None:
    prio.on_voice_state(community.pk, WAITING_ROOM, user_id, "", WAITING_ROOM, ELSEWHERE)


@pytest.fixture
def room(league: Community) -> Community:
    Community.objects.filter(pk=league.pk).update(
        waiting_room_channel_id=WAITING_ROOM, prio_channel_id=7100
    )
    league.refresh_from_db()
    return league


@pytest.mark.django_db
def test_longest_wait_first_and_grace_keeps_your_place(room: Community, clock: Clock) -> None:
    _join(room, 1, "Ann")
    clock.advance(30)
    _join(room, 2, "Bob")
    assert _names(room) == ["Ann", "Bob"]
    _leave(room, 1)
    entry = PrioEntry.objects.get(discord_user_id=1)
    assert entry.grace_until is not None
    clock.advance(prio.GRACE_SECONDS - 10)
    _join(room, 1, "Ann")  # Back in time: the place is kept.
    assert _names(room) == ["Ann", "Bob"]
    assert PrioEntry.objects.get(discord_user_id=1).grace_until is None


@pytest.mark.django_db
def test_grace_runs_out(room: Community, clock: Clock) -> None:
    _join(room, 1, "Ann")
    _join(room, 2, "Bob")
    _leave(room, 1)
    clock.advance(prio.GRACE_SECONDS + 1)
    assert deadlines.tick() >= 1
    assert _names(room) == ["Bob"]
    _join(room, 1, "Ann")  # Too late: the back of the list.
    assert _names(room) == ["Bob", "Ann"]


@pytest.mark.django_db
def test_moves_elsewhere_do_not_count(room: Community) -> None:
    prio.on_voice_state(room.pk, WAITING_ROOM, 1, "Ann", None, ELSEWHERE)
    prio.on_voice_state(room.pk, WAITING_ROOM, 1, "Ann", ELSEWHERE, ELSEWHERE + 1)
    assert _names(room) == []


@pytest.mark.django_db
def test_a_popped_lobby_takes_its_players_off(room: Community) -> None:
    players = [make_player(n) for n in range(1, 14)]
    for player in players:
        _join(room, player.discord_user_id, player.display_name)
    for player in players[:12]:
        queue.join(room.pk, player)  # The twelfth pops a lobby.
    assert _names(room) == [players[12].display_name]


@pytest.mark.django_db
def test_a_ready_check_replacement_comes_off(room: Community, clock: Clock) -> None:
    players = [make_player(n) for n in range(1, 14)]
    for player in players[:12]:
        queue.join(room.pk, player)
    match = Match.objects.get()
    spare = players[12]
    queue.join(room.pk, spare)
    _join(room, spare.discord_user_id, spare.display_name)
    for participant in match.participants.exclude(player=players[0]):
        lobby.mark_ready(match.pk, participant.player)
    clock.advance(3600)
    deadlines.tick()  # players[0] missed the ready check; the spare is offered the place.
    from league.models import SubOffer
    from league.services import subs

    offer = SubOffer.objects.get(player=spare)
    assert offer.source == "prio"  # In the Waiting Room, so asked before the queue.
    subs.answer_offer(offer.pk, spare, True)
    assert match.participants.filter(player=spare, is_active=True).exists()
    assert _names(room) == []


@pytest.mark.django_db
def test_a_sub_comes_off_the_list(room: Community) -> None:
    players = [make_player(n) for n in range(1, 13)]
    for player in players:
        queue.join(room.pk, player)
    match = to_in_progress(Match.objects.get())
    sub = make_player(40)
    _join(room, sub.discord_user_id, sub.display_name)
    leaving = match.participants.exclude(is_captain=True).filter(is_active=True).first()
    assert leaving is not None
    lobby.swap_player(match, leaving, sub, ready=True)
    assert _names(room) == []


@pytest.mark.django_db
def test_voice_moves_while_matched_are_ignored(room: Community) -> None:
    players = [make_player(n) for n in range(1, 13)]
    for player in players:
        queue.join(room.pk, player)
    _join(room, players[0].discord_user_id)
    _leave(room, players[0].discord_user_id)
    assert not PrioEntry.objects.exists()


@pytest.mark.django_db
def test_reconcile_catches_up_with_the_room(room: Community) -> None:
    _join(room, 1, "Ann")
    _join(room, 2, "Bob")
    player = make_player(3)
    prio.reconcile(room.pk, {2: "Bob", player.discord_user_id: ""})
    lines = {line.discord_user_id: line for line in prio.prio_view(room.pk).lines}
    assert lines[1].grace_until is not None  # Left while the bot wasn't looking.
    assert lines[2].grace_until is None
    assert lines[player.discord_user_id].name == player.display_name  # Named from its record.


@pytest.mark.django_db
def test_the_list_renders_with_timestamps_and_coalesces(room: Community) -> None:
    for n in range(1, 40):
        _join(room, n, f"Player number {n} with a long name")
    _leave(room, 3)
    text = prio_text(prio.prio_view(room.pk))
    assert "<t:" in text and ":R>" in text
    assert "⏳" in text and "and 9 more" in text
    assert_within_limits(render_prio(prio.prio_view(room.pk)))
    pending = OutboxEffect.objects.filter(kind=prio.RENDER_KIND, status=EffectStatus.PENDING)
    assert pending.count() == 1


@pytest.mark.django_db
def test_no_display_means_no_renders(league: Community) -> None:
    prio.on_voice_state(league.pk, WAITING_ROOM, 1, "Ann", None, WAITING_ROOM)
    assert not OutboxEffect.objects.filter(kind=prio.RENDER_KIND).exists()
    assert _names(league) == ["Ann"]


# --- With the outbox ------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_after_a_match_everyone_in_the_room_goes_on_the_back(wired: Community) -> None:  # noqa: F811
    prio.set_display(wired.pk, 7100)
    gateway = FakeGateway()
    waiting_first = make_player(30)
    _join(wired, waiting_first.discord_user_id, waiting_first.display_name)
    players = [make_player(n) for n in range(1, 13)]
    for player in players:
        queue.join(wired.pk, player)
    drain(gateway)
    match = Match.objects.get()
    lobby_voice = resource(match, "lobby_voice")
    gateway.voice[lobby_voice] = {p.discord_user_id for p in players[:11]}
    # One player went back to the Waiting Room mid-match: no event will put them on the list.
    gateway.voice.setdefault(WAITING_ROOM, set()).add(players[11].discord_user_id)
    gateway.names[players[11].discord_user_id] = players[11].display_name
    finish(to_in_progress(match), winner="A")
    drain(gateway)
    names = _names(wired)
    assert names[0] == waiting_first.display_name  # Waited all along: still first.
    assert set(names[1:]) == {p.display_name for p in players}
    assert len(names) == 13
    assert gateway.voice[WAITING_ROOM] >= {p.discord_user_id for p in players}


@pytest.mark.django_db(transaction=True)
def test_the_display_is_posted_and_reposted(wired: Community) -> None:  # noqa: F811
    gateway = FakeGateway()
    prio.set_display(wired.pk, 7100)
    drain(gateway)
    wired.refresh_from_db()
    first = wired.prio_message_id
    assert first is not None
    _join(wired, 1, "Ann")
    drain(gateway)
    assert first in gateway.edited
    gateway.messages[7100].remove(first)  # Someone deleted it.
    _join(wired, 2, "Bob")
    drain(gateway)
    wired.refresh_from_db()
    assert wired.prio_message_id not in (None, first)


# --- Review fixes -------------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_match_in_another_server_doesnt_take_you_off_this_list(room: Community) -> None:
    from league.services import community as community_service

    other = community_service.ensure(1234, "Another server")
    players = [make_player(n) for n in range(1, 13)]
    for player in players:
        queue.join(other.pk, player)  # A live match over there.
    _join(room, players[0].discord_user_id, players[0].display_name)
    assert _names(room) == [players[0].display_name]


@pytest.mark.django_db(transaction=True)
def test_an_unloaded_waiting_room_isnt_read_as_empty(wired: Community) -> None:  # noqa: F811
    class Loading(FakeGateway):
        def voice_members(self, guild_id, channel_id):  # type: ignore[no-untyped-def]
            return None  # Discord hasn't sent this server's channels yet.

    _join(wired, 1, "Ann")
    players = [make_player(n) for n in range(10, 22)]
    for player in players:
        queue.join(wired.pk, player)
    gateway = Loading()
    drain(gateway)
    finish(to_in_progress(Match.objects.get()), winner="A")
    drain(gateway)
    assert PrioEntry.objects.get(discord_user_id=1).grace_until is None


@pytest.mark.django_db(transaction=True)
def test_refresh_reposts_and_removes_the_old_list(wired: Community) -> None:  # noqa: F811
    gateway = FakeGateway()
    prio.set_display(wired.pk, 7100)
    drain(gateway)
    wired.refresh_from_db()
    first = wired.prio_message_id
    gateway.chat(7100)  # Chat pushes the list up.
    assert prio.repost(wired.pk)
    drain(gateway)
    wired.refresh_from_db()
    assert wired.prio_message_id not in (None, first)
    assert gateway.messages[7100][-1] == wired.prio_message_id
    assert first not in gateway.messages[7100]


@pytest.mark.django_db(transaction=True)
def test_a_player_who_misses_the_ready_check_goes_back_on(wired: Community) -> None:  # noqa: F811
    gateway = FakeGateway()
    players = [make_player(n) for n in range(1, 13)]
    for player in players:
        gateway.voice.setdefault(WAITING_ROOM, set()).add(player.discord_user_id)
        _join(wired, player.discord_user_id, player.display_name)
        queue.join(wired.pk, player)
    drain(gateway)  # Moved into the lobby, off the list.
    assert _names(wired) == []
    match = Match.objects.get()
    late = players[0]
    for users in gateway.voice.values():
        users.discard(late.discord_user_id)
    gateway.voice[WAITING_ROOM].add(late.discord_user_id)  # Back in the room, no event.
    for participant in match.participants.exclude(player=late):
        lobby.mark_ready(match.pk, participant.player)
    match.deadline_at = match.created_at
    match.save(update_fields=["deadline_at"])
    deadlines.tick()  # They missed it.
    drain(gateway)
    assert late.display_name in _names(wired)


def test_bots_in_the_waiting_room_dont_queue() -> None:
    import asyncio
    from types import SimpleNamespace

    from bot.client import DraftBot

    calls: list[object] = []
    bot = SimpleNamespace(wake_effects=lambda: calls.append("woke"))
    member = SimpleNamespace(bot=True, id=1, guild=SimpleNamespace(id=1), display_name="Music")
    # No database is touched: the test has no database access, so any query would fail.
    asyncio.run(DraftBot._update_prio(bot, member, None, None))  # type: ignore[arg-type]
    assert calls == []
