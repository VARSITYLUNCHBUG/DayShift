"""The /_sim control API without a bot attached."""

from __future__ import annotations

import asyncio
import json

from discord_sim import snowflake
from discord_sim.eventlog import EventLog
from discord_sim.heroes import HEROES
from discord_sim.message_body import MessageBody

from .support import RunningSim


async def test_health_and_state(running: RunningSim) -> None:
    health = await running.call("GET", "/_sim/health")
    assert health["ok"] is True and health["bot_connected"] is False
    state = await running.call("GET", "/_sim/state")
    assert state["guild"]["id"] == str(snowflake.GUILD_ID)
    assert state["seed"]["staff_role_id"] == str(snowflake.STAFF_ROLE_ID)
    owner = next(m for m in state["members"] if m["is_owner"])
    assert owner["id"] == str(snowflake.OWNER_USER_ID)


async def test_users_create_edit_delete(running: RunningSim) -> None:
    created = await running.call(
        "POST",
        "/_sim/users",
        {"count": 2, "name_prefix": "sub", "dm_open": False, "roles": ["Staff"]},
        status=201,
    )
    first, second = created["users"]
    assert first["name"] == "sub1" and first["dm_open"] is False
    assert first["roles"] == [str(snowflake.STAFF_ROLE_ID)]
    edited = await running.call("PATCH", f"/_sim/users/{first['id']}", {"dm_open": True})
    assert edited["dm_open"] is True
    await running.call("DELETE", f"/_sim/users/{second['id']}")
    await running.call("PATCH", f"/_sim/users/{second['id']}", {}, status=404)


async def test_voice_needs_a_voice_channel(running: RunningSim) -> None:
    user = (await running.call("POST", "/_sim/users", {}, status=201))["users"][0]
    await running.call(
        "POST", "/_sim/voice", {"user_id": user["id"], "channel_id": "general"}, status=400
    )
    moved = await running.call(
        "POST", "/_sim/voice", {"user_id": user["id"], "channel_id": "General"}
    )
    assert moved["channel_id"] == str(snowflake.GENERAL_VOICE_ID)


async def test_chat_respects_channel_permissions(running: RunningSim) -> None:
    user = (await running.call("POST", "/_sim/users", {}, status=201))["users"][0]
    state = running.sim.state
    hidden = state.create_channel(
        {
            "name": "staff",
            "permission_overwrites": [{"id": state.guild.id, "type": 0, "deny": 1 << 10}],
        }
    )
    body = {"user_id": user["id"], "channel_id": str(hidden.id), "content": "hi"}
    await running.call("POST", "/_sim/messages", body, status=403)
    posted = await running.call("POST", "/_sim/messages", body | {"force": True}, status=201)
    listed = await running.call("GET", f"/_sim/channels/{hidden.id}/messages")
    assert [m["id"] for m in listed["messages"]] == [posted["id"]]


async def test_click_without_a_match_lists_labels(running: RunningSim) -> None:
    user = (await running.call("POST", "/_sim/users", {}, status=201))["users"][0]
    state = running.sim.state
    row = {"type": 2, "style": 1, "label": "Join queue", "custom_id": "join"}
    state.post_message(
        snowflake.GENERAL_TEXT_ID,
        state.bot_user.id,
        MessageBody.parse({"components": [{"type": 1, "components": [row]}]}),
    )
    body = {"user_id": user["id"], "channel_id": "general", "label": "leave"}
    missing = await running.call("POST", "/_sim/interactions/click", body, status=404)
    assert missing["available"][0]["labels"] == ["Join queue"]
    # A matching label with no bot on the gateway is unavailable (503), not a hang, and not the
    # 409 of a disabled component, which a client retries as "the bot moved on".
    offline = await running.call(
        "POST", "/_sim/interactions/click", body | {"label": "JOIN QUEUE"}, status=503
    )
    assert offline == {"error": "No bot is connected to the gateway.", "reason": "no_bot"}


