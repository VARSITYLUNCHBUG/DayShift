"""Team voice comes from a reusable pool per server: Discord caps how many channels a server can
create in a day, and a day of matches each making two hit it (2026-11-20)."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest
from django.db import connections

from bot.db import db
from league.models import Community, Match, OutboxEffect, SubOffer, VoiceChannelSlot
from league.models.matches import ResourceKind
from league.models.outbox import EffectStatus
from league.services import community, effects, queue, runtime, voice_pool
from tests.conftest import Clock, make_player
from tests.helpers import (
    finish,
    fresh,
    run_player_draft,
    to_champion_draft,
    to_in_progress,
    vote_captains,
)
from tests.helpers import ready_all as ready_up
from tests.test_bot import WAITING_ROOM, FakeGateway, drain, resource

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def wired(transactional_db: None) -> Iterator[Community]:
    row = community.ensure(guild_id=999, name="Test")
    community.save_wiring(row.pk, waiting_room_channel_id=WAITING_ROOM)
    row.refresh_from_db()
    yield row
    asyncio.run(db(connections.close_all))


def new_match(wired: Community, gateway: FakeGateway, first: int) -> Match:
    """Twelve new players queue and pop a match."""
    existing = set(Match.objects.values_list("pk", flat=True))
    for player in [make_player(n) for n in range(first, first + 12)]:
        queue.join(wired.pk, player)
    drain(gateway)
    return Match.objects.exclude(pk__in=existing).get()


def team_channels(match: Match) -> tuple[int, int]:
    return resource(match, ResourceKind.TEAM_A_VOICE), resource(match, ResourceKind.TEAM_B_VOICE)


def team_ids(match: Match, team: str) -> set[int]:
    return set(
        match.participants.filter(team=team, is_active=True).values_list(
            "player__discord_user_id", flat=True
        )
    )


def play_out(match: Match, gateway: FakeGateway) -> Match:
    match = finish(to_in_progress(match), "A")
    drain(gateway)
    return match


def assert_nothing_failed() -> None:
    failed = OutboxEffect.objects.filter(status=EffectStatus.FAILED)
    assert not failed.exists(), list(failed.values_list("kind", "last_error"))


def test_the_next_match_reuses_the_pool_with_no_new_channels(wired: Community) -> None:
    gateway = FakeGateway()
    first = to_champion_draft(new_match(wired, gateway, 1))
    drain(gateway)
    channels = team_channels(first)
    assert gateway.voice_created == ["Team Voice 1", "Team Voice 2"]
    captain = first.captain_of("A").player.display_name
    assert gateway.statuses[channels[0]] == f"Match {first.pk} · {captain}'s Team"
    play_out(first, gateway)
    assert not set(channels) & set(gateway.deleted)

    second = to_champion_draft(new_match(wired, gateway, 20))
    drain(gateway)
    assert gateway.voice_created == ["Team Voice 1", "Team Voice 2"]  # Nothing new was made.
    assert team_channels(second) == channels
    # The new teams are let in by overwrite, and the status says whose channel it is now.
    assert team_ids(second, "A") <= {user for ch, user in gateway.granted if ch == channels[0]}
    captain = second.captain_of("B").player.display_name
    assert gateway.statuses[channels[1]] == f"Match {second.pk} · {captain}'s Team"
    # Players in the Waiting Room are moved into the borrowed channels as before.
    assert effects.on_voice_join(min(team_ids(second, "A")), WAITING_ROOM) == (999, channels[0])
    play_out(second, gateway)
    assert voice_pool.free_channels(wired.pk) == list(channels)
    assert_nothing_failed()


def test_two_matches_at_once_borrow_four_channels(wired: Community) -> None:
    gateway = FakeGateway()
    first = to_champion_draft(new_match(wired, gateway, 1))
    second = to_champion_draft(new_match(wired, gateway, 20))
    drain(gateway)
    assert len(set(team_channels(first)) | set(team_channels(second))) == 4
    assert sorted(gateway.voice_created) == [f"Team Voice {n}" for n in range(1, 5)]


def test_a_restart_hands_its_channels_back_for_the_successor(
    wired: Community, clock: Clock
) -> None:
    from league.services import deadlines, subs

    gateway = FakeGateway()
    match = to_champion_draft(new_match(wired, gateway, 1))
    drain(gateway)
    channels = team_channels(match)
    spare = make_player(40)
    queue.join(wired.pk, spare)
    leaving = match.participants.filter(is_active=True, is_captain=False).first().player
    subs.request_sub_out(match.pk, leaving, leaving.pk)
    drain(gateway)
    clock.advance(match.mode.subs.max_wait_seconds + 1)
    deadlines.tick()
    drain(gateway)
    successor = Match.objects.get(restarted_from=match)
    assert not set(channels) & set(gateway.deleted)
    assert sorted(voice_pool.free_channels(wired.pk)) == sorted(channels)

    offer = SubOffer.objects.get(player=spare)
    subs.answer_offer(offer.pk, spare, True)
    drain(gateway)
    successor = to_champion_draft(fresh(successor))
    drain(gateway)
    assert sorted(team_channels(successor)) == sorted(channels)
    assert gateway.voice_created == ["Team Voice 1", "Team Voice 2"]
    assert_nothing_failed()


def test_a_pooled_channel_deleted_by_hand_leaves_the_pool(wired: Community) -> None:
    gateway = FakeGateway()
    first = to_champion_draft(new_match(wired, gateway, 1))
    drain(gateway)
    gone, kept = team_channels(first)
    play_out(first, gateway)
    gateway.deleted.append(gone)  # Staff deleted it while it sat free.

    second = to_champion_draft(new_match(wired, gateway, 20))
    drain(gateway)
    a, b = team_channels(second)
    assert a == kept  # The next free one.
    assert b not in (gone, kept)  # The pool was short, so one more was made, in the gap.
    assert gateway.voice_created[-1] == "Team Voice 1"
    assert not VoiceChannelSlot.objects.filter(discord_id=gone).exists()
    assert VoiceChannelSlot.objects.count() == 2
    assert_nothing_failed()


def test_a_channel_deleted_mid_match_is_dropped_at_cleanup(wired: Community) -> None:
    gateway = FakeGateway()
    match = to_champion_draft(new_match(wired, gateway, 1))
    drain(gateway)
    gone, kept = team_channels(match)
    gateway.deleted.append(gone)
    gateway.voice.pop(gone, None)
    play_out(match, gateway)
    assert voice_pool.free_channels(wired.pk) == [kept]
    assert effects.resource_id(match.pk, ResourceKind.TEAM_A_VOICE) is None
    assert_nothing_failed()


def test_voice_setup_after_a_crash_lets_the_team_in_without_a_new_channel(
    wired: Community,
) -> None:
    """The bot went down after claiming team A's channel but before letting the team in: the
    retry finishes the job on the same channel."""
    gateway = FakeGateway()
    first = to_champion_draft(new_match(wired, gateway, 1))
    drain(gateway)
    channels = team_channels(first)
    play_out(first, gateway)

    second = run_player_draft(vote_captains(ready_up(new_match(wired, gateway, 20))))
    assert voice_pool.claim(second.pk, ResourceKind.TEAM_A_VOICE).channel_id == channels[0]
    gateway.granted.clear()
    drain(gateway)
    assert team_channels(second) == channels
    assert gateway.voice_created == ["Team Voice 1", "Team Voice 2"]
    granted = {user for ch, user in gateway.granted if ch == channels[0]}
    assert team_ids(fresh(second), "A") <= granted


def test_someone_left_in_a_free_channel_keeps_it_out_of_the_next_match(
    wired: Community,
) -> None:
    """Someone who wandered into a free channel (or was never moved out, in a server with no
    Waiting Room) keeps it out of the next match, which passes it over."""
    gateway = FakeGateway()
    first = to_champion_draft(new_match(wired, gateway, 1))
    drain(gateway)
    sat_in, free = team_channels(first)
    play_out(first, gateway)
    gateway.voice[sat_in] = {12345}

    second = to_champion_draft(new_match(wired, gateway, 20))
    drain(gateway)
    assert sat_in not in team_channels(second)
    assert free in team_channels(second)


def test_a_full_pool_falls_back_to_a_one_off_channel(wired: Community) -> None:
    runtime.update(wired, max_concurrent_matches=1)
    for number, channel_id in ((1, 801), (2, 802)):
        VoiceChannelSlot.objects.create(community=wired, number=number, discord_id=channel_id)
    gateway = FakeGateway()
    gateway.voice[801] = {12345}
    match = to_champion_draft(new_match(wired, gateway, 1))
    drain(gateway)
    a, b = team_channels(match)
    assert a == 802  # The one free channel; 801 has someone in it.
    captain = match.captain_of("B").player.display_name
    assert gateway.voice_created == [f"Match {match.pk} · {captain}'s Team"]
    assert not voice_pool.is_pooled(b)
    play_out(match, gateway)
    assert b in gateway.deleted  # A one-off goes after its match, as before the pool.
    assert 802 not in gateway.deleted
    assert VoiceChannelSlot.objects.count() == 2


def test_the_pool_shrinks_when_fewer_matches_can_run(wired: Community) -> None:
    for number, channel_id in ((1, 801), (2, 802), (3, 803), (4, 804)):
        VoiceChannelSlot.objects.create(community=wired, number=number, discord_id=channel_id)
    gateway = FakeGateway()
    gateway.voice[801] = {12345}
    gateway.voice[802] = {12346}
    match = to_champion_draft(new_match(wired, gateway, 1))
    drain(gateway)
    assert team_channels(match) == (803, 804)
    runtime.update(wired, max_concurrent_matches=1)
    play_out(match, gateway)
    # Two channels are all one match needs: the highest numbers go.
    assert {803, 804} <= set(gateway.deleted)
    assert list(VoiceChannelSlot.objects.values_list("number", flat=True)) == [1, 2]
    assert_nothing_failed()


def test_opening_match_voice_reaches_pooled_channels(wired: Community) -> None:
    gateway = FakeGateway()
    first = to_champion_draft(new_match(wired, gateway, 1))
    drain(gateway)
    channels = team_channels(first)
    assert gateway.open_voice[channels[0]] is False
    play_out(first, gateway)
    runtime.update(wired, open_match_voice=True)

    second = to_champion_draft(new_match(wired, gateway, 20))
    drain(gateway)
    assert team_channels(second) == channels
    assert all(gateway.open_voice[channel] for channel in channels)
    assert all(slot.open_to_everyone for slot in VoiceChannelSlot.objects.all())


def test_a_claimed_channel_deleted_before_the_retry_is_swapped_for_another(
    wired: Community,
) -> None:
    gateway = FakeGateway()
    first = to_champion_draft(new_match(wired, gateway, 1))
    drain(gateway)
    gone, kept = team_channels(first)
    play_out(first, gateway)

    second = run_player_draft(vote_captains(ready_up(new_match(wired, gateway, 20))))
    assert voice_pool.claim(second.pk, ResourceKind.TEAM_A_VOICE).channel_id == gone
    gateway.deleted.append(gone)  # Deleted by hand while the bot was down.
    drain(gateway)
    assert team_channels(second)[0] == kept
    assert not voice_pool.is_pooled(gone)
    assert_nothing_failed()


def test_the_first_eight_channels_are_made_ahead_of_any_match(wired: Community) -> None:
    gateway = FakeGateway()
    voice_pool.request_fill(wired)
    drain(gateway)
    assert gateway.voice_created == [f"Team Voice {n}" for n in range(1, 9)]
    assert len(voice_pool.free_channels(wired.pk)) == 8
    # Made empty: nobody is let in until a match borrows one.
    assert all(not gateway.members_seen[c] for c in voice_pool.free_channels(wired.pk))

    match = to_champion_draft(new_match(wired, gateway, 1))
    drain(gateway)
    assert len(gateway.voice_created) == 8  # The match borrowed two; none was made.
    numbers = [VoiceChannelSlot.objects.get(discord_id=c).number for c in team_channels(match)]
    assert numbers == [1, 2]
    assert team_ids(match, "A") <= {u for c, u in gateway.granted if c == team_channels(match)[0]}
    voice_pool.request_fill(wired)
    drain(gateway)
    assert len(gateway.voice_created) == 8  # Already full: a second fill makes nothing.


def test_the_first_fill_stops_at_what_the_server_can_use(wired: Community) -> None:
    runtime.update(wired, max_concurrent_matches=2)
    gateway = FakeGateway()
    voice_pool.request_fill(wired)
    drain(gateway)
    assert len(gateway.voice_created) == 4


def test_free_channels_are_hidden_and_shown_while_a_match_has_them(wired: Community) -> None:
    gateway = FakeGateway()
    voice_pool.request_fill(wired)
    drain(gateway)
    assert set(voice_pool.free_channels(wired.pk)) == gateway.hidden  # Made hidden.

    match = to_champion_draft(new_match(wired, gateway, 1))
    drain(gateway)
    channels = team_channels(match)
    assert not set(channels) & gateway.hidden  # Taken: shown to the players and PUGs role.
    assert len(gateway.hidden) == 6

    play_out(match, gateway)
    assert set(channels) <= gateway.hidden  # Back in the pool: hidden again.
    assert len(gateway.hidden) == 8
