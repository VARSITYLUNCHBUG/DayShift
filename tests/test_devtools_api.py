"""The dev control API over HTTP: every players, queue, plan and lookup endpoint, and its errors."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from django.core.management import call_command
from django.test import Client

from devtools import api, sim_client
from devtools.control import LOCAL_ID_BASE
from devtools.models import DevProfile
from league.models import Community, Match, Player, PlayerRating, QueueEntry
from league.services import queue

pytestmark = [pytest.mark.urls("config.urls_dev"), pytest.mark.django_db]

BASE = "/_control/api/"


def call(client: Client, method: str, path: str, body: Any = None) -> tuple[int, Any]:
    response = client.generic(
        method,
        BASE + path,
        data=json.dumps(body) if body is not None else "",
        content_type="application/json",
    )
    return response.status_code, response.json()


@pytest.fixture
def http(client: Client) -> Client:
    # The CSRF check is on, as in the real app: the API must be exempt.
    return Client(enforce_csrf_checks=True)


class FakeSim:
    """The simulator's user endpoints, recording what was asked."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []
        self.next_id = 1_100_000_000_000_010_000

    def handle(self, request: httpx.Request) -> httpx.Response:
        body: Any = json.loads(request.content) if request.content else None
        self.calls.append((request.method, request.url.path, body))
        if request.url.path == "/_sim/users" and request.method == "POST":
            users = []
            for index in range(body["count"]):
                self.next_id += 1
                users.append({"id": str(self.next_id), "name": f"{body['name_prefix']}{index}"})
            return httpx.Response(201, json={"users": users})
        return httpx.Response(200, json={"ok": True})


@pytest.fixture
def sim(settings: Any, monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeSim]:
    fake = FakeSim()
    settings.DISCORD_SIM_URL = "http://sim.test"
    monkeypatch.setattr(sim_client, "TRANSPORT", httpx.MockTransport(fake.handle))
    yield fake


def ledger_ok() -> None:
    call_command("check_ledger")


def test_index_lists_every_route(http: Client) -> None:
    status, body = call(http, "GET", "")
    assert status == 200
    listed = {(route["method"], route["path"]) for route in body["routes"]}
    assert listed == {(route.method, route.path) for route in api.ROUTES}
    assert ("POST", "matches/{match}/advance") in listed


def test_state_before_any_community(http: Client) -> None:
    status, body = call(http, "GET", "state")
    assert status == 200
    assert body["community"] is None
    assert body["sim"] == {"configured": False, "reachable": False, "url": None}


def test_state_shows_the_queue_and_live_matches(http: Client, popped: Match) -> None:
    status, body = call(http, "GET", "state")
    assert status == 200
    assert body["community"]["guild_id"] == "999"
    assert body["lobby_size"] == 12
    [match] = body["matches"]
    assert match["id"] == popped.pk
    assert match["status"] == "ready_check"
    assert match["turn"]["action"] == "ready"
    assert len(match["turn"]["player_ids"]) == 12
    assert match["seconds_left"] > 100
    assert body["timers"] == {"paused_all": False, "frozen_matches": []}
    assert body["lobbies"] == "create"
    assert body["community"]["settings"]["interim_points"] is False
    assert match["api_lobby"] == {"failed": False, "party_id": None, "started": False}


def test_lobbies_are_set_for_the_simulator_and_the_services(http: Client, sim: FakeSim) -> None:
    status, body = call(http, "PUT", "lobbies", {"lobby": "fail"})
    assert (status, body) == (200, {"lobbies": "fail"})
    assert ("PUT", "/_sim/deadlock-api", {"lobby": "fail"}) in sim.calls
    assert call(http, "GET", "state")[1]["lobbies"] == "fail"
    assert call(http, "PUT", "lobbies", {"lobby": "sometimes"})[0] == 400


def test_new_players_get_local_ids_spread_ratings_and_a_queue_place(
    http: Client, league: Community
) -> None:
    status, body = call(
        http,
        "POST",
        "players",
        {"count": 3, "rating": {"min": 800, "max": 1200}, "join_queue": True, "name_prefix": "T"},
    )
    assert status == 200
    players = body["players"]
    assert [p["rating"] for p in players] == [800, 1000, 1200]
    assert [p["queue_position"] for p in players] == [1, 2, 3]
    assert all(int(p["discord_user_id"]) > LOCAL_ID_BASE for p in players)
    assert all(isinstance(p["discord_user_id"], str) for p in players)
    assert body["match_id"] is None
    ledger_ok()


