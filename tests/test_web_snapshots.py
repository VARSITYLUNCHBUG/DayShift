"""What the websocket sends: the wire schema, the snapshot builders and plain text."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import threading
import typing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from django.conf import settings
from django.core.management import call_command
from django.db import connection

from league.domain import copy, engine
from league.domain.draft_plan import build_plan, player_draft_length, team_for_role
from league.domain.engine import Status, draft_name
from league.management.commands.export_ws_schema import DEFAULT_OUT, render
from league.models import Champion, Community, Match, Player, SteamAccount
from league.models.moderation import PenaltyKind
from league.services import (
    boards,
    chat,
    common,
    draft,
    early_leave,
    hero_art,
    lobby,
    penalties,
    queue,
    results,
    runtime,
    scrims,
    subs,
    swaps,
    wishes,
)
from league.web.live import actions, dbpool, schema, snapshots
from league.web.text import plain
from tests.conftest import make_player
from tests.helpers import (
    acting_captain,
    fail_api_lobby,
    finish,
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

pytestmark = pytest.mark.django_db


def _values(alias: typing.TypeAliasType) -> set[str]:
    return set(typing.get_args(alias.__value__))


def _body(match: Match) -> snapshots.MatchBody:
    body = snapshots.build_match(match.pk)
    assert body is not None
    return body


def _other_team(team: str) -> str:
    return "B" if team == "A" else "A"


# --- Schema -----------------------------------------------------------------------------------


def test_match_status_lists_every_engine_status() -> None:
    statuses = {value for name, value in vars(Status).items() if not name.startswith("_")}
    assert _values(schema.MatchStatus) == statuses


def test_coinflip_choices_are_the_engines() -> None:
    expected = {*engine.RANKED_COINFLIP_CHOICES, *engine.ORDER_CHOICES, *engine.SIDE_CHOICES}
    assert _values(schema.CoinflipChoice) == expected


def test_times_are_utc_with_a_z() -> None:
    moment = datetime(2026, 11, 16, 20, 15, 3, 120_000, tzinfo=UTC)
    message = schema.Pong(t="pong", server_time=moment)
    assert message.model_dump(mode="json")["server_time"] == "2026-11-16T20:15:03.120Z"


def test_client_messages_parse_and_bad_topics_are_refused() -> None:
    parsed = schema.ClientMessage.model_validate({"t": "sub", "topics": ["me", "match:12"]}).root
    assert isinstance(parsed, schema.Subscribe)
    assert schema.ClientMessage.model_validate({"t": "ping"}).root == schema.Ping(t="ping")
    for bad in ({"t": "sub", "topics": ["match:x"]}, {"t": "nope"}, {"t": "sub"}):
        with pytest.raises(ValueError):
            schema.ClientMessage.model_validate(bad)


def test_the_checked_in_schema_file_is_current() -> None:
    """The frontend's types come from this file: rerun `manage.py export_ws_schema` if not."""
    path = settings.BASE_DIR / DEFAULT_OUT
    assert path.read_text(encoding="utf-8") == render()


def test_export_ws_schema_writes_where_asked(tmp_path: Path) -> None:
    out = tmp_path / "deep" / "protocol.schema.json"
    call_command("export_ws_schema", "--out", str(out))
    document = json.loads(out.read_text(encoding="utf-8"))
    for name in ("ClientMessage", "ServerMessage", "MatchSnap", "MeSnap", "MatchStatus"):
        assert name in document["$defs"]


def test_the_schema_names_every_action_and_its_arguments() -> None:
    document = json.loads(render())
    arguments = document["$defs"]["ActionArgs"]
    assert set(arguments["properties"]) == set(actions.REGISTRY)
    assert set(arguments["required"]) == set(actions.REGISTRY)
    # Ids go over the wire as strings.
    match_id = document["$defs"]["MatchArgs"]["properties"]["match_id"]
    assert match_id["type"] == "string"


# --- Plain text -------------------------------------------------------------------------------

NOW = datetime(2026, 11, 16, 20, 0, tzinfo=UTC)


def test_plain_leaves_copy_alone() -> None:
    texts = [
        value
        for name, value in vars(copy).items()
        if isinstance(value, str) and value and not name.startswith("_")
    ]
    texts += [copy.has_captain("Pike's Team"), copy.not_your_turn("player_pick")]
    for text in texts:
        assert plain(text, now=NOW) == text


