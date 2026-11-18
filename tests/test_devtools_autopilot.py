"""The autopilot: whole matches through the services or by simulated presses, scripts, and act."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from itertools import count
from typing import Any

import httpx
import pytest
from django.core.management import call_command

from devtools import api, autopilot, sim_client
from devtools.models import FrozenTimer
from league.domain.engine import RANKED_COINFLIP_CHOICES, Status
from league.domain.errors import DomainError
from league.models import (
    Community,
    DraftAction,
    Match,
    MatchResource,
    MatchResult,
    Player,
    PlayerRating,
    PlayerSwap,
    SubOffer,
    SubRequest,
)
from league.models.matches import ResourceKind
from league.models.subs import UNRESOLVED, OfferStatus
from league.services import draft, lobby, queue, results, subs, swaps
from league.services.results import ImageRef

pytestmark = pytest.mark.django_db


def ok(method: str, path: str, body: Any = None) -> dict[str, Any]:
    status, response = api.call(method, path, body)
    assert status == 200, response
    return response


def test_a_full_match_from_an_empty_queue_to_the_results(league: Community) -> None:
    created = ok(
        "POST", "players", {"count": 12, "rating": {"min": 600, "max": 1700}, "join_queue": True}
    )
    match_id = created["match_id"]
    assert match_id is not None

    result = ok("POST", f"matches/{match_id}/advance", {"until": "completed", "via": "service"})
    assert (result["from"], result["to"]) == ("ready_check", "completed")
    actions = [entry["action"] for entry in result["actions"]]
    assert actions.count("ready") == 12
    assert actions.count("vote") == 12
    assert actions.count("checkin") == 2
    # Ten player draft steps, the last of them filled by the league itself, then 18 champions.
    assert actions.count("pick") + actions.count("ban") == 9 + 18
    assert actions[-4:] == ["api_lobby", "start_match", "report", "confirm"]
    assert {entry["via"] for entry in result["actions"]} == {"service"}
    phases = [phase["status"] for phase in result["phases"]]
    assert phases == list(autopilot.ORDER[:-1])
    assert all(phase["seconds"] >= 0 for phase in result["phases"])

    match = Match.objects.get(pk=match_id)
    assert match.status == Status.COMPLETED
    assert match.winner == "A"
    assert match.api_started_at is not None
    assert MatchResult.objects.filter(match=match).exists()
    assert PlayerRating.objects.filter(games=1).count() == 12
    call_command("check_ledger")


def test_without_until_advance_completes_only_the_current_phase(popped: Match) -> None:
    steps = ["captain_phase", "captain_checkin", "player_draft", "coinflip"]
    for status in steps:
        result = ok("POST", "matches/latest/advance", {"via": "service"})
        assert result["to"] == status
    assert len(result["actions"]) == 9


def test_advance_to_a_status_already_reached_does_nothing(popped: Match) -> None:
    ok("POST", "matches/latest/advance", {"until": "player_draft", "via": "service"})
    body = ok("POST", "matches/latest/advance", {"until": "captain_checkin"})
    assert (body["from"], body["to"], body["actions"]) == ("player_draft", "player_draft", [])
    status, _ = api.call("POST", "matches/latest/advance", {"until": "nowhere"})
    assert status == 400
    status, _ = api.call("POST", "matches/latest/advance", {"via": "carrier pigeon"})
    assert status == 400


def test_advance_stops_on_a_match_on_hold(popped: Match) -> None:
    ok("POST", "matches/latest/act", {"action": "request_sub", "player_id": "participant:3"})
    status, body = api.call("POST", "matches/latest/advance", {"via": "service"})
    assert status == 409
    assert "on hold" in body["error"]["message"]


def test_the_script_decides_votes_draft_coinflip_champions_code_and_winner(popped: Match) -> None:
    ids = list(popped.participants.order_by("pk").values_list("player_id", flat=True))
    captains = ids[10:12]
    draft_order = [ids[9], ids[0], ids[8]]
    ok(
        "PUT",
        f"matches/{popped.pk}/script",
        {
            "captain_votes": {"*": captains},
            "draft": draft_order,
            "coinflip": "archmother",
            "champions": [{"step": 0, "slug": "seven"}, {"step": 1, "slug": "haze"}],
            "lobby_code": "SCRIPTED",
            "winner": "B",
        },
    )
    ok("POST", "matches/latest/advance", {"until": "completed", "via": "service"})
    match = Match.objects.get(pk=popped.pk)
    assert set(
        match.participants.filter(is_captain=True).values_list("player_id", flat=True)
    ) == set(captains)
    picked = list(
        DraftAction.objects.filter(match=match, action="player_pick")
        .order_by("step_index")
        .values_list("target_player_id", flat=True)
    )
    assert picked[:3] == draft_order
    champions = list(
        DraftAction.objects.filter(match=match)
        .exclude(action="player_pick")
        .order_by("step_index")
        .values_list("target_champion__slug", flat=True)
    )
    assert champions[:2] == ["seven", "haze"]
    assert match.coinflip_winner_choice == "archmother"
    assert match.hidden_king_team != match.coinflip_winner
    assert match.lobby_code == "SCRIPTED"
    assert match.winner == "B"


def test_a_teams_champion_preferences_are_picked_and_banned(popped: Match) -> None:
    ok("POST", "matches/latest/advance", {"until": "champion_draft", "via": "service"})
    match = Match.objects.get(pk=popped.pk)
    first = match.champion_first_pick
    second = "B" if first == "A" else "A"
    ok(
        "PUT",
        f"players/{match.captain_of(first).player_id}/picks",
        {"prefer": ["mirage"], "ban": ["lash"]},
    )
    ok("PUT", f"players/{match.captain_of(second).player_id}/picks", {"ban": ["lash", "warden"]})
    ok("POST", "matches/latest/advance", {"via": "service"})
    rows = list(
        DraftAction.objects.filter(match=match)
        .exclude(action="player_pick")
        .order_by("step_index")
        .values_list("action", "team", "target_champion__slug")
    )
    # The first ban is the first team's; the second team's first choice is gone, so its next.
    assert rows[0] == ("ban", first, "lash")
    assert rows[1] == ("ban", second, "warden")
    assert ("pick", first, "mirage") in rows


def test_act_with_selectors_and_defaults(popped: Match) -> None:
    body = ok("POST", "matches/latest/act", {"action": "ready"})
    first = body["actions"][0]["player_id"]
    assert first == popped.participants.order_by("pk")[0].player_id
    body = ok(
        "POST",
        "matches/latest/act",
        {"action": "ready", "player_ids": [f"participant:{n}" for n in range(2, 13)]},
    )
    assert body["match"]["status"] == "captain_phase"
    ok("POST", "matches/latest/advance", {"until": "captain_checkin", "via": "service"})
    body = ok("POST", "matches/latest/act", {"action": "checkin"})
    assert body["match"]["turn"] == {
        "action": "checkin",
        "team": None,
        "player_ids": [body["match"]["captains"]["B"]],
    }
    ok("POST", "matches/latest/act", {"action": "checkin", "player_id": "captain:B"})
    body = ok("POST", "matches/latest/act", {"action": "pick", "player_id": "acting"})
    assert body["match"]["picks"][0]["action"] == "player_pick"
    status, _ = api.call("POST", "matches/latest/act", {"action": "ban"})
    assert status == 400
    status, _ = api.call("POST", "matches/latest/act", {"action": "dance", "player_id": 1})
    assert status in {400, 404}
    status, _ = api.call("POST", "matches/latest/act", {"action": "ready", "player_id": "wizard"})
    assert status == 400


def test_a_missed_checkin_hands_the_captaincy_on(popped: Match) -> None:
    ok("POST", "matches/latest/advance", {"until": "captain_checkin", "via": "service"})
    before = ok("GET", "matches/latest")["captains"]
    ok("POST", "matches/latest/act", {"action": "checkin", "player_id": "captain:A"})
    body = ok("POST", "matches/latest/fire")
    assert body["fired"]
    captains = body["match"]["captains"]
    assert captains["A"] == before["A"] and captains["B"] != before["B"]
    missed = [p for p in body["match"]["players"] if p["missed_checkin"]]
    assert [p["id"] for p in missed] == [before["B"]]
    assert body["match"]["turn"]["player_ids"] == [captains["B"]]


def test_a_refused_lobby_falls_back_to_the_host(popped: Match) -> None:
    ok("PUT", "lobbies", {"lobby": "fail"})
    ok("POST", "matches/latest/advance", {"until": "lobby_code", "via": "service"})
    body = ok("POST", "matches/latest/act", {"action": "api_lobby"})
    assert body["actions"][0]["args"] == {"create": False}
    match = body["match"]
    assert match["api_lobby"]["failed"] and match["turn"]["action"] == "lobby_code"
    body = ok("POST", "matches/latest/act", {"action": "lobby_code", "player_id": "host"})
    assert (body["match"]["status"], body["match"]["lobby_code"]) == (
        "in_progress",
        f"DEV{popped.pk}",
    )
    assert body["match"]["turn"]["action"] == "report"


def test_captains_swap_two_players(popped: Match) -> None:
    ok("POST", "matches/latest/advance", {"until": "coinflip", "via": "service"})
    match = Match.objects.get(pk=popped.pk)
    give = autopilot._first_of_team(match, "A")
    take = autopilot._first_of_team(match, "B")
    body = ok("POST", "matches/latest/act", {"action": "swap"})
    assert body["actions"][0]["args"] == {"give": give, "take": take}
    [offer] = body["match"]["swaps"]
    assert offer["status"] == "pending" and body["match"]["swap_open"]
    ok("POST", "matches/latest/act", {"action": "accept_swap"})
    teams = ok("GET", "matches/latest")["teams"]
    assert give in teams["B"] and take in teams["A"]
    ok("POST", "matches/latest/act", {"action": "swap", "args": {"give": take, "take": give}})
    body = ok("POST", "matches/latest/act", {"action": "decline_swap"})
    assert body["match"]["swaps"][-1]["status"] == "declined"
    status, _ = api.call("POST", "matches/latest/act", {"action": "decline_swap"})
    assert status == 409
    # An offer's answer clock is one of the match's timers: a pause parks it too.
    ok("POST", "matches/latest/act", {"action": "swap"})
    ok("POST", "matches/latest/pause")
    assert FrozenTimer.objects.filter(model="playerswap").exists()


def test_act_reports_disputes_and_resolves(popped: Match) -> None:
    ok("POST", "matches/latest/advance", {"until": "in_progress", "via": "service"})
    ok(
        "POST",
        "matches/latest/act",
        {"action": "report", "player_id": "captain:A", "args": {"winner": "A"}},
    )
    body = ok("POST", "matches/latest/act", {"action": "dispute", "player_id": "other_captain"})
    assert body["match"]["status"] == "disputed"
    assert body["match"]["turn"]["action"] == "resolve"
    body = ok("POST", "matches/latest/act", {"action": "resolve", "args": {"outcome": "B"}})
    assert body["actions"][0]["via"] == "service"
    assert body["match"]["status"] == "completed"
    assert body["match"]["winner"] == "B"


def test_act_runs_a_sub_through_request_offer_and_accept(league: Community, popped: Match) -> None:
    spare = ok("POST", "players", {"count": 1, "join_queue": True})["players"][0]
    ok("POST", "matches/latest/act", {"action": "request_sub", "player_id": "participant:4"})
    body = ok("POST", "matches/latest/act", {"action": "offer_queue", "player_id": "requester"})
    assert body["match"]["on_hold"]
    [request] = body["match"]["sub_requests"]
    assert request["offers"][0]["player_id"] == spare["id"]
    body = ok("POST", "matches/latest/act", {"action": "accept_sub", "player_id": "offered"})
    assert not body["match"]["on_hold"]
    assert SubRequest.objects.get().status == "filled"
    assert spare["id"] in [p["id"] for p in body["match"]["players"] if p["active"]]


def test_void_is_a_staff_action(popped: Match) -> None:
    body = ok("POST", "matches/latest/act", {"action": "void", "args": {"reason": "testing"}})
    assert body["match"]["status"] == "voided"
    status, _ = api.call("POST", "matches/latest/advance", {})
    assert status == 409


# --- Through the simulator -------------------------------------------------------------------


Message = dict[str, Any]


def button(custom_id: str, label: str = "") -> dict[str, Any]:
    return {"type": 2, "custom_id": custom_id, "label": label or custom_id.split(":")[2]}


class BotLikeSim:
    """The simulator's control API, with the bot stood in by service calls.

    Its messages carry the bot's real custom_ids, as the board, the pickers a press opens, the
    DMs and the staff channel's cards render them, so the presser is checked against the formats
    the bot uses. A refusal comes back as the bot's plain-text reply. `idle` makes presses do
    nothing, like a bot that isn't running; `lobbies` is the deadlock-api stand-in's answer.
    """

    CHANNEL = 4242
    STAFF = 4343
    QUEUE = 4444
    OWNER = 42

    def __init__(self, match: Match) -> None:
        self.match_id = match.pk
        self.calls: list[tuple[str, Any]] = []
        self.opened: dict[int, str] = {}
        self.pickers: dict[int, list[dict[str, Any]]] = {}
        self.answers: dict[str, dict[str, Any]] = {}
        self.ids = count(1)
        self.idle = False
        self.lobbies = "create"
        MatchResource.objects.create(match=match, kind=ResourceKind.TEXT, discord_id=self.CHANNEL)
        Community.objects.filter(pk=match.community_id).update(
            staff_channel_id=self.STAFF, queue_channel_id=self.QUEUE
        )

    def match(self) -> Match:
        return Match.objects.select_related("community").get(pk=self.match_id)

    def board(self) -> list[dict[str, Any]]:
        match, mid = self.match(), self.match_id
        components: list[dict[str, Any]] = []
        status = match.status
        if status == Status.READY_CHECK:
            components.append(button(f"dl:v1:ready:{mid}:", "Ready"))
        elif status == Status.CAPTAIN_PHASE:
            options = [
                {"value": str(p.player_id)} for p in match.participants.filter(is_active=True)
            ]
            components.append(
                {"type": 3, "custom_id": f"dl:v1s:captain_vote:{mid}:", "options": options}
            )
        elif status == Status.CAPTAIN_CHECKIN:
            components.append(button(f"dl:v1:checkin:{mid}:", "I'm here"))
        elif status == Status.PLAYER_DRAFT:
            for p in match.participants.filter(is_active=True, team=""):
                step = f"{match.step_index}.{p.player_id}"
                components.append(button(f"dl:v1:pick_player:{mid}:{step}"))
        elif status == Status.COINFLIP:
            for choice in RANKED_COINFLIP_CHOICES:
                components.append(button(f"dl:v1:coin_choice:{mid}:{choice}"))
        elif status == Status.CHAMPION_DRAFT:
            for cid in draft.available_champions(match):
                step = f"{match.step_index}.{cid}"
                components.append(button(f"dl:v1:choose_champion:{mid}:{step}"))
        elif status == Status.LOBBY_CODE and match.api_lobby_failed:
            components.append(button(f"dl:v1:code_open:{mid}:", "Enter lobby code"))
        elif status == Status.IN_PROGRESS:
            if match.api_party_id and match.api_started_at is None:
                components.append(button(f"dl:v1:api_start:{mid}:", "Start match"))
            for team in "AB":
                components.append(button(f"dl:v1:report_open:{mid}:{team}"))
        elif status == Status.AWAITING_CONFIRMATION:
            components.append(button(f"dl:v1:confirm:{mid}:", "Confirm"))
            components.append(button(f"dl:v1:dispute_open:{mid}:", "Dispute"))
        for request in match.sub_requests.filter(status__in=UNRESOLVED):
            components.append(button(f"dl:v1:sub_queue:{mid}:{request.pk}", "Ask the queue"))
            components.append(button(f"dl:v1:sub_cancel:{mid}:{request.pk}", "Cancel sub"))
        pending = swaps.pending(match)
        if pending is not None:
            components.append(button(f"dl:v1:swap_yes:{mid}:{pending.pk}", "Accept swap"))
            components.append(button(f"dl:v1:swap_no:{mid}:{pending.pk}", "Decline"))
        elif status in swaps.SWAPPABLE:
            components.append(button(f"dl:v1:swap_open:{mid}:", "Swap players"))
        components.append(button(f"dl:v1:sub_open:{mid}:", "Request a sub"))
        return components

    def channel_messages(self) -> list[Message]:
        messages: list[Message] = [
            {
                "id": "100",
                "components": [{"type": 2, "custom_id": "dl:v1:old:0:", "disabled": True}],
            },
            {"id": "200", "components": self.board()},
        ]
        for user_id, components in self.pickers.items():
            messages.append(
                {
                    "id": str(300 + user_id % 1000),
                    "ephemeral": True,
                    "ephemeral_for": str(user_id),
                    "components": components,
                }
            )
        return messages

    def staff_messages(self) -> list[Message]:
        mid = self.match_id
        if self.match().status != Status.DISPUTED:
            return []
        cards = [button(f"dl:v1:{name}:{mid}:") for name in ("resolve_a", "resolve_b")]
        return [{"id": "900", "components": cards}]

    def dms(self, user_id: int) -> list[Message]:
        offers = SubOffer.objects.filter(
            player__discord_user_id=user_id, status=OfferStatus.PENDING
        )
        return [
            {
                "id": str(1000 + offer.pk),
                "components": [
                    button(f"dl:v1:sub_accept:{self.match_id}:{offer.pk}", "I'll sub in"),
                    button(f"dl:v1:sub_decline:{self.match_id}:{offer.pk}", "Can't right now"),
                ],
            }
            for offer in offers
        ]

    def bot_effects(self) -> None:
        """What the bot's effects would do next: settle a lobby with deadlock-api."""
        match = self.match()
        if match.status == Status.LOBBY_CODE and not match.api_lobby_failed:
            if self.lobbies == "create":
                draft.accept_api_lobby(match.pk, "party-1", "ABC123")
            else:
                draft.api_lobby_failed(match.pk, "refused")

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        path = request.url.path
        self.calls.append((path, body))
        if path == "/_sim/health":
            return httpx.Response(200, json={"ok": True})
        if path == "/_sim/state":
            return httpx.Response(200, json={"guild": {"id": "1", "owner_id": str(self.OWNER)}})
        if path == "/_sim/deadlock-api":
            self.lobbies = body["lobby"]
            return httpx.Response(200, json={"lobby": self.lobbies})
        if path == f"/_sim/channels/{self.CHANNEL}/messages":
            return httpx.Response(200, json={"messages": self.channel_messages()})
        if path == f"/_sim/channels/{self.QUEUE}/messages":
            panel = [button("dl:v1:join:0:", "Join"), button("dl:v1:leave:0:", "Leave")]
            return httpx.Response(200, json={"messages": [{"id": "50", "components": panel}]})
        if path == f"/_sim/channels/{self.STAFF}/messages":
            return httpx.Response(200, json={"messages": self.staff_messages()})
        if path.endswith("/dms"):
            user_id = int(path.split("/")[-2])
            return httpx.Response(200, json={"messages": self.dms(user_id)})
        if path.startswith("/_sim/interactions/") and request.method == "GET":
            return httpx.Response(200, json=self.answers[path.rsplit("/", 1)[1]])
        if path == "/_sim/users":
            users = [{"id": str(77_000 + n), "name": f"Spare {n}"} for n in range(body["count"])]
            return httpx.Response(201, json={"users": users})
        if self.idle:
            self.answers["0"] = {"interaction_id": "0", "modal": None}
            return httpx.Response(200, json=self.answers["0"])
        user_id = int(body["user_id"])
        user = Player.objects.from_discord(user_id, "Owner" if user_id == self.OWNER else "?")
        answer: dict[str, Any] = {"interaction_id": str(next(self.ids)), "modal": None}
        try:
            if path == "/_sim/interactions/component":
                answer["modal"] = self.component(user, body["custom_id"], body.get("values"))
            elif path == "/_sim/interactions/modal":
                self.submit(user, body)
        except DomainError as exc:
            answer["message"] = {"content": exc.message, "components": []}
        self.bot_effects()
        self.answers[answer["interaction_id"]] = answer
        return httpx.Response(200, json=answer)

    def component(
        self, user: Any, custom_id: str, values: list[str] | None
    ) -> dict[str, Any] | None:
        _, _, action, _, arg = custom_id.split(":")
        mid = self.match_id
        handlers: dict[str, Callable[[], Any]] = {
            "ready": lambda: lobby.mark_ready(mid, user),
            "join": lambda: queue.join(self.match().community_id, user),
            "leave": lambda: queue.leave(self.match().community_id, user),
            "captain_vote": lambda: lobby.cast_captain_votes(
                mid, user, [int(v) for v in values or []]
            ),
            "checkin": lambda: lobby.check_in(mid, user),
            "coin_choice": lambda: draft.choose_coinflip(mid, user, arg),
            "api_start": lambda: draft.mark_api_started(mid, user),
            "confirm": lambda: results.confirm(mid, user),
            "swap_yes": lambda: swaps.answer(mid, user, int(arg), True),
            "swap_no": lambda: swaps.answer(mid, user, int(arg), False),
            "swap_take": lambda: swaps.propose(mid, user, *map(int, arg.split("."))),
            "sub_out": lambda: subs.request_sub_out(mid, user, int(arg)),
            "sub_queue": lambda: subs.offer_to_queue(int(arg), user),
            "sub_cancel": lambda: subs.cancel_sub(int(arg), user),
            "sub_accept": lambda: subs.answer_offer(int(arg), user, True),
            "sub_decline": lambda: subs.answer_offer(int(arg), user, False),
            "resolve_a": lambda: results.resolve_dispute(mid, "A", user, "staff"),
            "resolve_b": lambda: results.resolve_dispute(mid, "B", user, "staff"),
        }
        if action in {"pick_player", "choose_champion"}:
            step, target = arg.split(".")
            pick = draft.pick_player if action == "pick_player" else draft.choose_champion
            pick(mid, user, int(step), int(target))
        elif action == "swap_open":
            match = self.match()
            team = match.participants.get(player=user).team
            give = match.participants.filter(team=team, is_captain=False, is_active=True)
            self.pickers[user.discord_user_id] = [
                button(f"dl:v1:swap_give:{mid}:{p.player_id}") for p in give
            ]
        elif action == "swap_give":
            match = self.match()
            team = match.participants.get(player=user).team
            take = match.participants.filter(is_captain=False, is_active=True).exclude(team=team)
            self.pickers[user.discord_user_id] = [
                button(f"dl:v1:swap_take:{mid}:{arg}.{p.player_id}") for p in take
            ]
        elif action == "sub_open":
            self.pickers[user.discord_user_id] = [button(f"dl:v1:sub_out:{mid}:{user.pk}")]
        elif action in {"report_open", "code_open", "dispute_open"}:
            if action == "code_open":
                draft.check_lobby_host(mid, user)
            self.opened[user.pk] = f"{action}:{arg}"
            upload = {"type": 18, "component": {"type": 19, "custom_id": "shot"}}
            text = {"type": 18, "component": {"type": 4, "custom_id": "text"}}
            optional = {"type": 18, "component": {"type": 4, "custom_id": "id", "required": False}}
            rows = [upload, optional] if action == "report_open" else [text]
            return {"custom_id": "modal", "components": rows}
        else:
            handlers[action]()
        if action not in {"swap_open", "swap_give", "sub_open"}:
            self.pickers.pop(user.discord_user_id, None)
        return None

    def submit(self, user: Any, body: dict[str, Any]) -> None:
        action, _, arg = self.opened.pop(user.pk).partition(":")
        if action == "code_open":
            draft.submit_lobby_code(self.match_id, user, body["values"]["text"])
        elif action == "dispute_open":
            results.dispute(self.match_id, user, body["values"]["text"])
        else:
            assert body["attachments"] == {"shot": [{"filename": "scoreboard.png"}]}
            assert body["values"] == {"id": ""}
            image = ImageRef(
                sha256="f" * 64, archive_channel_id=1, archive_message_id=7, attachment_id=8
            )
            results.submit_report(self.match_id, user, arg, image)

    def pressed(self) -> list[str]:
        """The action of every component pressed, in order."""
        return [
            body["custom_id"].split(":")[2]
            for path, body in self.calls
            if path == "/_sim/interactions/component"
        ]