def test_the_twelfth_new_player_pops_a_lobby(http: Client, league: Community) -> None:
    status, body = call(http, "POST", "players", {"count": 12, "join_queue": True})
    assert status == 200
    assert body["match_id"] == Match.objects.get().pk


def test_new_players_are_simulator_users_when_there_is_one(
    http: Client, league: Community, sim: FakeSim
) -> None:
    status, body = call(http, "POST", "players", {"count": 2, "dm_open": False})
    assert status == 200
    assert sim.calls[0] == (
        "POST",
        "/_sim/users",
        {"count": 2, "dm_open": False, "name_prefix": "Dev"},
    )
    [first, second] = body["players"]
    assert first["sim_user"] and first["dm_open"] is False
    assert first["discord_user_id"] == "1100000000000010001"
    assert first["name"] == "Dev0"

    status, body = call(
        http, "PATCH", f"players/{first['id']}", {"name": "Renamed", "dm_open": True}
    )
    assert status == 200
    assert body["name"] == "Renamed" and body["dm_open"] is True
    assert sim.calls[-1] == (
        "PATCH",
        f"/_sim/users/{first['discord_user_id']}",
        {"name": "Renamed", "dm_open": True},
    )

    status, body = call(http, "DELETE", f"players/{second['id']}")
    assert (status, body) == (200, {"deleted": "hard"})
    assert sim.calls[-1][:2] == ("DELETE", f"/_sim/users/{second['discord_user_id']}")


def test_a_rating_change_reseeds_through_the_ledger(http: Client, league: Community) -> None:
    _, body = call(http, "POST", "players", {"count": 1, "rating": 1500})
    player = body["players"][0]
    status, body = call(http, "PATCH", f"players/{player['id']}", {"rating": 640})
    assert status == 200
    assert body["rating"] == 640
    assert body["sigma"] == "8.333333"
    assert PlayerRating.objects.get(player_id=player["id"]).rating == 640
    ledger_ok()


def test_a_player_without_history_is_deleted_and_one_with_it_retired(
    http: Client, league: Community
) -> None:
    _, body = call(http, "POST", "players", {"count": 2})
    plain, rated = (p["id"] for p in body["players"])
    call(http, "PATCH", f"players/{rated}", {"rating": 900})

    assert call(http, "DELETE", f"players/{plain}") == (200, {"deleted": "hard"})
    assert not Player.objects.filter(pk=plain).exists()
    assert call(http, "DELETE", f"players/{rated}") == (200, {"deleted": "retired"})
    assert DevProfile.objects.get(player_id=rated).retired

    _, listed = call(http, "GET", "players")
    assert [p["id"] for p in listed["players"]] == []
    _, everyone = call(http, "GET", "players?all=1")
    assert [p["id"] for p in everyone["players"]] == [rated]


def test_a_player_in_a_live_match_cant_be_deleted(http: Client, popped: Match) -> None:
    player = popped.participants.order_by("pk")[0].player
    status, body = call(http, "DELETE", f"players/{player.pk}")
    assert status == 409
    assert body["error"]["code"] == "invalid_action"
    assert f"match #{popped.pk}" in body["error"]["message"]


def test_picks_are_stored_by_champion_and_shown_as_slugs(
    http: Client, league: Community, players: list[Player]
) -> None:
    status, body = call(
        http,
        "PUT",
        f"players/{players[0].pk}/picks",
        {"prefer": ["haze", "Wraith", 1], "ban": ["seven"]},
    )
    assert status == 200
    assert body["picks"] == {"prefer": ["haze", "wraith", "infernus"], "ban": ["seven"]}
    status, body = call(http, "PUT", f"players/{players[0].pk}/picks", {"prefer": ["nobody"]})
    assert status == 400
    assert "nobody" in body["error"]["message"]


def test_queue_join_by_count_and_by_id_then_leave(
    http: Client, league: Community, players: list[Player]
) -> None:
    status, body = call(http, "POST", "queue/join", {"count": 3})
    assert status == 200
    assert [entry["player"]["id"] for entry in body["queue"]] == [p.pk for p in players[:3]]
    status, body = call(http, "POST", "queue/join", {"player_ids": [players[5].pk]})
    assert [entry["position"] for entry in body["queue"]] == [1, 2, 3, 4]
    status, body = call(http, "POST", "queue/leave", {"player_ids": [players[0].pk]})
    assert status == 200
    assert [entry["player"]["id"] for entry in body["queue"]] == [
        players[1].pk,
        players[2].pk,
        players[5].pk,
    ]
    status, body = call(http, "POST", "queue/join", {"count": 50})
    assert status == 409
    status, body = call(http, "POST", "queue/join", {"player_ids": [players[1].pk]})
    assert status == 409


def test_fill_tops_the_queue_up_and_pops(
    http: Client, league: Community, players: list[Player]
) -> None:
    for player in players[:5]:
        queue.join(league.pk, player)
    status, body = call(http, "POST", "queue/fill", {"rating": 1000})
    assert status == 200
    assert len(body["players"]) == 7
    assert all(p["rating"] == 1000 for p in body["players"])
    assert body["match_id"] == Match.objects.get().pk
    assert body["queue"] == []
    assert not QueueEntry.objects.exists()


def test_a_match_script_is_checked_and_stored(http: Client, popped: Match) -> None:
    script = {
        "draft": [3, 4],
        "champions": [{"step": 0, "slug": "haze"}, {"step": 1, "team": "B", "slug": "Abrams"}],
        "captain_votes": {"*": [1, 2]},
        "coinflip": "archmother",
        "lobby_code": "DEV-1",
        "winner": "B",
    }
    status, body = call(http, "PUT", f"matches/{popped.pk}/script", script)
    assert status == 200
    assert body["script"]["champions"] == [
        {"step": 0, "team": None, "champion": 13},
        {"step": 1, "team": "B", "champion": 6},
    ]
    assert body["script"]["winner"] == "B"
    for bad in ({"nope": 1}, {"coinflip": "heads"}, {"winner": "C"}, {"draft": ["x"]}):
        status, body = call(http, "PUT", f"matches/{popped.pk}/script", bad)
        assert status == 400, bad


def test_matches_by_id_and_latest(http: Client, popped: Match) -> None:
    assert call(http, "GET", f"matches/{popped.pk}")[1]["id"] == popped.pk
    assert call(http, "GET", "matches/latest")[1]["id"] == popped.pk
    status, body = call(http, "GET", "matches/999999")
    assert (status, body["error"]["code"]) == (404, "not_found")


def test_errors_are_json_with_a_status_and_code(http: Client, popped: Match) -> None:
    response = http.post(BASE + "players", data="{nope", content_type="application/json")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "bad_request"
    assert call(http, "GET", "nowhere")[0] == 404
    status, body = call(http, "DELETE", "state")
    assert status == 400
    assert "takes GET" in body["error"]["message"]
    assert call(http, "POST", "players", {"count": 0})[0] == 400
    assert call(http, "POST", "players", {"count": "many"})[0] == 400

    player = popped.participants.order_by("pk")[0].player
    assert (
        call(http, "POST", "matches/latest/act", {"action": "ready", "player_id": player.pk})[0]
        == 200
    )
    status, body = call(
        http, "POST", "matches/latest/act", {"action": "ready", "player_id": player.pk}
    )
    assert (status, body["error"]["code"]) == (409, "invalid_action")


def test_a_foreign_page_cant_change_dev_state(http: Client, league: Community) -> None:
    """The API skips CSRF, and a text/plain POST needs no preflight: the Origin stops it."""
    before = Player.objects.count()
    for origin in ("http://evil.test", "null"):
        response = http.post(
            BASE + "players",
            data='{"count": 1}',
            content_type="text/plain",
            headers={"Origin": origin},
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "cross_origin"
    assert Player.objects.count() == before
    # Reads stay open; the panel (any loopback port), the host itself and Origin-less clients
    # such as curl or the e2e suite get through.
    assert http.get(BASE + "state", headers={"Origin": "http://evil.test"}).status_code == 200
    for allowed in ("http://127.0.0.1:18091", "http://localhost:5174", "http://testserver", None):
        headers = {"Origin": allowed} if allowed else {}
        response = http.post(
            BASE + "players",
            data='{"count": 1}',
            content_type="application/json",
            headers=headers,
        )
        assert response.status_code == 200, (allowed, response.json())


def test_a_league_refusal_of_who_acts_is_403(http: Client, popped: Match) -> None:
    from league.services.common import active_participants

    for participant in active_participants(popped):
        call(
            http,
            "POST",
            "matches/latest/act",
            {"action": "ready", "player_id": participant.player_id},
        )
    call(http, "POST", "matches/latest/advance", {"until": "player_draft", "via": "service"})
    match = Match.objects.get()
    acting = call(http, "GET", "matches/latest")[1]["turn"]["player_ids"][0]
    other = match.participants.filter(is_captain=True).exclude(player_id=acting).get()
    status, body = call(
        http, "POST", "matches/latest/act", {"action": "pick", "player_id": other.player_id}
    )
    assert status == 403
    assert body["error"]["code"] == "not_allowed"