async def test_cors_for_the_control_panel(running: RunningSim) -> None:
    origin = {"Origin": "http://localhost:18091"}
    async with running.http.options(
        running.url + "/_sim/users",
        headers=origin | {"Access-Control-Request-Method": "POST"},
    ) as response:
        assert response.status == 204
        assert response.headers["Access-Control-Allow-Origin"] == origin["Origin"]
    async with running.http.get(running.url + "/_sim/health", headers=origin) as response:
        assert response.headers["Access-Control-Allow-Origin"] == origin["Origin"]
    async with running.http.get(
        running.url + "/_sim/health", headers={"Origin": "http://evil.test"}
    ) as response:
        assert "Access-Control-Allow-Origin" not in response.headers


async def test_a_foreign_page_cant_change_the_sim(running: RunningSim) -> None:
    """A text/plain or multipart POST needs no preflight, so the Origin is what stops it."""
    before = len((await running.call("GET", "/_sim/users"))["users"])
    for origin in ("http://evil.test", "null"):
        async with running.http.post(
            running.url + "/_sim/users",
            data='{"count": 1}',
            headers={"Origin": origin, "Content-Type": "text/plain"},
        ) as response:
            assert response.status == 403
            assert (await response.json())["reason"] == "origin"
    assert len((await running.call("GET", "/_sim/users"))["users"]) == before
    # Reads stay open (CORS decides who may see them), and so do the panel, loopback pages on
    # any port, the host being called, and clients with no Origin at all.
    async with running.http.get(
        running.url + "/_sim/health", headers={"Origin": "http://evil.test"}
    ) as response:
        assert response.status == 200
    for allowed in ("http://localhost:18091", "http://127.0.0.1:46291", "http://[::1]:5174", None):
        headers = {"Origin": allowed} if allowed else {}
        async with running.http.post(
            running.url + "/_sim/users", json={"count": 1}, headers=headers
        ) as response:
            assert response.status == 201, allowed


async def test_log_and_event_stream(running: RunningSim) -> None:
    async with running.http.get(running.url + "/_sim/events?since=0") as stream:
        assert stream.headers["Content-Type"] == "text/event-stream"
        await running.call("POST", "/_sim/users", {"count": 1}, status=201)
        async with asyncio.timeout(5):
            while True:
                line = (await stream.content.readline()).decode()
                if line.startswith("data: "):
                    entry = json.loads(line[6:])
                    if entry["kind"] == "control":
                        break
    assert entry["path"] == "/_sim/users"
    log = await running.call("GET", "/_sim/log?kind=control")
    assert log["entries"][-1]["path"] == "/_sim/users"


async def test_a_stream_that_falls_behind_or_outlives_the_sim_is_ended() -> None:
    log = EventLog(size=10)
    lagging, idle = log.subscribe(), log.subscribe()
    for _ in range(lagging.maxsize):
        log.add("rest")
    while not idle.empty():
        idle.get_nowait()
    log.add("rest")
    assert lagging.get_nowait() is None  # Its backlog is dropped; the replay refills it.
    assert idle.get_nowait() is not None
    log.close()
    assert idle.get_nowait() is None


async def test_reset_returns_the_seed(running: RunningSim) -> None:
    await running.call("POST", "/_sim/users", {"count": 3}, status=201)
    state = await running.call("POST", "/_sim/reset")
    assert len(state["members"]) == 2  # The owner and the bot.


async def test_an_admin_made_channel(running: RunningSim) -> None:
    category = await running.call(
        "POST", "/_sim/channels", {"name": "Deadlock", "type": 4}, status=201
    )
    hidden = [{"id": str(snowflake.GUILD_ID), "type": 0, "deny": str(1 << 10)}]
    text = await running.call(
        "POST",
        "/_sim/channels",
        {"name": "Staff Alerts", "parent_id": "Deadlock", "permission_overwrites": hidden},
        status=201,
    )
    assert text["name"] == "staff-alerts" and text["parent_id"] == category["id"]
    assert text["overwrites"][0]["deny"] == str(1 << 10)
    await running.call("POST", "/_sim/channels", {"name": ""}, status=400)