@pytest.fixture
def sim(popped: Match, settings: Any, monkeypatch: pytest.MonkeyPatch) -> Iterator[BotLikeSim]:
    fake = BotLikeSim(popped)
    settings.DISCORD_SIM_URL = "http://sim.test"
    monkeypatch.setattr(sim_client, "TRANSPORT", httpx.MockTransport(fake.handle))
    monkeypatch.setattr(autopilot, "POLL_SECONDS", 0.01)
    monkeypatch.setattr(autopilot, "ANSWER_POLL_SECONDS", 0.01)
    yield fake


def test_a_full_match_by_pressing_as_each_player(sim: BotLikeSim) -> None:
    result = ok("POST", "matches/latest/advance", {"until": "completed"})
    assert result["to"] == "completed"
    assert {entry["via"] for entry in result["actions"]} == {"discord"}
    pressed = sim.pressed()
    assert pressed.count("ready") == 12 and pressed.count("captain_vote") == 12
    assert pressed.count("checkin") == 2 and pressed.count("pick_player") == 9
    assert pressed.count("choose_champion") == 18
    assert pressed[-4:] == ["choose_champion", "api_start", "report_open", "confirm"]
    assert [path for path, _ in sim.calls].count("/_sim/interactions/modal") == 1
    votes = [
        body
        for path, body in sim.calls
        if path == "/_sim/interactions/component" and ":captain_vote:" in body["custom_id"]
    ]
    assert len(votes) == 12 and all(body["message_id"] == "200" for body in votes)
    match = Match.objects.get(pk=sim.match_id)
    assert (match.lobby_code, match.api_party_id) == ("ABC123", "party-1")
    call_command("check_ledger")


