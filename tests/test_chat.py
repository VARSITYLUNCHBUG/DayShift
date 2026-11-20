"""The match chats: which one a player sees when, who can read it, and what a message may be."""

from __future__ import annotations

import re
from datetime import timedelta

import pytest
from django.utils import timezone

from league.domain.engine import Status
from league.domain.errors import InvalidAction, NotAllowed, StaleAction
from league.models import ChatMessage, ChatScope, Community, Match, MatchParticipant, Player
from league.models.matches import MatchKind
from league.services import chat, results, scrims, subs
from league.web.live import schema, snapshots
from tests.conftest import make_player
from tests.helpers import (
    fresh,
    image,
    ready_all,
    run_player_draft,
    to_champion_draft,
    to_in_progress,
    vote_captains,
)

pytestmark = pytest.mark.django_db

SCRIM_CHANNEL = 8200


def _player(match: Match, team: str, captain: bool = False) -> Player:
    row = (
        match.participants.filter(removed_reason="", team=team, is_captain=captain)
        .select_related("player")
        .order_by("id")
        .first()
    )
    assert row is not None
    return row.player


def _undrafted(match: Match) -> Player:
    row = match.participants.filter(removed_reason="", team="").order_by("id").first()
    assert row is not None
    return row.player


def _seen(match: Match, viewer: Player | None) -> schema.MatchSnap:
    body = snapshots.build_match(match.pk)
    assert body is not None
    return snapshots.project_match(body, viewer.pk if viewer else None)


def _said(snap: schema.MatchSnap) -> list[schema.ChatLine]:
    """The players' messages, without the system lines between them."""
    assert snap.chat is not None
    return [line for line in snap.chat.messages if isinstance(line, schema.ChatLine)]


def _bodies(snap: schema.MatchSnap) -> list[str]:
    return [line.body for line in _said(snap)]


def _system(snap: schema.MatchSnap) -> list[str]:
    assert snap.chat is not None
    return [line.body for line in snap.chat.messages if isinstance(line, schema.SystemLine)]


# --- Which chat, when -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (Status.READY_CHECK, None),
        (Status.CAPTAIN_PHASE, ("lobby", True)),
        (Status.CAPTAIN_CHECKIN, ("lobby", True)),
        (Status.PLAYER_DRAFT, ("lobby", True)),
        (Status.COINFLIP, ("team", True)),
        (Status.CHAMPION_DRAFT, ("team", True)),
        (Status.LOBBY_CODE, ("team", True)),
        (Status.IN_PROGRESS, ("team", True)),
        (Status.AWAITING_CONFIRMATION, ("team", False)),
        (Status.DISPUTED, ("team", False)),
        (Status.COMPLETED, None),
        (Status.VOIDED, None),
    ],
)
def test_the_ranked_chat_follows_the_status(status: str, expected: tuple[str, bool] | None) -> None:
    room = chat.room(MatchKind.RANKED, status)
    assert (None if room is None else (room.kind, room.open)) == expected
    if room is not None:
        assert (room.closed_reason is None) == room.open


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (Status.CAPTAIN_CLAIM, None),
        (Status.COINFLIP, None),
        (Status.READY_TO_DRAFT, None),
        (Status.CHAMPION_DRAFT, ("team", True)),
        (Status.DRAFTED, None),
        (Status.VOIDED, None),
    ],
)
def test_a_scrim_has_team_chat_in_its_hero_draft_only(
    status: str, expected: tuple[str, bool] | None
) -> None:
    room = chat.room(MatchKind.SCRIM, status)
    assert (None if room is None else (room.kind, room.open)) == expected


def test_messages_are_cleaned_to_plain_lines() -> None:
    assert chat.clean("  hi\tthere\x00\x1b[31m  ") == "hithere[31m"
    assert chat.clean("one\r\ntwo\n\nthree") == "one\ntwo\n\nthree"
    assert chat.clean("<b>bold</b> & 'quotes'") == "<b>bold</b> & 'quotes'"  # Text, as typed.
    assert chat.clean("\n \x07 \n") == ""


# --- The lobby chat ---------------------------------------------------------------------------


def test_the_lobby_chat_reaches_the_whole_roster_and_nobody_else(popped: Match) -> None:
    match = vote_captains(ready_all(popped))
    assert match.status == Status.PLAYER_DRAFT
    captain, waiting = _player(match, "A", captain=True), _undrafted(match)
    chat.send(match.pk, captain, "gl hf")
    chat.send(match.pk, waiting, "  pick me\r\nplease  ")
    for viewer in (captain, waiting, _player(match, "B", captain=True)):
        seen = _seen(match, viewer)
        assert seen.chat is not None and seen.chat.scope == "lobby" and seen.chat.open
        assert _bodies(seen) == ["gl hf", "pick me\nplease"]
        first, second = _said(seen)
        assert (first.player_id, first.name, first.team) == (
            str(captain.pk),
            captain.display_name,
            "A",
        )
        assert (second.player_id, second.team) == (str(waiting.pk), None)  # Not drafted yet.
    for outsider in (make_player(50), None):
        seen = _seen(match, outsider)
        assert seen.chat is None
        assert "pick me" not in seen.model_dump_json()


def test_the_lobby_chat_is_replaced_by_the_team_chat_at_the_coinflip(popped: Match) -> None:
    match = vote_captains(ready_all(popped))
    chat.send(match.pk, _player(match, "A", captain=True), "lobby line")
    match = run_player_draft(match)
    assert match.status == Status.COINFLIP
    seen = _seen(match, _player(match, "A"))
    assert seen.chat is not None and seen.chat.scope == "team" and seen.chat.open
    assert _bodies(seen) == []
    assert ChatMessage.objects.filter(match=match, scope=ChatScope.LOBBY).count() == 1


def test_there_is_no_chat_in_the_ready_check(popped: Match, players: list[Player]) -> None:
    assert _seen(popped, players[0]).chat is None
    with pytest.raises(StaleAction):
        chat.send(popped.pk, players[0], "anyone?")


# --- The team chats ---------------------------------------------------------------------------


def _both_teams_talk(match: Match) -> tuple[Player, Player]:
    a, b = _player(match, "A"), _player(match, "B")
    chat.send(match.pk, a, "A only")
    chat.send(match.pk, _player(match, "B", captain=True), "B only")
    chat.send(match.pk, b, "B again")
    return a, b


def test_each_team_reads_only_its_own_chat(popped: Match) -> None:
    match = to_champion_draft(popped)
    a, b = _both_teams_talk(match)
    for viewer in (a, _player(match, "A", captain=True)):
        assert _bodies(_seen(match, viewer)) == ["A only"]
    for viewer in (b, _player(match, "B", captain=True)):
        assert _bodies(_seen(match, viewer)) == ["B only", "B again"]
    for outsider in (make_player(50), None):
        seen = _seen(match, outsider)
        assert seen.chat is None
        text = seen.model_dump_json()
        assert "A only" not in text and "B only" not in text
    assert "B only" not in _seen(match, a).model_dump_json()


def test_a_subbed_out_player_loses_the_team_chat_and_the_sub_gets_it(popped: Match) -> None:
    match = to_in_progress(popped)
    leaving = _player(match, "A")
    chat.send(match.pk, leaving, "brb, have to go")
    request = subs.request_sub_out(match.pk, leaving, leaving.pk)
    newcomer = make_player(40)
    offer = subs.invite_sub(request.pk, leaving, newcomer.discord_user_id, "P40")
    subs.answer_offer(offer.pk, newcomer, accept=True)
    assert MatchParticipant.objects.get(match=match, player=leaving).removed_reason
    gone = _seen(match, leaving)
    assert gone.chat is None and "have to go" not in gone.model_dump_json()
    with pytest.raises(NotAllowed):
        chat.send(match.pk, leaving, "still here?")
    joined = _seen(match, newcomer)
    assert _bodies(joined) == ["brb, have to go"]  # The leaver's lines stay for the team.
    chat.send(match.pk, newcomer, "hi all")
    assert _bodies(_seen(match, _player(match, "A", captain=True)))[-1] == "hi all"


def test_the_team_chat_is_read_only_once_the_game_ends_then_gone(popped: Match) -> None:
    match = to_in_progress(popped)
    a, _ = _both_teams_talk(match)
    captain = _player(match, "A", captain=True)
    results.submit_report(match.pk, captain, "A", image(1))
    match = fresh(match)
    assert match.status == Status.AWAITING_CONFIRMATION
    seen = _seen(match, a)
    assert seen.chat is not None and not seen.chat.open
    assert seen.chat.closed_reason == chat.TEAM_CLOSED
    assert _bodies(seen) == ["A only"]
    with pytest.raises(StaleAction) as refused:
        chat.send(match.pk, a, "gg")
    assert refused.value.message == chat.TEAM_CLOSED
    results.confirm(match.pk, _player(match, "B", captain=True))
    assert fresh(match).status == Status.COMPLETED
    assert _seen(match, a).chat is None


def test_a_scrim_captains_chat_in_its_hero_draft(league: Community) -> None:
    match = scrims.start_claim(league.pk, SCRIM_CHANNEL, make_player(44))
    hk, am = make_player(45), make_player(46)
    scrims.claim_captain(match.pk, hk, "hk")
    assert _seen(match, hk).chat is None
    scrims.claim_captain(match.pk, am, "am")
    assert fresh(match).status == Status.CHAMPION_DRAFT
    chat.send(match.pk, hk, "ban the frog")
    assert _bodies(_seen(match, hk)) == ["ban the frog"]
    assert _bodies(_seen(match, am)) == []
    assert _seen(match, make_player(47)).chat is None


# --- What a message may be --------------------------------------------------------------------


def test_an_empty_or_long_message_is_refused_in_words(popped: Match) -> None:
    match = vote_captains(ready_all(popped))
    player = _undrafted(match)
    with pytest.raises(InvalidAction) as empty:
        chat.send(match.pk, player, " \n\x00 ")
    assert empty.value.message == "Write something first."
    with pytest.raises(InvalidAction) as long:
        chat.send(match.pk, player, "x" * 501)
    assert long.value.message == "Keep it to 500 characters."
    chat.send(match.pk, player, "x" * 500 + "   ")
    assert ChatMessage.objects.get(match=match).body == "x" * 500


def test_outsiders_cant_post(popped: Match) -> None:
    match = vote_captains(ready_all(popped))
    with pytest.raises(NotAllowed):
        chat.send(match.pk, make_player(50), "let me in")


def test_five_messages_in_ten_seconds_then_slow_down(popped: Match) -> None:
    match = vote_captains(ready_all(popped))
    player, other = _undrafted(match), _player(match, "A", captain=True)
    for number in range(5):
        chat.send(match.pk, player, f"line {number}")
    with pytest.raises(InvalidAction) as refused:
        chat.send(match.pk, player, "one more")
    assert refused.value.message == "Slow down a little."
    chat.send(match.pk, other, "someone else may")  # The limit is per player.
    ChatMessage.objects.filter(player=player).update(
        created_at=timezone.now() - timedelta(seconds=11)
    )
    chat.send(match.pk, player, "and again")


def test_a_message_bumps_the_match(popped: Match) -> None:
    match = vote_captains(ready_all(popped))
    version = fresh(match).version
    chat.send(match.pk, _undrafted(match), "hello")
    assert fresh(match).version == version + 1


def test_a_chat_shows_its_last_hundred_lines_oldest_first(popped: Match) -> None:
    match = vote_captains(ready_all(popped))
    player = _undrafted(match)
    ChatMessage.objects.bulk_create(
        ChatMessage(match=match, scope=ChatScope.LOBBY, player=player, body=f"line {number}")
        for number in range(105)
    )
    seen = _seen(match, player)
    assert _bodies(seen) == [f"line {number}" for number in range(5, 105)]
    assert _said(seen)[0].at.tzinfo is not None


# --- System lines -----------------------------------------------------------------------------


def test_the_lobby_chat_says_who_captains_and_who_was_picked(popped: Match) -> None:
    match = vote_captains(ready_all(popped))
    captains = {team: _player(match, team, captain=True).display_name for team in "AB"}
    match = run_player_draft(match)
    match.status = Status.PLAYER_DRAFT  # Read the lobby chat as it stood in the draft.
    lines = [line.body for line in chat.system_lines(match.pk, ChatScope.LOBBY)]
    assert lines[0] == (
        f"{captains['A']} and {captains['B']} are the captains. The player draft is on."
    )
    picks = lines[1:]
    assert len(picks) == match.draft_actions.filter(action="player_pick").count() > 0
    assert all(" picked " in line or line.startswith("Time ran out") for line in picks)
    # The team chats get none of it.
    assert all(
        "captains" not in line.body and "player draft" not in line.body
        for line in chat.system_lines(match.pk, ChatScope.TEAM_A)
    )


def test_the_team_chats_get_the_hero_draft_and_the_game(popped: Match) -> None:
    match = to_in_progress(popped)
    seen = _seen(match, _player(match, "A"))
    lines = _system(seen)
    assert lines[0] == "The hero draft is on." and lines[-1] == "The game is on. Good luck."
    heroes = match.draft_actions.exclude(action="player_pick").count()
    assert sum(" banned " in line or " picked " in line for line in lines) == heroes
    assert _system(_seen(match, _player(match, "B"))) == lines  # The board is public anyway.
    assert not any(re.search(r" picked P\d+\.$", line) for line in lines)  # No player picks.
    assert _seen(match, make_player(50)).chat is None  # Outsiders still see no chat.


def test_a_sub_is_announced_in_the_chat_of_the_phase_it_came_in(popped: Match) -> None:
    match = to_in_progress(popped)
    leaving = _player(match, "A")
    request = subs.request_sub_out(match.pk, leaving, leaving.pk)
    newcomer = make_player(40)
    offer = subs.invite_sub(request.pk, leaving, newcomer.discord_user_id, "P40")
    subs.answer_offer(offer.pk, newcomer, accept=True)
    line = f"P40 came in for {leaving.display_name}."
    assert line in _system(_seen(match, newcomer))
    assert line not in [x.body for x in chat.system_lines(match.pk, ChatScope.LOBBY)]


def test_system_lines_sit_between_the_messages_in_time_order(popped: Match) -> None:
    match = to_champion_draft(popped)
    chat.send(match.pk, _player(match, "A"), "ban their best")
    seen = _seen(match, _player(match, "A"))
    assert seen.chat is not None
    times = [line.at for line in seen.chat.messages]
    assert times == sorted(times)
    assert {line.kind for line in seen.chat.messages} == {"message", "system"}
