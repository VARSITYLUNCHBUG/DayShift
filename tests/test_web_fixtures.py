"""Snapshot fixtures for the frontend, from real matches driven through the services.

Each scenario plays a match to one status and writes what a captain, a player and a spectator
would be sent, plus their `me`, the queue and the live list, to `services/web/src/fixtures/`.
The web UI renders every screen from these, so a change to what the server sends shows up here.

    UPDATE_WS_FIXTURES=1 pytest tests/test_web_fixtures.py   # rewrite them after a change

Without the variable the files must match exactly. Time is frozen and the random seeds fixed, so
a run is repeatable; database IDs, which depend on what ran before, are renumbered by creation
order within each kind (players, matches, sub requests, offers, scoreboard reads). Hero IDs are
Deadlock's own and stay as they are.
"""

from __future__ import annotations

import itertools
import json
import os
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from django.conf import settings
from django.utils import timezone
from pydantic import BaseModel

from league.domain.engine import ARCHMOTHER, LAST_PICK, Status
from league.models import (
    ChatMessage,
    Community,
    Match,
    Player,
    PlayerSwap,
    ScoreboardRead,
    Season,
    SubOffer,
    SubRequest,
)
from league.services import (
    chat,
    deadlines,
    draft,
    early_leave,
    lobby,
    prio,
    queue,
    results,
    scrims,
    subs,
    swaps,
    wishes,
)
from league.web.live import snapshots
from tests.conftest import Clock, make_player
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
from tests.web_helpers import read_scoreboard

pytestmark = pytest.mark.django_db

FIXTURES = settings.BASE_DIR / "services" / "web" / "src" / "fixtures"
EPOCH = datetime(2026, 1, 5, 19, 0, tzinfo=UTC)
UPDATE = os.environ.get("UPDATE_WS_FIXTURES") == "1"
CHANNEL = 8200

# Keys holding a database ID, by kind. A plain "id" takes its kind from the key it sits under.
PLAYER_KEYS = {
    "player_id",
    "leaving_id",
    "requested_by_id",
    "give_id",
    "take_id",
    "reported_by_id",
    "captain_id",
    "chooser_id",
    "leaver_id",
    "by_id",
    "joined_id",
}
PLAYER_LIST_KEYS = {"votes"}  # Lists of player IDs.
MATCH_KEYS = {"match_id", "restarted_from"}
SWAP_KEYS = {"swap_id"}
READ_KEYS = {"read_id"}
SEASON_KEYS = {"season_id"}
ID_UNDER = {
    "player": "player",
    "players": "player",
    "host": "player",
    "match": "match",
    "scrim": "match",
    "seasons": "season",
    "matches": "match",
    "subs": "sub",
    "subs_done": "sub",
    "offers": "offer",
    "last_offer": "offer",
    "pending": "swap",
    "messages": "chat",
}


@pytest.fixture
def frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    """Freeze the clock at EPOCH (the `clock` fixture still moves it) and fix every seed."""
    monkeypatch.setattr(timezone, "now", lambda: EPOCH)
    seeds = itertools.count(1)
    monkeypatch.setattr(secrets, "randbits", lambda bits: (next(seeds) * 7_919_993) % (1 << bits))
    monkeypatch.setattr(secrets, "randbelow", lambda bound: 0)


@dataclass
class Scene:
    match: Match
    captain: Player | None
    player: Player | None
    spectator: Player


def _non_captain(match: Match) -> Player | None:
    row = (
        match.participants.filter(removed_reason="", is_captain=False)
        .select_related("player")
        .order_by("id")
        .first()
    )
    return row.player if row else None


def _scene(match: Match, captain: Player | None, spectator: Player) -> Scene:
    match = fresh(match)
    if captain is None and match.participants.filter(is_captain=True).exists():
        captain = match.captain_of("A").player
    return Scene(match, captain, _non_captain(match), spectator)


def _onlooker(league: Community) -> Player:
    """Someone signed in but not playing: waiting in the queue."""
    player = make_player(13)
    queue.join(league.pk, player)
    return player


def _popped(league: Community, players: list[Player]) -> Match:
    for player in players:
        queue.join(league.pk, player)
    return Match.objects.get()


# --- Wishes and chat --------------------------------------------------------------------------


def _seats(match: Match, team: str) -> list[Player]:
    """A team's players, captain first."""
    rows = match.participants.filter(removed_reason="", team=team).select_related("player")
    return [row.player for row in rows.order_by("-is_captain", "id")]


def _talk(match: Match, clock: Clock, lines: list[tuple[Player, str]]) -> None:
    """Post these lines in the chat each sender sees, a few seconds apart, the last just now."""
    sent = [chat.send(match.pk, player, body) for player, body in lines]
    for back, message in enumerate(reversed(sent)):
        moment = clock.now() - timedelta(seconds=5 + 17 * back)
        ChatMessage.objects.filter(pk=message.pk).update(created_at=moment)


def _wish(match: Match) -> None:
    """Wishes on both teams: three, two and one, and the captains' too. Each team's view shows
    only its own."""
    pool = sorted(fresh(match).champion_pool)
    for team, offset in (("A", 0), ("B", 7)):
        captain, first, second, third, *_ = _seats(match, team)
        heroes = pool[offset:]
        wishes.set_wishes(match.pk, first, [heroes[0], heroes[1], heroes[2]])
        wishes.set_wishes(match.pk, second, [heroes[3], heroes[0]])
        wishes.set_wishes(match.pk, third, [heroes[4]])
        wishes.set_wishes(match.pk, captain, [heroes[5], heroes[6]])


def _team_talk(match: Match, clock: Clock) -> None:
    a, b = _seats(match, "A"), _seats(match, "B")
    _talk(
        match,
        clock,
        [
            (a[1], "I can flex, put me wherever"),
            (b[0], "Who wants to go first pick?"),
            (a[0], "Ban their best duo, then we take the frog."),
            (b[2], "me pls"),
            (a[2], "ok\nI'll take mid if nobody minds"),
            (b[1], "Careful, they're stacked on hard carries"),
        ],
    )


# --- Ranked -----------------------------------------------------------------------------------


def ready_check(league: Community, players: list[Player], clock: Clock) -> Scene:
    match = _popped(league, players)
    for player in players[:7]:
        lobby.mark_ready(match.pk, player)
    return _scene(match, None, _onlooker(league))


def captain_phase(league: Community, players: list[Player], clock: Clock) -> Scene:
    match = ready_all(_popped(league, players))
    for voter in players[:4]:
        lobby.cast_captain_votes(match.pk, voter, [players[4].pk, players[7].pk])
    return _scene(match, None, _onlooker(league))


def captain_checkin(league: Community, players: list[Player], clock: Clock) -> Scene:
    """The vote picked the captains; A has checked in, B hasn't yet."""
    match = vote_only(ready_all(_popped(league, players)))
    assert match.status == Status.CAPTAIN_CHECKIN
    lobby.check_in(match.pk, match.captain_of("A").player)
    return _scene(match, match.captain_of("B").player, _onlooker(league))


def player_draft(league: Community, players: list[Player], clock: Clock) -> Scene:
    match = vote_captains(ready_all(_popped(league, players)))
    target = match.participants.filter(team="").order_by("id").first()
    assert target is not None
    draft.pick_player(match.pk, acting_captain(match), match.step_index, target.player_id)
    waiting = match.participants.filter(team="").order_by("id").select_related("player")
    _talk(
        match,
        clock,
        [
            (match.captain_of("A").player, "gl hf everyone"),
            (target.player, "thanks for the pick!"),
            (waiting[0].player, "I play anything, pick me"),
            (match.captain_of("B").player, "Noted. <b>No promises</b> & no tilting"),
            (waiting[1].player, "first time here, be nice :)"),
        ],
    )
    return _scene(match, acting_captain(match), _onlooker(league))


def player_draft_sub_open(league: Community, players: list[Player], clock: Clock) -> Scene:
    """A player subs themself out mid-draft and names the onlooker, who has the offer."""
    match = vote_captains(ready_all(_popped(league, players)))
    leaving = _non_captain(match)
    assert leaving is not None
    request = subs.request_sub_out(match.pk, leaving, leaving.pk)
    onlooker = _onlooker(league)
    subs.invite_sub(request.pk, leaving, onlooker.discord_user_id, onlooker.display_name)
    return _scene(match, acting_captain(match), onlooker)


def player_draft_sub_approval(league: Community, players: list[Player], clock: Clock) -> Scene:
    """A captain asks to sub out the teammate they just picked; the other captain decides."""
    match = vote_captains(ready_all(_popped(league, players)))
    asking = acting_captain(match)
    target = match.participants.filter(team="").order_by("id").first()
    assert target is not None
    draft.pick_player(match.pk, asking, match.step_index, target.player_id)
    subs.request_sub_out(match.pk, asking, target.player_id)
    other = fresh(match).participants.filter(is_captain=True).exclude(player=asking).get()
    return _scene(match, other.player, _onlooker(league))


def player_draft_sub_naming(league: Community, players: list[Player], clock: Clock) -> Scene:
    """The other captain approved: the captain who asked has a while to name a sub."""
    match = vote_captains(ready_all(_popped(league, players)))
    asking = acting_captain(match)
    target = match.participants.filter(team="").order_by("id").first()
    assert target is not None
    draft.pick_player(match.pk, asking, match.step_index, target.player_id)
    request = subs.request_sub_out(match.pk, asking, target.player_id)
    other = fresh(match).participants.filter(is_captain=True).exclude(player=asking).get()
    subs.answer_sub_out(request.pk, other.player, approve=True)
    return _scene(match, asking, _onlooker(league))


def coinflip(league: Community, players: list[Player], clock: Clock) -> Scene:
    """The teams are set: both have wishes, and a word in their team chat."""
    match = run_player_draft(vote_captains(ready_all(_popped(league, players))))
    _wish(match)
    a, b = _seats(match, "A"), _seats(match, "B")
    _talk(match, clock, [(a[0], "Calling it: we go Hidden King."), (b[1], "we got this")])
    return _scene(match, match.captain_of(match.coinflip_winner).player, _onlooker(league))


def champion_draft(league: Community, players: list[Player], clock: Clock) -> Scene:
    """Three bans in. Both teams have wishes (some for heroes now banned) and team chat."""
    match = to_champion_draft(_popped(league, players))
    _wish(match)
    _team_talk(match, clock)
    for _ in range(3):
        champion = draft.available_champions(match)[0]
        draft.choose_champion(match.pk, acting_captain(match), match.step_index, champion)
        match = fresh(match)
    return _scene(match, acting_captain(match), _onlooker(league))


def champion_draft_swap_pending(league: Community, players: list[Player], clock: Clock) -> Scene:
    """Captain A offers a swap during the hero draft; captain B decides."""
    match = to_champion_draft(_popped(league, players))
    give = match.participants.filter(team="A", is_captain=False).order_by("id").first()
    take = match.participants.filter(team="B", is_captain=False).order_by("id").first()
    assert give is not None and take is not None
    swaps.propose(match.pk, match.captain_of("A").player, give.player_id, take.player_id)
    return _scene(match, match.captain_of("B").player, _onlooker(league))


def lobby_code(league: Community, players: list[Player], clock: Clock) -> Scene:
    """The bot is asking deadlock-api for a lobby."""
    match = run_champion_draft(to_champion_draft(_popped(league, players)))
    return _scene(match, match.lobby_code_host, _onlooker(league))


def lobby_code_failed(league: Community, players: list[Player], clock: Clock) -> Scene:
    """deadlock-api couldn't make the lobby: the host makes one and enters its code."""
    match = fail_api_lobby(run_champion_draft(to_champion_draft(_popped(league, players))))
    return _scene(match, match.lobby_code_host, _onlooker(league))


def in_progress_api_lobby(league: Community, players: list[Player], clock: Clock) -> Scene:
    """The bot's lobby is up: a captain presses Start once everyone's in."""
    match = run_champion_draft(to_champion_draft(_popped(league, players)))
    assert draft.accept_api_lobby(match.pk, "1234", "ABCD-EF")
    clock.advance(60)
    return _scene(match, None, _onlooker(league))


def in_progress_api_started(league: Community, players: list[Player], clock: Clock) -> Scene:
    match = run_champion_draft(to_champion_draft(_popped(league, players)))
    assert draft.accept_api_lobby(match.pk, "1234", "ABCD-EF")
    clock.advance(120)
    draft.mark_api_started(match.pk, match.captain_of("A").player)
    clock.advance(300)
    return _scene(match, None, _onlooker(league))


def in_progress(league: Community, players: list[Player], clock: Clock) -> Scene:
    match = to_in_progress(_popped(league, players))
    clock.advance(600)
    return _scene(match, None, _onlooker(league))


def in_progress_sub_offered(league: Community, players: list[Player], clock: Clock) -> Scene:
    """A player subs themself out of the game and skips naming anyone: the onlooker, waiting in
    the queue, is offered the spot. The player is the one leaving."""
    match = to_in_progress(_popped(league, players))
    clock.advance(190)
    onlooker = _onlooker(league)
    leaving = _non_captain(match)
    assert leaving is not None
    request = subs.request_sub_out(match.pk, leaving, leaving.pk)
    subs.offer_to_queue(request.pk, leaving)
    return Scene(fresh(match), match.captain_of("A").player, leaving, onlooker)


def in_progress_early_leave(league: Community, players: list[Player], clock: Clock) -> Scene:
    """Captain A reports an early leaver; the match waits on captain B's answer."""
    match = to_in_progress(_popped(league, players))
    clock.advance(120)
    leaver = match.participants.filter(team="A", is_captain=False).order_by("id").first()
    assert leaver is not None
    early_leave.report(match.pk, match.captain_of("A").player, leaver.player_id)
    return _scene(match, match.captain_of("B").player, _onlooker(league))


def awaiting_confirmation(league: Community, players: list[Player], clock: Clock) -> Scene:
    """Captain A reported. The team chats are read-only now."""
    match = to_in_progress(_popped(league, players))
    clock.advance(1800)
    _team_talk(match, clock)
    results.submit_report(match.pk, match.captain_of("A").player, "A", image(1))
    return _scene(match, match.captain_of("B").player, _onlooker(league))


def awaiting_confirmation_scoreboard(
    league: Community, players: list[Player], clock: Clock
) -> Scene:
    """Captain A reported, and the scoreboard read left one name on each team that nobody could
    place. Captain B sees the names to match beside the confirm step."""
    match = to_in_progress(_popped(league, players))
    clock.advance(1800)
    results.submit_report(match.pk, match.captain_of("A").player, "A", image(1))
    read_scoreboard(match, strangers=1)
    return _scene(match, match.captain_of("B").player, _onlooker(league))


def disputed(league: Community, players: list[Player], clock: Clock) -> Scene:
    match = to_in_progress(_popped(league, players))
    clock.advance(1800)
    results.submit_report(match.pk, match.captain_of("A").player, "A", image(1))
    results.dispute(match.pk, match.captain_of("B").player, "We won that one.")
    return _scene(match, match.captain_of("B").player, _onlooker(league))


def completed(league: Community, players: list[Player], clock: Clock) -> Scene:
    match = to_in_progress(_popped(league, players))
    clock.advance(1800)
    return _scene(finish(match, "B"), None, _onlooker(league))


def ready_check_refill(league: Community, players: list[Player], clock: Clock) -> Scene:
    """Two missed the ready check. Their seats went to the two waiting in the queue: the first
    took one, the second hasn't answered. The player is the one who came in; the spectator is
    the one still deciding."""
    match = _popped(league, players)
    for player in players[:10]:
        lobby.mark_ready(match.pk, player)
    first, second = make_player(13), make_player(14)
    queue.join(league.pk, first)
    queue.join(league.pk, second)
    clock.advance(match.mode.ready_check.seconds + 1)
    deadlines.tick()
    clock.advance(20)
    (offer,) = SubOffer.objects.filter(player=first, status="pending")
    subs.answer_offer(offer.pk, first, accept=True)
    match = fresh(match)
    assert match.status == Status.READY_CHECK and match.held_seconds is not None
    return Scene(match, None, first, second)


def voided_ready_check(league: Community, players: list[Player], clock: Clock) -> Scene:
    """Not enough players ready: the lobby is cancelled and the ready players requeued. The
    spectator is the one who missed it, now on a cooldown."""
    match = _popped(league, players)
    for player in players[:11]:
        lobby.mark_ready(match.pk, player)
    clock.advance(match.mode.ready_check.seconds + 1)
    deadlines.tick()
    clock.advance(match.mode.ready_check.refill_seconds + 1)
    deadlines.tick()
    match = fresh(match)
    assert match.status == Status.VOIDED
    return Scene(match, None, players[0], players[11])


# --- Scrims -----------------------------------------------------------------------------------


def scrim_captain_claim(league: Community, players: list[Player], clock: Clock) -> Scene:
    match = scrims.start_claim(league.pk, CHANNEL, players[2])
    scrims.claim_captain(match.pk, players[0], "hk")
    return _scene(match, players[0], players[5])


def scrim_coinflip(league: Community, players: list[Player], clock: Clock) -> Scene:
    """The winner chose to pick last; the loser chooses a side."""
    match = scrims.start_coinflip(league.pk, CHANNEL, players[2], players[0], players[1])
    winner = match.participants.get(team=match.coinflip_winner).player
    draft.choose_coinflip(match.pk, winner, LAST_PICK)
    loser = match.participants.exclude(team=match.coinflip_winner).get().player
    return _scene(match, loser, players[5])


def scrim_ready_to_draft(league: Community, players: list[Player], clock: Clock) -> Scene:
    match = scrims.start_coinflip(league.pk, CHANNEL, players[2], players[0], players[1])
    winner = match.participants.get(team=match.coinflip_winner).player
    loser = match.participants.exclude(team=match.coinflip_winner).get().player
    draft.choose_coinflip(match.pk, winner, LAST_PICK)
    draft.choose_coinflip(match.pk, loser, ARCHMOTHER)
    return _scene(match, winner, players[5])


def _scrim_drafting(league: Community, players: list[Player]) -> Match:
    match = scrims.start_claim(league.pk, CHANNEL, players[2])
    scrims.claim_captain(match.pk, players[0], "hk")
    scrims.claim_captain(match.pk, players[1], "am")
    return fresh(match)


def scrim_champion_draft(league: Community, players: list[Player], clock: Clock) -> Scene:
    match = _scrim_drafting(league, players)
    for _ in range(2):
        champion = draft.available_champions(match)[0]
        draft.choose_champion(match.pk, acting_captain(match), match.step_index, champion)
        match = fresh(match)
    return _scene(match, acting_captain(match), players[5])


def scrim_drafted(league: Community, players: list[Player], clock: Clock) -> Scene:
    match = _scrim_drafting(league, players)
    while match.status == Status.CHAMPION_DRAFT:
        champion = draft.available_champions(match)[0]
        draft.choose_champion(match.pk, acting_captain(match), match.step_index, champion)
        match = fresh(match)
    assert match.status == Status.DRAFTED
    return _scene(match, players[0], players[5])


SCENES: list[Callable[[Community, list[Player], Clock], Scene]] = [
    ready_check,
    captain_phase,
    captain_checkin,
    player_draft,
    player_draft_sub_open,
    player_draft_sub_approval,
    player_draft_sub_naming,
    coinflip,
    champion_draft,
    champion_draft_swap_pending,
    lobby_code,
    lobby_code_failed,
    in_progress,
    in_progress_api_lobby,
    in_progress_api_started,
    in_progress_sub_offered,
    in_progress_early_leave,
    awaiting_confirmation,
    awaiting_confirmation_scoreboard,
    disputed,
    completed,
    ready_check_refill,
    voided_ready_check,
    scrim_captain_claim,
    scrim_coinflip,
    scrim_ready_to_draft,
    scrim_champion_draft,
    scrim_drafted,
]


# --- Normalising ------------------------------------------------------------------------------


# An avatar URL names its player by database ID: /avatar/<id>/<hash>.png.
AVATAR_PLAYER = re.compile(r"^/avatar/(\d+)/")


def _numbering() -> dict[str, dict[str, str]]:
    """Each kind's IDs, renumbered 1, 2, 3 by creation order."""
    tables = {
        "player": Player.objects,
        "match": Match.objects,
        "sub": SubRequest.objects,
        "offer": SubOffer.objects,
        "read": ScoreboardRead.objects,
        "swap": PlayerSwap.objects,
        "season": Season.objects,
        "chat": ChatMessage.objects,
    }
    return {
        kind: {
            str(pk): str(index)
            for index, pk in enumerate(manager.order_by("pk").values_list("pk", flat=True), 1)
        }
        for kind, manager in tables.items()
    }


def _normalise(value: Any, numbers: dict[str, dict[str, str]], key: str = "") -> Any:
    if isinstance(value, dict):
        out = {}
        for name, item in value.items():
            kind = ID_UNDER.get(key, "match" if not key else "") if name == "id" else ""
            if name in PLAYER_KEYS:
                kind = "player"
            elif name in MATCH_KEYS:
                kind = "match"
            elif name in SWAP_KEYS:
                kind = "swap"
            elif name in READ_KEYS:
                kind = "read"
            elif name in SEASON_KEYS:
                kind = "season"
            if kind and isinstance(item, str):
                out[name] = numbers[kind][item]
            elif name == "avatar_url" and isinstance(item, str):
                out[name] = AVATAR_PLAYER.sub(
                    lambda found: f"/avatar/{numbers['player'][found[1]]}/", item
                )
            elif name in PLAYER_LIST_KEYS:
                out[name] = [numbers["player"][pk] for pk in item]
            elif name == "deltas":
                out[name] = {numbers["player"][pk]: delta for pk, delta in item.items()}
            else:
                out[name] = _normalise(item, numbers, name)
        return out
    if isinstance(value, list):
        return [_normalise(item, numbers, key) for item in value]
    return value


def _has_key(value: Any, wanted: str) -> bool:
    if isinstance(value, dict):
        return wanted in value or any(_has_key(v, wanted) for v in value.values())
    if isinstance(value, list):
        return any(_has_key(item, wanted) for item in value)
    return False


# --- The test ---------------------------------------------------------------------------------


@pytest.mark.parametrize("scene", SCENES, ids=lambda scene: scene.__name__)
def test_fixture(
    frozen: None,
    clock: Clock,
    league: Community,
    scene: Callable[[Community, list[Player], Clock], Scene],
) -> None:
    players = [make_player(number) for number in range(1, 13)]
    # Two faces, so the fixtures show avatar URLs as well as initials.
    faces = ("a1b2c3d4e5f60718293a4b5c6d7e8f90", "0f1e2d3c4b5a6978")
    for player, avatar in zip(players[:2], faces, strict=True):
        Player.objects.filter(pk=player.pk).update(discord_avatar=avatar)
    played = scene(league, players, clock)
    name = scene.__name__

    body = snapshots.build_match(played.match.pk)
    assert body is not None
    views: dict[str, BaseModel] = {}
    viewers = {"captain": played.captain, "player": played.player, "spectator": played.spectator}
    for role, viewer in viewers.items():
        if viewer is None:
            continue
        views[role] = snapshots.project_match(body, viewer.pk)
        me = snapshots.build_me(viewer.pk, league.pk)
        assert me is not None
        views[f"me-{role}"] = me
    views["queue"] = snapshots.build_queue(league.pk)
    views["live"] = snapshots.build_live(league.pk)

    spectator_view = views["spectator"].model_dump(mode="json")
    assert spectator_view["lobby_code"] is None and not spectator_view["viewer"]["is_player"]
    if "captain" in views:
        assert views["captain"].model_dump(mode="json")["viewer"]["is_captain"]

    discord_ids = [str(uid) for uid in Player.objects.values_list("discord_user_id", flat=True)]
    numbers = _numbering()
    written = set()
    for view, model in views.items():
        data = model.model_dump(mode="json")
        # No Discord IDs anywhere, avatars included: those are served from /avatar/.
        text = json.dumps(data)
        assert not [uid for uid in discord_ids if uid in text], view
        if view.startswith("me-"):
            viewer = viewers[view.removeprefix("me-")]
            assert viewer is not None
            own = prio.place_of(league.pk, viewer.discord_user_id)
            place = data["queue"]["place"]
            if own is None:
                assert place is None, view
            else:
                assert (place["position"], place["total"]) == (own.position, own.total), view
        else:
            assert not _has_key(data, "place") and not _has_key(data, "held_until"), view
        _check(f"{name}.{view}.json", _normalise(data, numbers))
        written.add(f"{name}.{view}.json")
    on_disk = {path.name for path in FIXTURES.glob(f"{name}.*.json")}
    if UPDATE:
        for stale in on_disk - written:
            (FIXTURES / stale).unlink()
    else:
        assert on_disk == written, "Stale fixtures: rerun with UPDATE_WS_FIXTURES=1."


def _check(filename: str, data: Any) -> None:
    path = FIXTURES / filename
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    if UPDATE:
        FIXTURES.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        return
    assert path.exists(), f"{filename} is missing: rerun with UPDATE_WS_FIXTURES=1."
    assert json.loads(path.read_text(encoding="utf-8")) == data, (
        f"{filename} changed: rerun with UPDATE_WS_FIXTURES=1 and review the diff."
    )