def test_a_refused_lobby_is_entered_through_the_form(sim: BotLikeSim) -> None:
    ok("PUT", "lobbies", {"lobby": "fail"})
    assert sim.lobbies == "fail"
    ok("POST", "matches/latest/advance", {"until": "in_progress"})
    match = Match.objects.get(pk=sim.match_id)
    assert (match.lobby_code, match.api_lobby_failed) == (f"DEV{match.pk}", True)
    assert "code_open" in sim.pressed()


def test_disputes_are_resolved_on_the_staff_card(sim: BotLikeSim) -> None:
    ok("POST", "matches/latest/advance", {"until": "awaiting_confirmation"})
    ok("POST", "matches/latest/act", {"action": "dispute", "player_id": "other_captain"})
    body = ok("POST", "matches/latest/act", {"action": "resolve", "args": {"outcome": "B"}})
    assert body["actions"][0]["via"] == "discord"
    assert body["match"]["winner"] == "B"
    assert sim.pressed()[-1] == "resolve_b"


def test_swaps_and_subs_go_through_the_bot_too(sim: BotLikeSim, league: Community) -> None:
    spare = ok("POST", "players", {"count": 1, "join_queue": True})["players"][0]
    ok("POST", "matches/latest/act", {"action": "request_sub", "player_id": "participant:4"})
    ok("POST", "matches/latest/act", {"action": "offer_queue", "player_id": "requester"})
    body = ok("POST", "matches/latest/act", {"action": "accept_sub", "player_id": "offered"})
    assert {entry["via"] for entry in body["actions"]} == {"discord"}
    assert SubRequest.objects.get().status == "filled"
    assert spare["id"] in [p["id"] for p in body["match"]["players"] if p["active"]]
    assert sim.pressed() == ["sub_open", "sub_out", "sub_queue", "sub_accept"]

    ok("POST", "matches/latest/advance", {"until": "coinflip"})
    ok("POST", "matches/latest/act", {"action": "swap"})
    ok("POST", "matches/latest/act", {"action": "accept_swap"})
    assert PlayerSwap.objects.get().status == "accepted"
    assert sim.pressed()[-4:] == ["swap_open", "swap_give", "swap_take", "swap_yes"]