async def test_the_deadlock_api_stand_in(running: RunningSim) -> None:
    base = running.url + "/deadlock-api/v1/matches/custom"
    async with running.http.post(f"{base}/create", json={"server_region": "europe"}) as made:
        assert made.status == 200
        lobby = await made.json()
    assert len(lobby["party_code"]) == 6
    async with running.http.post(f"{base}/{lobby['party_id']}/start") as started:
        assert started.status == 200
    async with running.http.get(f"{base}/{lobby['party_id']}/match-id") as match_id:
        assert match_id.status == 404
    state = await running.call("GET", "/_sim/deadlock-api")
    assert state["lobbies"] == [
        {
            "party_id": lobby["party_id"],
            "party_code": lobby["party_code"],
            "region": "europe",
            "started": True,
        }
    ]

    await running.call("PUT", "/_sim/deadlock-api", {"lobby": "fail"})
    async with running.http.post(f"{base}/create", json={}) as refused:
        assert refused.status == 503
    await running.call("PUT", "/_sim/deadlock-api", {"lobby": "maybe"}, status=400)
    await running.call("POST", "/_sim/reset")
    state = await running.call("GET", "/_sim/deadlock-api")
    assert (state["lobby"], state["lobbies"], state["steam_names"]) == ("create", [], {})
    assert [(h["id"], h["name"]) for h in state["heroes"]] == list(HEROES)


async def test_the_hero_roster_as_the_champion_sync_reads_it(running: RunningSim) -> None:
    url = running.url + "/deadlock-api/v1/assets/heroes"
    async with running.http.get(url, params={"only_active": "true"}) as answer:
        assert answer.status == 200
        roster = await answer.json()
    assert [(hero["id"], hero["name"]) for hero in roster] == list(HEROES)
    haze = next(hero for hero in roster if hero["name"] == "Haze")
    assert haze == {
        "id": 13,
        "class_name": "hero_haze",
        "name": "Haze",
        "player_selectable": True,
        "disabled": False,
        "in_development": False,
        "images": {},
    }

    # A new hero, a rename and one nobody can pick any more, for the admin's sync to find.
    heroes = [
        {"id": 1, "name": "Infernus"},
        {"id": 2, "name": "Seven Again"},
        {"id": 3, "name": "Vindicta", "player_selectable": False},
        {"id": 99, "name": "Newcomer"},
    ]
    await running.call("PUT", "/_sim/deadlock-api", {"heroes": heroes})
    async with running.http.get(url, params={"only_active": "true"}) as answer:
        active = [(hero["id"], hero["name"]) for hero in await answer.json()]
    assert active == [(1, "Infernus"), (2, "Seven Again"), (99, "Newcomer")]
    async with running.http.get(url) as answer:
        assert len(await answer.json()) == 4

    for bad in ([], [{"id": 1}], [{"id": 1, "name": "A"}, {"id": 1, "name": "B"}], [{"id": "x"}]):
        await running.call("PUT", "/_sim/deadlock-api", {"heroes": bad}, status=400)
    await running.call("PUT", "/_sim/deadlock-api", {"lobby": "fail", "heroes": []}, status=400)
    state = await running.call("GET", "/_sim/deadlock-api")
    assert state["lobby"] == "create"  # A bad request changes nothing.
    assert len(state["heroes"]) == 4
    await running.call("PUT", "/_sim/deadlock-api", {"roster": []}, status=400)


async def test_steam_names_as_link_reads_them(running: RunningSim) -> None:
    url = running.url + "/deadlock-api/v1/players/steam"
    async with running.http.get(url, params={"account_ids": "22,11,22"}) as answer:
        assert answer.status == 200
        rows = await answer.json()
    assert [(row["account_id"], row["personaname"]) for row in rows] == [
        (22, "steam_22"),
        (11, "steam_11"),
    ]
    assert rows[0]["profileurl"] == "https://steamcommunity.com/profiles/76561197960265750/"

    await running.call("PUT", "/_sim/deadlock-api", {"steam_names": {"11": "Ash", "22": None}})
    async with running.http.get(url, params={"account_ids": "11,22"}) as answer:
        assert [(r["account_id"], r["personaname"]) for r in await answer.json()] == [(11, "Ash")]
    for bad in ("", "abc", "0", str(2**32)):
        async with running.http.get(url, params={"account_ids": bad}) as answer:
            assert answer.status == 400
    for names in ({"x": "A"}, {"5": ""}, ["5"]):
        await running.call("PUT", "/_sim/deadlock-api", {"steam_names": names}, status=400)