def test_plain_times() -> None:
    stamp = int((NOW + timedelta(minutes=15)).timestamp())
    assert plain(f"until <t:{stamp}:t>.", now=NOW) == "until 20:15 UTC."
    assert plain(f"asked <t:{stamp}:R>.", now=NOW) == "asked in 15 minutes."
    assert plain(f"<t:{int(NOW.timestamp()) - 7200}:R>", now=NOW) == "2 hours ago"
    assert plain(f"<t:{stamp}:R>", now=NOW + timedelta(minutes=15)) == "just now"
    assert plain(f"wait until <t:{stamp}:d>", now=NOW) == "wait until 16 Nov 2026"
    assert plain(f"<t:{stamp}>", now=NOW) == "16 Nov 2026, 20:15 UTC"


def test_plain_markup_mentions_and_emoji() -> None:
    assert (
        plain("**Lumen** is subbing out, so the match is paused.", now=NOW)
        == "Lumen is subbing out, so the match is paused."
    )
    assert plain("`scrim` is on cooldown.", now=NOW) == "scrim is on cooldown."
    assert (
        plain("You need the <@&123> role to send this ping.", now=NOW)
        == "You need the role to send this ping."
    )
    assert plain("Ping <@42> in <#7>!", now=NOW, names={42: "Rook"}) == "Ping Rook in!"
    assert plain("GG <:hk:1234567> <a:spin:42> __well__ *played*", now=NOW) == "GG well played"
    assert plain("snake_case_name and 2 * 3", now=NOW) == "snake_case_name and 2 * 3"


def test_plain_cooldown_refusal(league: Community) -> None:
    player = make_player(1)
    penalty = penalties.issue(league, player, PenaltyKind.MISSED_READY)
    text = plain(penalties.refusal_text(league, player, penalty))
    assert "<t:" not in text and "*" not in text
    assert f"{penalty.expires_at:%H:%M} UTC" in text


# --- me ---------------------------------------------------------------------------------------


def test_me_shows_only_the_players_own_place(league: Community) -> None:
    waiting = [make_player(n) for n in range(1, 6)]
    for player in waiting:
        queue.join(league.pk, player)
    queue.leave(league.pk, waiting[1])  # Their place is held.
    me = snapshots.build_me(waiting[2].pk, league.pk)
    assert me is not None
    assert me.queue.in_queue and me.queue.position == 2
    assert me.queue.place is not None
    assert (me.queue.place.position, me.queue.place.total) == (3, 5)
    held = snapshots.build_me(waiting[1].pk, league.pk)
    assert held is not None and not held.queue.in_queue
    assert held.queue.place is not None and held.queue.place.held_until is not None
    text = me.model_dump_json()
    for other in waiting:
        if other != waiting[2]:
            assert other.display_name not in text
            assert str(other.discord_user_id) not in text


def test_me_for_a_missing_player_is_none(league: Community) -> None:
    assert snapshots.build_me(999_999, league.pk) is None


def test_me_shows_a_cooldown_in_plain_text(league: Community) -> None:
    player = make_player(1)
    penalties.issue(league, player, PenaltyKind.DODGE)
    me = snapshots.build_me(player.pk, league.pk)
    assert me is not None and me.cooldown is not None
    assert me.cooldown.kind == "dodge" and "<t:" not in me.cooldown.text


def test_a_cooldown_brings_its_ladder_and_rung(league: Community) -> None:
    player = make_player(1)
    penalties.issue(league, player, PenaltyKind.MISSED_READY)
    penalties.revoke_active(league, player, keep_strikes=True)
    penalties.issue(league, player, PenaltyKind.MISSED_READY)
    me = snapshots.build_me(player.pk, league.pk)
    assert me is not None and me.cooldown is not None
    assert me.cooldown.ladder == penalties.ladder(league, PenaltyKind.MISSED_READY)
    assert me.cooldown.rung == 1  # One strike already carried.


@pytest.mark.parametrize("manual", [True, False])
def test_a_cooldown_staff_set_has_no_ladder(league: Community, manual: bool) -> None:
    player = make_player(1)
    kind = PenaltyKind.MANUAL if manual else PenaltyKind.DODGE
    penalties.issue(league, player, kind, minutes=7)
    me = snapshots.build_me(player.pk, league.pk)
    assert me is not None and me.cooldown is not None
    assert me.cooldown.ladder == [] and me.cooldown.rung is None


def test_me_shows_the_live_match_and_an_offer(popped: Match, players: list[Player]) -> None:
    request = subs.request_sub_out(popped.pk, players[3], players[3].pk)
    outsider = make_player(40)
    subs.invite_sub(request.pk, players[3], outsider.discord_user_id, outsider.display_name)
    me = snapshots.build_me(players[0].pk, popped.community_id)
    assert me is not None and me.match is not None
    assert me.match.id == str(popped.pk) and me.match.status == "ready_check"
    offered = snapshots.build_me(outsider.pk, popped.community_id)
    assert offered is not None and offered.match is None
    assert [(o.match_id, o.source) for o in offered.offers] == [(str(popped.pk), "invite")]


def test_me_keeps_the_match_until_its_result_is_settled(
    popped: Match, players: list[Player]
) -> None:
    """The first report makes everyone inactive (they can queue again), but the match is theirs
    to confirm or dispute until it's settled."""
    match = to_in_progress(popped)
    leaver = match.participants.filter(team="A", is_captain=False).order_by("id").first()
    assert leaver is not None
    results.submit_report(match.pk, match.captain_of("A").player, "A", image())
    assert not match.participants.filter(is_active=True).exists()
    me = snapshots.build_me(leaver.player_id, match.community_id)
    assert me is not None and me.match is not None
    assert (me.match.id, me.match.status) == (str(match.pk), "awaiting_confirmation")
    assert snapshots.roster_of(match.pk) >= {leaver.player_id}

    results.dispute(match.pk, match.captain_of("B").player, "No.")
    me = snapshots.build_me(leaver.player_id, match.community_id)
    assert me is not None and me.match is not None and me.match.status == "disputed"

    results.resolve_dispute(match.pk, "A", None, "Staff")
    me = snapshots.build_me(leaver.player_id, match.community_id)
    assert me is not None and me.match is None


def test_a_player_subbed_out_no_longer_has_the_match(popped: Match, players: list[Player]) -> None:
    request = subs.request_sub_out(popped.pk, players[3], players[3].pk)
    outsider = make_player(40)
    offer = subs.invite_sub(request.pk, players[3], outsider.discord_user_id, "P40")
    subs.answer_offer(offer.pk, outsider, accept=True)
    gone = snapshots.build_me(players[3].pk, popped.community_id)
    assert gone is not None and gone.match is None
    came = snapshots.build_me(outsider.pk, popped.community_id)
    assert came is not None and came.match is not None and came.match.id == str(popped.pk)


def test_me_counts_strikes_with_or_without_a_cooldown(league: Community) -> None:
    player = make_player(1)
    me = snapshots.build_me(player.pk, league.pk)
    assert me is not None and me.strikes == 0
    penalties.issue(league, player, PenaltyKind.DODGE)
    me = snapshots.build_me(player.pk, league.pk)
    assert me is not None and me.cooldown is not None
    assert me.strikes == me.cooldown.strikes > 0
    penalties.revoke_active(league, player, keep_strikes=True)
    me = snapshots.build_me(player.pk, league.pk)
    assert me is not None and me.cooldown is None and me.strikes > 0


def test_me_lists_the_players_own_steam_accounts(league: Community) -> None:
    player = make_player(1)
    SteamAccount.objects.create(
        player=player, account_id=111, steam_name="Main", linked_at=common.now()
    )
    SteamAccount.objects.create(
        player=player,
        account_id=222,
        steam_name="Alt",
        linked_at=common.now() + timedelta(seconds=1),
        proven_at=common.now(),
    )
    me = snapshots.build_me(player.pk, league.pk)
    assert me is not None
    assert [(link.account_id, link.proven, link.verified) for link in me.player.steam] == [
        ("111", False, False),
        ("222", True, False),
    ]


def test_me_flags_say_what_ratings_are_called(league: Community) -> None:
    me = snapshots.build_me(make_player(1).pk, league.pk)
    assert me is not None and me.flags.rating_label == "Rating"
    runtime.update(league, interim_points=True)
    me = snapshots.build_me(make_player(1).pk, league.pk)
    assert me is not None and me.flags.rating_label == "Points"


def test_an_offer_says_who_asked_and_where_the_match_is(
    popped: Match, players: list[Player]
) -> None:
    request = subs.request_sub_out(popped.pk, players[3], players[3].pk)
    outsider = make_player(40)
    subs.invite_sub(request.pk, players[3], outsider.discord_user_id, outsider.display_name)
    me = snapshots.build_me(outsider.pk, popped.community_id)
    assert me is not None and me.last_offer is None
    (offer,) = me.offers
    assert (offer.invited_by_name, offer.match_status, offer.started_at) == (
        "P4",
        "ready_check",
        None,
    )


def test_me_says_how_the_last_offer_ended(popped: Match, players: list[Player]) -> None:
    request = subs.request_sub_out(popped.pk, players[3], players[3].pk)
    outsider, other = make_player(40), make_player(41)
    queue.join(popped.community_id, other)  # Next in line once the invite falls through.
    offer = subs.invite_sub(request.pk, players[3], outsider.discord_user_id, outsider.display_name)
    subs.answer_offer(offer.pk, outsider, accept=False)
    me = snapshots.build_me(outsider.pk, popped.community_id)
    assert me is not None and me.offers == []
    assert me.last_offer == schema.OfferEnd(
        id=str(offer.pk), match_id=str(popped.pk), status="declined", team_name=None
    )
    me = snapshots.build_me(other.pk, popped.community_id)
    assert me is not None and me.last_offer is None
    (pending,) = me.offers
    subs.answer_offer(int(pending.id), other, accept=True)
    me = snapshots.build_me(other.pk, popped.community_id)
    assert me is not None and me.match is not None and me.match.id == str(popped.pk)
    assert me.last_offer is not None and me.last_offer.status == "accepted"


def test_ended_sub_requests_say_who_came_in(popped: Match, players: list[Player]) -> None:
    cancelled = subs.request_sub_out(popped.pk, players[2], players[2].pk)
    subs.cancel_sub(cancelled.pk, players[2])
    filled = subs.request_sub_out(popped.pk, players[3], players[3].pk)
    outsider = make_player(40)
    offer = subs.invite_sub(filled.pk, players[3], outsider.discord_user_id, outsider.display_name)
    subs.answer_offer(offer.pk, outsider, accept=True)
    body = _body(popped)
    assert body.snap.subs == []
    assert [
        (done.id, done.status, done.leaving_id, done.joined_id, done.joined_name)
        for done in body.snap.subs_done
    ] == [
        (str(cancelled.pk), "cancelled", str(players[2].pk), None, None),
        (str(filled.pk), "filled", str(players[3].pk), str(outsider.pk), "P40"),
    ]


def test_an_early_leave_report_has_its_answer_deadline(popped: Match) -> None:
    match = to_in_progress(popped)
    leaver = match.participants.filter(team="A", is_captain=False).first()
    assert leaver is not None
    claim = early_leave.report(match.pk, match.captain_of("A").player, leaver.player_id)
    body = _body(match)
    pending = body.snap.early_leave.pending
    assert pending is not None and pending.deadline_at == claim.deadline_at
    assert (pending.leaver_id, pending.by_id) == (
        str(leaver.player_id),
        str(match.captain_of("A").player_id),
    )
    other = match.captain_of("B").player_id
    assert snapshots.project_match(body, other).viewer.is_acting
    assert not snapshots.project_match(body, match.captain_of("A").player_id).viewer.is_acting


def test_avatar_urls_need_a_hash(league: Community) -> None:
    pytest.importorskip("league.web.avatars")
    player = make_player(1)
    for number in range(10, 15):
        queue.join(league.pk, make_player(number))
    queue.join(league.pk, player)
    assert snapshots.build_queue(league.pk).players[-1].avatar_url is None
    Player.objects.filter(pk=player.pk).update(discord_avatar="abc123")
    url = snapshots.build_queue(league.pk).players[-1].avatar_url
    assert url is not None and f"/avatar/{player.pk}/abc123" in url
    assert str(player.discord_user_id) not in url


# --- queue and live ---------------------------------------------------------------------------


def test_queue_and_live(popped: Match, league: Community) -> None:
    waiting = make_player(30)
    queue.join(league.pk, waiting)
    snap = snapshots.build_queue(league.pk)
    assert (snap.size, snap.count, snap.live_matches, snap.open) == (12, 1, 1, True)
    assert [p.id for p in snap.players] == [str(waiting.pk)]
    live = snapshots.build_live(league.pk)
    assert [(m.id, m.status) for m in live.matches] == [(str(popped.pk), "ready_check")]
    (row,) = live.matches
    assert row.draft_name == draft_name(popped.rng_seed)
    assert (row.sides.A, row.sides.B) == (None, None)  # Until the coinflip.


def test_live_shows_the_sides_once_settled(popped: Match) -> None:
    match = to_in_progress(popped)
    (row,) = snapshots.build_live(match.community_id).matches
    hk = match.hidden_king_team
    assert getattr(row.sides, hk) == "hk"
    assert getattr(row.sides, _other_team(hk)) == "am"


# --- match:{id} -------------------------------------------------------------------------------


def test_spectators_never_get_the_lobby_code(popped: Match, players: list[Player]) -> None:
    match = to_in_progress(popped)
    body = _body(match)
    assert body.snap.lobby_code == "ABC123"
    assert snapshots.project_match(body, players[0].pk).lobby_code == "ABC123"
    outsider = make_player(50)
    for viewer in (outsider.pk, None):
        seen = snapshots.project_match(body, viewer)
        assert seen.lobby_code is None
        assert not seen.viewer.is_player and not seen.viewer.can_request_sub
    assert "ABC123" not in snapshots.project_match(body, outsider.pk).model_dump_json()


def test_a_player_subbed_out_no_longer_gets_the_lobby_code(
    popped: Match, players: list[Player]
) -> None:
    match = to_in_progress(popped)
    leaving = match.participants.filter(is_captain=False).order_by("id").first()
    assert leaving is not None
    request = subs.request_sub_out(match.pk, leaving.player, leaving.player_id)
    outsider = make_player(40)
    offer = subs.invite_sub(request.pk, leaving.player, outsider.discord_user_id, "P40")
    subs.answer_offer(offer.pk, outsider, accept=True)
    body = _body(match)
    assert snapshots.project_match(body, leaving.player_id).lobby_code is None
    assert snapshots.project_match(body, outsider.pk).lobby_code == "ABC123"


def test_viewer_flags_follow_the_turn(popped: Match, players: list[Player]) -> None:
    match = ready_all(popped)
    voter = players[0]
    lobby.cast_captain_votes(match.pk, voter, [players[1].pk, players[2].pk])
    body = _body(match)
    voted = snapshots.project_match(body, voter.pk).viewer
    waiting = snapshots.project_match(body, players[5].pk).viewer
    assert voted.has_voted and not voted.is_acting
    assert not waiting.has_voted and waiting.is_acting
    assert voted.can_request_sub

    match = vote_captains(match)
    body = _body(match)
    assert body.snap.turn is not None
    acting = acting_captain(match)
    other = next(
        match.captain_of(team).player
        for team in ("A", "B")
        if match.captain_of(team).player != acting
    )
    seen = snapshots.project_match(body, acting.pk).viewer
    assert seen.is_captain and seen.is_acting and seen.team == body.snap.turn.team
    assert body.snap.turn.captain_id == str(acting.pk)
    assert not snapshots.project_match(body, other.pk).viewer.is_acting

    match = run_player_draft(match)
    assert fresh(match).status == Status.COINFLIP
    body = _body(match)
    assert body.snap.coinflip is not None
    winner = match.captain_of(match.coinflip_winner).player
    assert body.snap.coinflip.chooser_id == str(winner.pk)
    assert snapshots.project_match(body, winner.pk).viewer.is_acting
    assert set(body.snap.coinflip.options) == set(engine.RANKED_COINFLIP_CHOICES)


def test_the_captain_check_in_shows_who_is_here(popped: Match) -> None:
    match = vote_only(ready_all(popped))
    assert match.status == Status.CAPTAIN_CHECKIN
    first, second = match.captain_of("A").player, match.captain_of("B").player
    lobby.check_in(match.pk, first)
    body = _body(match)
    assert body.snap.status == "captain_checkin"
    here = {p.id for p in body.snap.players if p.checked_in}
    assert here == {str(first.pk)}
    assert snapshots.project_match(body, first.pk).viewer.checked_in
    assert not snapshots.project_match(body, first.pk).viewer.is_acting
    assert snapshots.project_match(body, second.pk).viewer.is_acting
    player = match.participants.filter(is_captain=False).first()
    assert player is not None
    assert not snapshots.project_match(body, player.player_id).viewer.is_acting


def test_the_step_and_the_whole_player_pick_order(popped: Match) -> None:
    body = _body(popped)
    assert (body.snap.step_index, body.snap.player_draft_order) == (0, [])

    match = vote_captains(ready_all(popped))
    plan = build_plan(match.mode)[: player_draft_length(match.mode)]
    body = _body(match)
    assert body.snap.turn is not None
    order = body.snap.player_draft_order
    assert [step.step_index for step in order] == list(range(len(plan)))
    assert [step.team for step in order] == [
        team_for_role(step.role, match.player_first_pick) for step in plan
    ]
    assert body.snap.step_index == match.step_index == 0
    assert order[0].team == body.snap.turn.team == match.player_first_pick

    match = run_player_draft(match)
    body = _body(match)
    assert body.snap.step_index == len(plan)  # The player draft is done.
    assert len(body.snap.player_draft_order) == len(plan)


def test_the_hero_draft_has_its_steps_and_art(
    popped: Match, monkeypatch: pytest.MonkeyPatch
) -> None:
    abrams = Champion.objects.get(name="Abrams")
    monkeypatch.setattr(hero_art, "available", lambda: frozenset({abrams.slug}))
    match = to_champion_draft(popped)
    champion = draft.available_champions(match)[0]
    draft.choose_champion(match.pk, acting_captain(match), match.step_index, champion)
    body = _body(fresh(match))
    snap = body.snap
    assert snap.champion_step == 1 and len(snap.champion_steps) > 1
    grid = {choice.name: choice for choice in snap.champions}
    assert grid["Abrams"].icon_url == f"/static/hero-art/{abrams.slug}.webp"
    assert grid["Seven"].icon_url is None  # The page shows initials.
    taken = snap.draft[-1].champion
    assert taken is not None and taken.id == str(champion)
    assert grid[taken.name].taken


def test_a_scrim_sends_its_step_and_no_player_picks(
    league: Community, players: list[Player]
) -> None:
    match = scrims.start_claim(league.pk, 8200, players[2])
    scrims.claim_captain(match.pk, players[0], "hk")
    scrims.claim_captain(match.pk, players[1], "am")
    match = fresh(match)
    assert match.status == Status.CHAMPION_DRAFT
    body = _body(match)
    # A scrim's steps follow on from the player picks it never makes.
    assert body.snap.step_index == match.step_index == player_draft_length(match.mode)
    assert body.snap.player_draft_order == []
    assert body.snap.champion_step == 0
    assert body.snap.kind == "scrim"


def test_a_scrim_coinflip_waits_on_the_loser_after_the_winner(
    league: Community, players: list[Player]
) -> None:
    match = scrims.start_coinflip(league.pk, 8200, players[2], players[0], players[1])
    winner = match.participants.get(team=match.coinflip_winner).player
    loser = match.participants.exclude(team=match.coinflip_winner).get().player
    body = _body(match)
    assert body.snap.coinflip is not None and len(body.snap.coinflip.options) == 4
    assert snapshots.project_match(body, winner.pk).viewer.is_acting
    draft.choose_coinflip(match.pk, winner, engine.LAST_PICK)
    body = _body(match)
    assert body.snap.coinflip is not None
    assert body.snap.coinflip.chooser_id == str(loser.pk)
    assert set(body.snap.coinflip.options) == set(engine.SIDE_CHOICES)
    draft.choose_coinflip(match.pk, loser, engine.ARCHMOTHER)
    body = _body(match)
    assert body.snap.status == "ready_to_draft"
    assert snapshots.project_match(body, winner.pk).viewer.is_acting


def test_the_api_lobby_states(popped: Match, players: list[Player]) -> None:
    match = run_champion_draft(to_champion_draft(popped))
    assert match.status == Status.LOBBY_CODE
    body = _body(match)
    assert body.snap.lobby.state == "making"
    host = snapshots.project_match(body, match.lobby_code_host_id)
    assert not host.viewer.is_acting  # The bot is making it.

    failed = fail_api_lobby(match)
    body = _body(failed)
    assert body.snap.lobby.state == "failed"
    assert snapshots.project_match(body, failed.lobby_code_host_id).viewer.is_acting


def test_the_api_lobby_ready_then_started(popped: Match) -> None:
    match = run_champion_draft(to_champion_draft(popped))
    assert draft.accept_api_lobby(match.pk, "1234", "ABCD-EF")
    match = fresh(match)
    body = _body(match)
    assert body.snap.status == "in_progress"
    assert (body.snap.lobby.state, body.snap.lobby.api_lobby) == ("ready", True)
    assert body.snap.lobby.api_leaves_at is not None
    assert body.snap.lobby_code == "ABCD-EF"
    captain = match.captain_of("A").player
    assert snapshots.project_match(body, captain.pk).viewer.is_acting  # Press Start.
    draft.mark_api_started(match.pk, captain)
    body = _body(match)
    assert body.snap.lobby.state == "started" and body.snap.started_at is not None
    assert not snapshots.project_match(body, captain.pk).viewer.is_acting


def test_a_swap_offer_and_the_captains_choices(popped: Match) -> None:
    match = to_champion_draft(popped)
    body = _body(match)
    assert body.snap.swap.open and body.snap.swap.pending is None
    a, b = match.captain_of("A").player, match.captain_of("B").player
    seen = snapshots.project_match(body, a.pk).viewer
    own = {p.id for p in body.snap.players if p.team == "A" and not p.is_captain}
    theirs = {p.id for p in body.snap.players if p.team == "B" and not p.is_captain}
    assert {c.player_id for c in seen.swap_give} == own
    assert {c.player_id for c in seen.swap_take} == theirs
    player = match.participants.filter(team="A", is_captain=False).first()
    assert player is not None
    assert snapshots.project_match(body, player.player_id).viewer.swap_give == []

    give, take = sorted(own)[0], sorted(theirs)[0]
    swap = swaps.propose(match.pk, a, int(give), int(take))
    body = _body(match)
    pending = body.snap.swap.pending
    assert pending is not None
    assert (pending.id, pending.requested_by_id, pending.give_id, pending.take_id) == (
        str(swap.pk),
        str(a.pk),
        give,
        take,
    )
    assert snapshots.project_match(body, a.pk).viewer.swap_give == []  # One at a time.
    assert snapshots.project_match(body, b.pk).viewer.is_acting


def test_swaps_close_once_the_game_starts(popped: Match) -> None:
    body = _body(to_in_progress(popped))
    assert not body.snap.swap.open and body.snap.swap.pending is None


def test_a_completed_match_has_deltas_and_the_rating_label(popped: Match) -> None:
    match = finish(to_in_progress(popped), "B")
    body = _body(match)
    assert body.snap.result.winner == "B"
    assert body.snap.rating_label == "Rating"
    assert set(body.snap.result.deltas) == {p.id for p in body.snap.players}
    assert [r.verdict for r in body.snap.result.responses] == ["report", "confirm"]


def test_a_voided_match_says_why(popped: Match) -> None:
    lobby.staff_void(popped.pk, None, "Testing **voids**")
    body = _body(popped)
    assert body.snap.status == "voided"
    assert body.snap.result.void_reason is not None
    assert "*" not in body.snap.result.void_reason


def test_a_sub_line_carries_player_ids(popped: Match, players: list[Player]) -> None:
    request = subs.request_sub_out(popped.pk, players[3], players[3].pk)
    outsider = make_player(40)
    subs.invite_sub(request.pk, players[3], outsider.discord_user_id, outsider.display_name)
    body = _body(popped)
    (line,) = body.snap.subs
    assert (line.leaving_id, line.requested_by_id) == (str(players[3].pk), str(players[3].pk))
    assert line.offer is not None and line.offer.player_id == str(outsider.pk)
    assert line.offer.source == "invite"
    assert body.snap.on_hold and body.snap.hold_until is not None
    leaving = snapshots.project_match(body, players[3].pk).viewer
    assert not leaving.can_request_sub and not leaving.is_acting


def test_team_only_fields_reach_only_that_team(popped: Match) -> None:
    """Where BE-CHAT's chat and wishes go: `by_team` is merged into the viewer's team's view."""
    match = to_champion_draft(popped)
    body = dataclasses.replace(_body(match), by_team={"A": {"mode_name": "secret"}})
    a, b = match.captain_of("A").player_id, match.captain_of("B").player_id
    assert snapshots.project_match(body, a).mode_name == "secret"
    assert snapshots.project_match(body, b).mode_name != "secret"
    assert snapshots.project_match(body, None).mode_name != "secret"


def test_roster_only_fields_reach_the_roster_and_nobody_else(popped: Match) -> None:
    """The lobby chat's way in: `roster_only` goes to every player in the match, team or not."""
    match = vote_captains(ready_all(popped))
    body = dataclasses.replace(_body(match), roster_only={"mode_name": "ours"})
    undrafted = match.participants.filter(team="").order_by("id").first()
    assert undrafted is not None
    assert snapshots.project_match(body, undrafted.player_id).mode_name == "ours"
    assert snapshots.project_match(body, make_player(50).pk).mode_name != "ours"
    assert snapshots.project_match(body, None).mode_name != "ours"


def test_chat_lines_and_wishes_on_the_wire(popped: Match) -> None:
    match = to_champion_draft(popped)
    player = match.participants.filter(team="A", is_captain=False).order_by("id").first()
    assert player is not None
    hero = sorted(match.champion_pool)[0]
    wishes.set_wishes(match.pk, player.player, [hero])
    chat.send(match.pk, player.player, "hello")
    data = snapshots.project_match(_body(match), player.player_id).model_dump(mode="json")
    assert data["wishes"] == [
        {"player_id": str(player.player_id), "champion_id": str(hero), "rank": 1}
    ]
    assert data["viewer"]["can_wish"] is True
    (line,) = data["chat"]["messages"]
    assert data["chat"]["scope"] == "team" and data["chat"]["open"]
    assert line["at"].endswith("Z") and line["team"] == "A" and line["body"] == "hello"
    assert isinstance(line["id"], str) and line["player_id"] == str(player.player_id)
    public = snapshots.project_match(_body(match), None).model_dump(mode="json")
    assert public["wishes"] == [] and public["chat"] is None
    assert public["viewer"]["can_wish"] is False


def test_a_match_says_its_player_draft_timeout_rule(popped: Match) -> None:
    """The mode picks the highest-rated player left by default, so the page says so."""
    body = snapshots.build_match(popped.pk)
    assert body is not None and body.snap.player_timeout == "highest_rating"


def test_a_missing_match_has_no_body(league: Community) -> None:
    assert snapshots.build_match(123_456_789) is None


def test_roster_is_everyone_playing(popped: Match, players: list[Player]) -> None:
    assert snapshots.roster_of(popped.pk) == {player.pk for player in players}


def test_a_scrim_you_captain_is_your_scrim(league: Community) -> None:
    """Scrim captains are inactive participants (they can play ranked meanwhile), so the scrim
    has a place of its own in `me`, and its changes reach their `me`."""
    starter, hk, am, onlooker = (make_player(n) for n in range(1, 5))
    match = scrims.start_claim(league.pk, 4242, starter)
    scrims.claim_captain(match.pk, hk, "hk")
    me = snapshots.build_me(hk.pk, league.pk)
    assert me is not None and me.match is None
    assert me.scrim is not None
    assert (me.scrim.id, me.scrim.status) == (str(match.pk), "captain_claim")
    assert me.scrim.kind == "scrim"
    assert me.scrim.team == "A" and me.scrim.is_captain
    other = snapshots.build_me(onlooker.pk, league.pk)
    assert other is not None and other.scrim is None
    assert snapshots.roster_of(match.pk) == {hk.pk}

    scrims.claim_captain(match.pk, am, "am")
    assert snapshots.roster_of(match.pk) == {hk.pk, am.pk}
    match = fresh(match)
    while match.status == Status.CHAMPION_DRAFT:
        champion = draft.available_champions(match)[0]
        draft.choose_champion(match.pk, acting_captain(match), match.step_index, champion)
        match = fresh(match)
    assert match.status == Status.DRAFTED
    done = snapshots.build_me(hk.pk, league.pk)
    assert done is not None and done.scrim is None


def test_board_read_models_carry_ids(popped: Match) -> None:
    view = boards.queue_view(popped.community)
    assert view.player_ids == [] and view.players == []
    match = vote_captains(ready_all(popped))
    captain = acting_captain(match)
    target = match.participants.filter(team="").order_by("id").first()
    assert target is not None
    draft.pick_player(match.pk, captain, match.step_index, target.player_id)
    state = boards.board_state(match.pk)
    assert state.actions[-1].player_id == target.player_id
    assert state.version == fresh(match).version
    assert state.community_id == match.community_id


# --- Consistency and the pool -----------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_snapshots_read_in_one_repeatable_read_only_transaction(
    league: Community, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[str, str]] = []
    real = boards.queue_view

    def spy(community: Community) -> boards.QueueView:
        with connection.cursor() as cursor:
            cursor.execute("SHOW transaction_isolation")
            isolation = cursor.fetchone()[0]
            cursor.execute("SHOW transaction_read_only")
            seen.append((isolation, cursor.fetchone()[0]))
        return real(community)

    monkeypatch.setattr(boards, "queue_view", spy)
    snapshots.build_queue(league.pk)
    assert seen == [("repeatable read", "on")]


@pytest.mark.django_db(transaction=True)
def test_web_db_runs_on_its_own_threads(league: Community) -> None:
    def where() -> tuple[str, int]:
        return threading.current_thread().name, Community.objects.count()

    try:
        name, count = asyncio.run(dbpool.web_db(where))
    finally:
        dbpool.shutdown()
    assert name.startswith("web-db") and count == 1