def test_the_queue_is_joined_and_left_on_its_panel(sim: BotLikeSim) -> None:
    ids = [p["id"] for p in ok("POST", "players", {"count": 2})["players"]]
    body = ok("POST", "queue/join", {"player_ids": ids})
    assert [entry["player"]["id"] for entry in body["queue"]] == ids
    assert body["match_id"] is None
    body = ok("POST", "queue/leave", {"player_ids": ids[:1]})
    assert [entry["player"]["id"] for entry in body["queue"]] == ids[1:]
    assert sim.pressed() == ["join", "join", "leave"]
    status, body = api.call("POST", "queue/join", {"player_ids": ids[1:]})
    assert status == 409 and "the queue" in body["error"]["message"]


def test_the_bots_refusal_is_a_409_with_its_words(sim: BotLikeSim) -> None:
    ok("POST", "matches/latest/advance", {"until": "captain_checkin"})
    ok("POST", "matches/latest/act", {"action": "checkin", "player_id": "captain:A"})
    status, body = api.call(
        "POST", "matches/latest/act", {"action": "checkin", "player_id": "captain:A"}
    )
    assert status == 409
    assert "You've already checked in" in body["error"]["message"]
    assert "captain_checkin" in body["error"]["message"]


def test_an_idle_bot_times_out_naming_the_phase(
    sim: BotLikeSim, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(autopilot, "BOT_WAIT_SECONDS", 0.2)
    sim.idle = True
    status, body = api.call("POST", "matches/latest/act", {"action": "ready"})
    assert status == 504
    assert body["error"]["code"] == "timeout"
    assert "ready_check" in body["error"]["message"]


def test_a_missing_component_times_out_listing_what_is_there(
    sim: BotLikeSim, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(autopilot, "BOT_WAIT_SECONDS", 0.2)
    status, body = api.call(
        "POST", "matches/latest/act", {"action": "confirm", "player_id": "participant:1"}
    )
    assert status == 504
    assert "Confirm button" in body["error"]["message"]
    assert "Ready" in body["error"]["message"] and "Request a sub" in body["error"]["message"]


def test_void_goes_through_the_service_even_via_discord(sim: BotLikeSim) -> None:
    body = ok("POST", "matches/latest/act", {"action": "void", "via": "discord"})
    assert body["actions"][0]["via"] == "service"
    assert body["match"]["status"] == "voided"


def test_a_message_replaced_under_a_press_is_pressed_again(
    sim: BotLikeSim, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = sim.handle
    gone = {"left": 1}

    def flaky(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/_sim/interactions/component" and gone["left"]:
            gone["left"] -= 1
            return httpx.Response(404, json={"error": "No message with that message_id."})
        return real(request)

    monkeypatch.setattr(sim_client, "TRANSPORT", httpx.MockTransport(flaky))
    body = ok("POST", "matches/latest/act", {"action": "ready"})
    assert body["actions"][0]["via"] == "discord"
    assert sim.pressed() == ["ready"]


def test_a_simulator_error_is_a_502(sim: BotLikeSim, monkeypatch: pytest.MonkeyPatch) -> None:
    real = sim.handle

    def broken(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/_sim/interactions/component":
            return httpx.Response(504, json={"error": "The bot didn't answer in time."})
        return real(request)

    monkeypatch.setattr(sim_client, "TRANSPORT", httpx.MockTransport(broken))
    status, body = api.call("POST", "matches/latest/act", {"action": "ready"})
    assert status == 502
    assert "didn't answer" in body["error"]["message"]
    assert "ready_check" in body["error"]["message"]


NO_BOT = {"error": "No bot is connected to the gateway.", "reason": "no_bot"}


def test_no_bot_on_the_gateway_is_a_503_not_a_timeout(
    sim: BotLikeSim, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A press with nobody to answer it is waited out like a replaced message, but reported as
    the bot being offline, not as the bot never posting the button."""
    monkeypatch.setattr(autopilot, "BOT_WAIT_SECONDS", 0.3)
    real = sim.handle

    def offline(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/_sim/interactions/component":
            return httpx.Response(503, json=NO_BOT)
        return real(request)

    monkeypatch.setattr(sim_client, "TRANSPORT", httpx.MockTransport(offline))
    status, body = api.call("POST", "matches/latest/act", {"action": "ready"})
    assert status == 503, body
    assert body["error"]["code"] == "bot_offline"
    assert "no bot is connected" in body["error"]["message"]
    assert "the Ready button" in body["error"]["message"]


def test_a_bot_that_reconnects_within_the_wait_gets_the_press(
    sim: BotLikeSim, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = sim.handle
    down = {"left": 2}

    def reconnecting(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/_sim/interactions/component" and down["left"]:
            down["left"] -= 1
            return httpx.Response(503, json=NO_BOT)
        return real(request)

    monkeypatch.setattr(sim_client, "TRANSPORT", httpx.MockTransport(reconnecting))
    body = ok("POST", "matches/latest/act", {"action": "ready"})
    assert body["actions"][0]["via"] == "discord"
    assert sim.pressed() == ["ready"]


def test_a_champion_grid_that_never_comes_times_out_once(
    sim: BotLikeSim, monkeypatch: pytest.MonkeyPatch
) -> None:
    ok("POST", "matches/latest/advance", {"until": "champion_draft", "via": "service"})
    monkeypatch.setattr(autopilot, "BOT_WAIT_SECONDS", 0.5)
    monkeypatch.setattr(sim, "channel_messages", list)  # The bot posts no grid, no dropdown.
    # A clock that only the waits move, so a busy test host can't stretch the measurement.
    clock = FakeClock()
    monkeypatch.setattr(autopilot, "time", clock)
    status, body = api.call("POST", "matches/latest/act", {"action": "ban"})
    assert status == 504, body
    assert "champion grid (step" in body["error"]["message"]
    assert 0.5 <= clock.now < 0.95  # One wait of 0.5 s, not a second one on top.


class FakeClock:
    """`time.monotonic` and `time.sleep` for the autopilot: sleeping is the only thing that
    takes time."""

    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds
