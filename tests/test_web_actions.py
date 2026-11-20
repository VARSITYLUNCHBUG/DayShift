"""Actions from the players' websocket: each one calls its service as the signed-in player.

Most cases call the registry directly on the test's own thread (`actions.perform`). The socket
cases run the real ASGI app with real NOTIFYs.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import pytest

from league.asyncdb import db
from league.domain import engine
from league.domain.engine import Status
from league.integrations import deadlock_api
from league.models import (
    CaptainVote,
    Community,
    EarlyLeave,
    Match,
    Player,
    PlayerSwap,
    QueueEntry,
    SubOffer,
    SubRequest,
)
from league.models.moderation import PenaltyKind
from league.models.scoreboards import ReadStatus
from league.models.subs import OfferStatus, SubStatus
from league.services import (
    community,
    draft,
    live,
    lobby,
    ocr,
    penalties,
    queue,
    results,
    scrims,
    standing,
    subs,
    swaps,
)
from league.web.live import actions, consumer, hub, schema, snapshots
from league.web.live.actions import BAD_REQUEST, FAILED, Actor, Reply
from tests.conftest import make_player
from tests.helpers import (
    acting_captain,
    fail_api_lobby,
    fresh,
    image,
    ready_all,
    run_champion_draft,
    run_player_draft,
    to_champion_draft,
    to_in_progress,
    vote_captains,
    vote_only,
)
from tests.test_ocr import scoreboard
from tests.web_helpers import (
    Msg,
    close_code,
    listening,
    run,
    serve,
    signed_in,
    snap,
    subscribe,
    until,
)

pytestmark = pytest.mark.django_db

# The contract's "Actions" table, by name: what the frontend may send.
CONTRACT = {
    "queue.join",
    "queue.leave",
    "lobby.ready",
    "lobby.vote",
    "lobby.checkin",
    "draft.pick_player",
    "draft.coinflip",
    "draft.champion",
    "draft.random_champion",
    "draft.lobby_code",
    "draft.api_start",
    "swap.propose",
    "swap.answer",
    "results.confirm",
    "results.dispute",
    "ocr.map_row",
    "early_leave.report",
    "early_leave.answer",
    "subs.options",
    "subs.request",
    "subs.answer_request",
    "subs.cancel",
    "subs.invite",
    "subs.offer_queue",
    "subs.answer_offer",
    "scrims.claim",
    "scrims.start",
}
SCRIM_CHANNEL = 8200


@pytest.fixture(autouse=True)
def web(league: Community, settings: Any) -> Iterator[Community]:
    yield from serve(league, settings)


def act(player: Player, name: str, args: dict[str, Any] | None = None) -> Reply:
    community_id = snapshots.web_community_id()
    assert community_id is not None
    return actions.perform(Actor(player, community_id), name, args or {})


def ok(reply: Reply) -> Reply:
    assert reply.ok, reply.error
    return reply


# --- One case per action ----------------------------------------------------------------------


@dataclass
class Case:
    player: Player
    args: dict[str, Any]
    check: Callable[[Reply], None]


def _non_captain(match: Match, team: str = "") -> Player:
    rows = match.participants.filter(is_active=True, is_captain=False)
    if team:
        rows = rows.filter(team=team)
    return rows.order_by("id").first().player


def _self_sub(match: Match, player: Player) -> SubRequest:
    return subs.request_sub_out(match.pk, player, player.pk)


def _queue_join(league: Community, popped: Match, players: list[Player]) -> Case:
    player = make_player(40)
    return Case(player, {}, lambda r: assert_(QueueEntry.objects.filter(player=player)))


def _queue_leave(league: Community, popped: Match, players: list[Player]) -> Case:
    player = make_player(40)
    queue.join(league.pk, player)
    return Case(player, {}, lambda r: assert_(not QueueEntry.objects.filter(player=player)))


def _ready(league: Community, popped: Match, players: list[Player]) -> Case:
    def check(reply: Reply) -> None:
        assert popped.participants.get(player=players[0]).ready_at is not None
        assert reply.topics == (live.match_topic(popped.pk),)

    return Case(players[0], {"match_id": str(popped.pk)}, check)


def _vote(league: Community, popped: Match, players: list[Player]) -> Case:
    match = ready_all(popped)
    assert match.status == Status.CAPTAIN_PHASE
    chosen = [str(players[1].pk), str(players[2].pk)]
    voters = CaptainVote.objects.filter(voter=players[0])
    return Case(
        players[0],
        {"match_id": str(match.pk), "candidate_ids": chosen},
        lambda r: assert_({str(v.candidate_id) for v in voters} == set(chosen)),
    )


def _checkin(league: Community, popped: Match, players: list[Player]) -> Case:
    match = vote_only(ready_all(popped))
    assert match.status == Status.CAPTAIN_CHECKIN
    captain = match.captain_of("A").player
    return Case(
        captain,
        {"match_id": str(match.pk)},
        lambda r: assert_(match.participants.get(player=captain).checked_in_at is not None),
    )


def _swap_propose(league: Community, popped: Match, players: list[Player]) -> Case:
    match = to_champion_draft(popped)
    give = _non_captain(match, "A")
    take = _non_captain(match, "B")

    def check(reply: Reply) -> None:
        swap = PlayerSwap.objects.get(match=match)
        assert (swap.give_id, swap.take_id) == (give.pk, take.pk)
        assert reply.result == schema.SwapProposed(swap_id=str(swap.pk))

    args = {"match_id": str(match.pk), "give_id": str(give.pk), "take_id": str(take.pk)}
    return Case(match.captain_of("A").player, args, check)


def _swap_answer(league: Community, popped: Match, players: list[Player]) -> Case:
    match = to_champion_draft(popped)
    give = _non_captain(match, "A")
    take = _non_captain(match, "B")
    swap = swaps.propose(match.pk, match.captain_of("A").player, give.pk, take.pk)
    return Case(
        match.captain_of("B").player,
        {"match_id": str(match.pk), "swap_id": str(swap.pk), "accept": True},
        lambda r: assert_(match.participants.get(player=give).team == "B"),
    )


def _pick_player(league: Community, popped: Match, players: list[Player]) -> Case:
    match = vote_captains(ready_all(popped))
    assert match.status == Status.PLAYER_DRAFT
    target = _non_captain(match)
    args = {"match_id": str(match.pk), "step_index": match.step_index, "player_id": str(target.pk)}
    return Case(
        acting_captain(match),
        args,
        lambda r: assert_(match.participants.get(player=target).team in {"A", "B"}),
    )


def _coinflip(league: Community, popped: Match, players: list[Player]) -> Case:
    match = run_player_draft(vote_captains(ready_all(popped)))
    assert match.status == Status.COINFLIP
    winner = match.captain_of(match.coinflip_winner).player
    return Case(
        winner,
        {"match_id": str(match.pk), "choice": engine.HIDDEN_KING},
        lambda r: assert_(fresh(match).status == Status.CHAMPION_DRAFT),
    )


def _champion(league: Community, popped: Match, players: list[Player]) -> Case:
    match = to_champion_draft(popped)
    champion = draft.available_champions(match)[0]
    args = {"match_id": str(match.pk), "step_index": match.step_index, "champion_id": champion}
    return Case(
        acting_captain(match),
        args,
        lambda r: assert_(fresh(match).step_index == match.step_index + 1),
    )


def _random_champion(league: Community, popped: Match, players: list[Player]) -> Case:
    match = to_champion_draft(popped)

    def check(reply: Reply) -> None:
        assert fresh(match).step_index == match.step_index + 1
        assert reply.result is not None
        champion_id = reply.result.model_dump()["champion_id"]
        assert isinstance(champion_id, str)
        assert int(champion_id) not in draft.available_champions(fresh(match))

    args = {"match_id": str(match.pk), "step_index": match.step_index}
    return Case(acting_captain(match), args, check)


def _lobby_code(league: Community, popped: Match, players: list[Player]) -> Case:
    match = fail_api_lobby(run_champion_draft(to_champion_draft(popped)))
    assert match.status == Status.LOBBY_CODE
    return Case(
        match.lobby_code_host,
        {"match_id": str(match.pk), "code": "ABC123"},
        lambda r: assert_(fresh(match).lobby_code == "ABC123"),
    )


def _reported(popped: Match) -> Match:
    match = to_in_progress(popped)
    results.submit_report(match.pk, match.captain_of("A").player, "A", image(1))
    return fresh(match)


def _confirm(league: Community, popped: Match, players: list[Player]) -> Case:
    match = _reported(popped)
    return Case(
        match.captain_of("B").player,
        {"match_id": str(match.pk)},
        lambda r: assert_(fresh(match).status == Status.COMPLETED),
    )


def _dispute(league: Community, popped: Match, players: list[Player]) -> Case:
    match = _reported(popped)
    return Case(
        match.captain_of("B").player,
        {"match_id": str(match.pk), "note": "  We won.  "},
        lambda r: assert_(fresh(match).status == Status.DISPUTED),
    )


def _map_row(league: Community, popped: Match, players: list[Player]) -> Case:
    match = to_in_progress(popped)
    hk = match.hidden_king_team
    for number, row in enumerate(match.participants.filter(team=hk).order_by("id")):
        Player.objects.filter(pk=row.player_id).update(display_name=f"Discord name {number}")
    captain = match.captain_of(hk).player
    results.submit_report(match.pk, captain, hk, image(1))
    submission = match.submissions.order_by("id").first()
    read = ocr.ingest(submission.pk, scoreboard(1))
    assert read.status == ReadStatus.NEEDS_MAPPING
    row = ocr.unmapped_rows(read.pk)[0]
    target = match.participants.filter(team=hk).order_by("id").first()
    args = {"read_id": str(read.pk), "row": row.row, "player_id": str(target.player_id)}

    def check(reply: Reply) -> None:
        assert read.stats.get(row=row.row).player_id == target.player_id
        assert reply.topics == (live.match_topic(match.pk),)

    return Case(captain, args, check)


def _early_report(league: Community, popped: Match, players: list[Player]) -> Case:
    match = to_in_progress(popped)
    leaver = _non_captain(match, "A")
    return Case(
        match.captain_of("A").player,
        {"match_id": str(match.pk), "player_id": str(leaver.pk)},
        lambda r: assert_(EarlyLeave.objects.filter(match=match, leaver=leaver).exists()),
    )


def _early_answer(league: Community, popped: Match, players: list[Player]) -> Case:
    from league.services import early_leave

    match = to_in_progress(popped)
    early_leave.report(match.pk, match.captain_of("A").player, _non_captain(match, "A").pk)
    return Case(
        match.captain_of("B").player,
        {"match_id": str(match.pk), "agree": True},
        lambda r: assert_(fresh(match).status == Status.VOIDED),
    )


def _sub_options(league: Community, popped: Match, players: list[Player]) -> Case:
    def check(reply: Reply) -> None:
        assert reply.result is not None
        assert reply.result.model_dump() == {
            "choices": [{"player_id": str(players[3].pk), "name": "P4", "is_self": True}],
            "game_on": False,
            "dodge": False,
            "strikes": 0,  # Nothing to pay during the ready check.
        }
        assert reply.topics == ()

    return Case(players[3], {"match_id": str(popped.pk)}, check)


def _sub_request(league: Community, popped: Match, players: list[Player]) -> Case:
    def check(reply: Reply) -> None:
        request = SubRequest.objects.get(leaving=players[3])
        assert reply.result is not None
        assert reply.result.model_dump() == {"request_id": str(request.pk)}

    return Case(players[3], {"match_id": str(popped.pk), "player_id": str(players[3].pk)}, check)


def _sub_answer_request(league: Community, popped: Match, players: list[Player]) -> Case:
    match = vote_captains(ready_all(popped))
    request = subs.request_sub_out(match.pk, match.captain_of("A").player, _non_captain(match).pk)
    return Case(
        match.captain_of("B").player,
        {"request_id": str(request.pk), "approve": True},
        lambda r: assert_(SubRequest.objects.get(pk=request.pk).status == SubStatus.OPEN),
    )


def _sub_cancel(league: Community, popped: Match, players: list[Player]) -> Case:
    request = _self_sub(popped, players[3])
    return Case(
        players[3],
        {"request_id": str(request.pk)},
        lambda r: assert_(SubRequest.objects.get(pk=request.pk).status == SubStatus.CANCELLED),
    )


def _sub_invite(league: Community, popped: Match, players: list[Player]) -> Case:
    request = _self_sub(popped, players[3])
    target = make_player(41)

    def check(reply: Reply) -> None:
        offer = SubOffer.objects.get(request=request)
        assert offer.player_id == target.pk and offer.status == OfferStatus.PENDING
        assert Player.objects.get(pk=target.pk).display_name == "P41"  # Kept, not renamed.
        assert live.player_topic(target.pk) in reply.topics

    return Case(players[3], {"request_id": str(request.pk), "player_id": str(target.pk)}, check)


def _sub_offer_queue(league: Community, popped: Match, players: list[Player]) -> Case:
    request = _self_sub(popped, players[3])
    waiting = make_player(42)
    queue.join(league.pk, waiting)
    return Case(
        players[3],
        {"request_id": str(request.pk)},
        lambda r: assert_(SubOffer.objects.filter(request=request, player=waiting).exists()),
    )


def _sub_answer_offer(league: Community, popped: Match, players: list[Player]) -> Case:
    request = _self_sub(popped, players[3])
    target = make_player(43)
    offer = subs.invite_sub(request.pk, players[3], target.discord_user_id, target.display_name)
    return Case(
        target,
        {"offer_id": str(offer.pk), "accept": True},
        lambda r: assert_(popped.participants.filter(player=target, is_active=True).exists()),
    )


def _scrim_claim(league: Community, popped: Match, players: list[Player]) -> Case:
    match = scrims.start_claim(league.pk, SCRIM_CHANNEL, make_player(44))
    claimer = make_player(45)
    return Case(
        claimer,
        {"match_id": str(match.pk), "side": "hk"},
        lambda r: assert_(match.participants.filter(player=claimer, is_captain=True).exists()),
    )


def _scrim_start(league: Community, popped: Match, players: list[Player]) -> Case:
    one, two = make_player(46), make_player(47)
    match = scrims.start_coinflip(league.pk, SCRIM_CHANNEL, make_player(48), one, two)
    winner = match.participants.get(team=match.coinflip_winner).player
    loser = match.participants.exclude(team=match.coinflip_winner).get().player
    draft.choose_coinflip(match.pk, winner, engine.LAST_PICK)
    draft.choose_coinflip(match.pk, loser, engine.ARCHMOTHER)
    assert fresh(match).status == Status.READY_TO_DRAFT
    return Case(
        loser,
        {"match_id": str(match.pk)},
        lambda r: assert_(fresh(match).status == Status.CHAMPION_DRAFT),
    )


def assert_(condition: object) -> None:
    assert condition


CASES: dict[str, Callable[[Community, Match, list[Player]], Case]] = {
    "queue.join": _queue_join,
    "queue.leave": _queue_leave,
    "lobby.ready": _ready,
    "lobby.vote": _vote,
    "lobby.checkin": _checkin,
    "swap.propose": _swap_propose,
    "swap.answer": _swap_answer,
    "draft.pick_player": _pick_player,
    "draft.coinflip": _coinflip,
    "draft.champion": _champion,
    "draft.random_champion": _random_champion,
    "draft.lobby_code": _lobby_code,
    "results.confirm": _confirm,
    "results.dispute": _dispute,
    "ocr.map_row": _map_row,
    "early_leave.report": _early_report,
    "early_leave.answer": _early_answer,
    "subs.options": _sub_options,
    "subs.request": _sub_request,
    "subs.answer_request": _sub_answer_request,
    "subs.cancel": _sub_cancel,
    "subs.invite": _sub_invite,
    "subs.offer_queue": _sub_offer_queue,
    "subs.answer_offer": _sub_answer_offer,
    "scrims.claim": _scrim_claim,
    "scrims.start": _scrim_start,
}  # `draft.api_start` waits on deadlock-api, so it has tests of its own below.


def test_a_scrim_hero_draft_runs_on_the_snapshots_step(league: Community) -> None:
    """What the hero draft screen does: send the snapshot's step with the hero, or Random."""
    match = scrims.start_claim(league.pk, SCRIM_CHANNEL, make_player(44))
    scrims.claim_captain(match.pk, make_player(45), "hk")
    scrims.claim_captain(match.pk, make_player(46), "am")
    assert fresh(match).status == Status.CHAMPION_DRAFT

    def seen() -> schema.MatchSnap:
        body = snapshots.build_match(match.pk)
        assert body is not None
        return snapshots.project_match(body, acting_captain(fresh(match)).pk)

    snap = seen()
    assert snap.viewer.is_acting
    hero = next(choice for choice in snap.champions if not choice.taken)
    args = {"match_id": snap.id, "step_index": snap.step_index, "champion_id": hero.id}
    ok(act(acting_captain(fresh(match)), "draft.champion", args))
    after = seen()
    assert after.step_index == snap.step_index + 1
    assert after.draft[-1].champion is not None and after.draft[-1].champion.id == hero.id

    args = {"match_id": after.id, "step_index": after.step_index}
    reply = ok(act(acting_captain(fresh(match)), "draft.random_champion", args))
    assert reply.result is not None
    assert seen().step_index == after.step_index + 1
    # A step that has gone by is refused, as a double click would be.
    stale = {"match_id": snap.id, "step_index": snap.step_index, "champion_id": hero.id}
    assert not act(acting_captain(fresh(match)), "draft.champion", stale).ok


def test_every_contract_action_is_registered_and_nothing_else() -> None:
    assert set(actions.REGISTRY) == CONTRACT
    assert set(CASES) | {"draft.api_start"} == CONTRACT
    for name, action in actions.REGISTRY.items():
        assert action.name == name
        assert (action.run is None) != (action.run_async is None)


@pytest.mark.parametrize("name", sorted(CASES))
def test_each_action_calls_its_service(
    name: str, league: Community, popped: Match, players: list[Player]
) -> None:
    case = CASES[name](league, popped, players)
    reply = ok(act(case.player, name, case.args))
    case.check(reply)


# --- Refusals ---------------------------------------------------------------------------------


def test_refusals_come_back_as_plain_text(league: Community, popped: Match) -> None:
    outsider = make_player(50)
    match_id = str(popped.pk)
    assert act(outsider, "lobby.ready", {"match_id": match_id}) == Reply(
        False, "You are not in this match."
    )
    assert act(outsider, "queue.leave").error == "You're not in queue!"
    assert act(outsider, "results.confirm", {"match_id": match_id}).error == (
        "There's nothing to confirm."
    )
    assert act(outsider, "scrims.claim", {"match_id": match_id, "side": "hk"}).error == (
        "That isn't a scrim."
    )
    ready_all(popped)
    match = vote_captains(popped)
    waiting = match.captain_of("A").player
    if waiting == acting_captain(match):
        waiting = match.captain_of("B").player
    pick = {"match_id": match_id, "step_index": match.step_index, "player_id": "1"}
    assert act(waiting, "draft.pick_player", pick).error == "It's not your turn to pick a player."


def test_the_host_enters_a_code_only_once_the_bot_cant(popped: Match) -> None:
    match = run_champion_draft(to_champion_draft(popped))
    args = {"match_id": str(match.pk), "code": "ABC123"}
    reply = act(match.lobby_code_host, "draft.lobby_code", args)
    assert reply == Reply(False, draft.API_LOBBY_PENDING)
    match = fail_api_lobby(match)
    outsider = match.participants.exclude(player=match.lobby_code_host).first()
    assert outsider is not None
    assert act(outsider.player, "draft.lobby_code", args).error == (
        "Only the chosen host can enter the lobby code."
    )


def test_a_swap_from_a_player_is_refused(popped: Match) -> None:
    match = to_champion_draft(popped)
    give, take = _non_captain(match, "A"), _non_captain(match, "B")
    args = {"match_id": str(match.pk), "give_id": str(give.pk), "take_id": str(take.pk)}
    assert act(give, "swap.propose", args) == Reply(False, "Only a captain can swap players.")
    late = to_in_progress(match)
    assert not act(late.captain_of("A").player, "swap.propose", args).ok


def test_sub_options_say_what_subbing_yourself_out_costs(
    league: Community, popped: Match, players: list[Player]
) -> None:
    """A dodge before the game, leaving once it's on: each kind's strikes, from the policy."""
    policy = standing.strike_policy(league)
    match = vote_captains(ready_all(popped))
    player = _non_captain(match)
    options = ok(act(player, "subs.options", {"match_id": str(match.pk)})).result
    assert isinstance(options, schema.SubOutOptions)
    assert options.dodge and not options.game_on
    assert options.strikes == policy.points_for(PenaltyKind.DODGE) > 0
    match = to_in_progress(match)
    options = ok(act(player, "subs.options", {"match_id": str(match.pk)})).result
    assert isinstance(options, schema.SubOutOptions)
    assert options.game_on and options.strikes == policy.points_for(PenaltyKind.LEAVER)


def test_someone_elses_sub_request_is_refused(popped: Match, players: list[Player]) -> None:
    request = _self_sub(popped, players[3])
    reply = act(players[4], "subs.cancel", {"request_id": str(request.pk)})
    assert reply == Reply(False, "Only whoever asked for the sub can cancel it.")


def test_another_servers_match_is_refused_as_missing(players: list[Player]) -> None:
    other = community.ensure(guild_id=4242, name="Elsewhere")
    for player in players:
        queue.join(other.pk, player)
    foreign = Match.objects.get(community=other)
    request = _self_sub(foreign, players[3])
    gone = "That match no longer exists."
    assert act(players[0], "lobby.ready", {"match_id": str(foreign.pk)}).error == gone
    assert act(players[0], "lobby.ready", {"match_id": "987654"}).error == gone
    assert act(players[3], "subs.cancel", {"request_id": str(request.pk)}).error == (
        "That sub request no longer exists."
    )
    assert act(players[3], "subs.answer_offer", {"offer_id": "5", "accept": True}).error == (
        "That offer no longer exists."
    )
    assert act(players[3], "ocr.map_row", {"read_id": "5", "row": 0, "player_id": "1"}).error == (
        "That scoreboard read no longer exists."
    )
    assert fresh(foreign).participants.get(player=players[0]).ready_at is None
    assert SubRequest.objects.get(pk=request.pk).status == SubStatus.OPEN


def test_a_cooldown_refusal_reads_as_plain_text(league: Community) -> None:
    player = make_player(51)
    penalties.issue(league, player, PenaltyKind.DODGE, reason="Test")
    reply = act(player, "queue.join")
    assert not reply.ok and reply.error is not None
    assert reply.error.startswith("You're on a queue cooldown until ")
    assert " UTC" in reply.error
    for markup in ("<t:", "<@", "**"):
        assert markup not in reply.error


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("no.such", {}),
        ("lobby.ready", {}),
        ("lobby.ready", {"match_id": "abc"}),
        ("lobby.ready", {"match_id": "0"}),
        ("lobby.ready", {"match_id": "99999999999999999999"}),
        ("lobby.ready", {"match_id": "1", "extra": True}),
        ("draft.coinflip", {"match_id": "1", "choice": "heads"}),
        ("lobby.vote", {"match_id": "1", "candidate_ids": []}),
        ("draft.lobby_code", {"match_id": "1", "code": "x" * 33}),
        ("results.dispute", {"match_id": "1", "note": "x" * 501}),
        ("queue.join", {"anything": 1}),
    ],
)
def test_bad_arguments_are_refused_before_any_call(
    name: str, args: dict[str, Any], league: Community
) -> None:
    assert act(make_player(52), name, args) == Reply(False, BAD_REQUEST)


def test_an_unexpected_failure_is_logged_and_hidden(
    popped: Match, players: list[Player], monkeypatch: pytest.MonkeyPatch, caplog: Any
) -> None:
    def broken(*args: Any) -> None:
        raise RuntimeError("secret detail")

    monkeypatch.setattr(lobby, "mark_ready", broken)
    with caplog.at_level(logging.ERROR, logger="league.web.live.actions"):
        reply = act(players[0], "lobby.ready", {"match_id": str(popped.pk)})
    assert reply == Reply(False, FAILED)
    assert "secret" not in str(reply)
    assert "lobby.ready" in caplog.text and str(popped.pk) in caplog.text


# --- Over the socket --------------------------------------------------------------------------


async def _acked(ws: Any, ack_id: str) -> tuple[Msg, list[Msg]]:
    """Messages up to and including the ack with this id."""
    seen: list[Msg] = []

    def want(message: Msg) -> bool:
        seen.append(message)
        return message["t"] == "ack" and message["id"] == ack_id

    ack = await until(ws, want)
    return ack, seen[:-1]


@pytest.mark.django_db(transaction=True)
def test_the_snapshot_arrives_before_the_ack(
    popped: Match, players: list[Player], monkeypatch: pytest.MonkeyPatch
) -> None:
    # No listener: the only way a fresh snapshot can reach the socket is the action's refresh.
    monkeypatch.setattr(hub.listener, "start", lambda on_topic, on_connect: None)

    async def test() -> None:
        topic = f"match:{popped.pk}"
        ws = await signed_in(players[0])
        await subscribe(ws, "me", topic)
        await ws.send_json_to(
            {"t": "act", "id": "c-1", "name": "lobby.ready", "args": {"match_id": str(popped.pk)}}
        )
        ack, before = await _acked(ws, "c-1")
        assert ack == {"t": "ack", "id": "c-1", "ok": True, "error": None, "result": None}
        me = str(players[0].pk)
        ready = snap(topic, lambda m: any(p["is_ready"] for p in m["players"] if p["id"] == me))
        assert any(ready(message) for message in before)
        assert any(snap("me")(message) for message in before)

    run(test)


@pytest.mark.django_db(transaction=True)
def test_a_result_and_a_refusal_over_the_socket(popped: Match, players: list[Player]) -> None:
    async def test() -> None:
        ws = await signed_in(players[3])
        await subscribe(ws, f"match:{popped.pk}")
        args = {"match_id": str(popped.pk)}
        await ws.send_json_to({"t": "act", "id": "o", "name": "subs.options", "args": args})
        ack, _ = await _acked(ws, "o")
        assert ack["ok"] and ack["result"]["choices"][0]["player_id"] == str(players[3].pk)
        await ws.send_json_to({"t": "act", "id": "q", "name": "queue.leave", "args": {}})
        ack, _ = await _acked(ws, "q")
        assert ack == {
            "t": "ack",
            "id": "q",
            "ok": False,
            "error": "You're not in queue!",
            "result": None,
        }

    run(test)


@pytest.mark.django_db(transaction=True)
def test_a_repeated_action_id_is_answered_once(league: Community) -> None:
    async def test() -> None:
        player = await _db(make_player, 53)
        ws = await signed_in(player)
        await subscribe(ws, "me")
        join = {"t": "act", "id": "same", "name": "queue.join", "args": {}}
        await ws.send_json_to(join)
        await ws.send_json_to(join)
        await ws.send_json_to({"t": "act", "id": "next", "name": "queue.leave", "args": {}})
        _, before = await _acked(ws, "next")
        acks = [m for m in before if m["t"] == "ack"]
        assert acks == [{"t": "ack", "id": "same", "ok": True, "error": None, "result": None}]
        assert await _db(lambda: QueueEntry.objects.filter(player=player).exists()) is False

    run(test)


@pytest.mark.django_db(transaction=True)
def test_too_many_actions_is_4429(league: Community) -> None:
    async def test() -> None:
        ws = await signed_in(await _db(make_player, 54))
        for number in range(consumer.LiveConsumer.MAX_ACTIONS):
            await ws.send_json_to({"t": "act", "id": f"a{number}", "name": "no.such", "args": {}})
        _, _ = await _acked(ws, f"a{consumer.LiveConsumer.MAX_ACTIONS - 1}")
        await ws.send_json_to({"t": "act", "id": "over", "name": "no.such", "args": {}})
        assert await close_code(ws) == 4429

    run(test)


@pytest.mark.django_db(transaction=True)
def test_other_sockets_hear_the_change_by_notification(
    popped: Match, players: list[Player]
) -> None:
    async def test() -> None:
        topic = f"match:{popped.pk}"
        actor = await signed_in(players[0])
        watcher = await signed_in(await _db(make_player, 55))
        await subscribe(actor, topic)
        await subscribe(watcher, topic)
        await listening()
        await actor.send_json_to(
            {"t": "act", "id": "r", "name": "lobby.ready", "args": {"match_id": str(popped.pk)}}
        )
        await _acked(actor, "r")
        await until(watcher, snap(topic, lambda m: any(p["is_ready"] for p in m["players"])))

    run(test)


async def _db(fn: Callable[..., Any], *args: Any) -> Any:
    return await db(fn, *args)


# --- The bot-hosted lobby ---------------------------------------------------------------------


@pytest.fixture
def api_lobby(popped: Match) -> Match:
    match = run_champion_draft(to_champion_draft(popped))
    assert draft.accept_api_lobby(match.pk, "1234", "ABCD-EF")
    return fresh(match)


def _api_start(match: Match, player: Player) -> Reply:
    async def go() -> Reply:
        return await actions.dispatch(
            player.pk, match.community_id, "draft.api_start", {"match_id": str(match.pk)}
        )

    return asyncio.run(go())


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (None, None),
        (deadlock_api.ApiError("boom", 500), "Start it from the game instead."),
        (deadlock_api.ApiError("slow down", 429), "Try again in a moment."),
    ],
)
def test_api_start(
    api_lobby: Match,
    monkeypatch: pytest.MonkeyPatch,
    error: deadlock_api.ApiError | None,
    expected: str | None,
) -> None:
    started: list[str] = []

    def start(party_id: str) -> None:
        started.append(party_id)
        if error is not None:
            raise error

    monkeypatch.setattr(deadlock_api, "start_custom_match", start)
    captain = api_lobby.captain_of("A").player
    reply = _api_start(api_lobby, captain)
    assert started == ["1234"]
    if expected is None:
        assert reply == Reply(True, topics=(live.match_topic(api_lobby.pk),))
        assert fresh(api_lobby).api_started_at is not None
    else:
        assert reply == Reply(False, f"The match couldn't be started. {expected}")
        assert fresh(api_lobby).api_started_at is None


@pytest.mark.django_db(transaction=True)
def test_api_start_is_for_captains_only(api_lobby: Match, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(deadlock_api, "start_custom_match", lambda party_id: pytest.fail())
    reply = _api_start(api_lobby, _non_captain(api_lobby))
    assert reply == Reply(False, "Only a captain can start the match.")
    assert fresh(api_lobby).api_started_at is None
