"""The players' websocket, end to end: real sessions, real NOTIFYs, the real ASGI app."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any

import pytest
from django.contrib.sessions.backends.db import SessionStore
from django.db import connection
from django.db.models import F

from league.asyncdb import db
from league.models import Community, Match, Player
from league.services import community, live, lobby, queue
from league.web.auth.session import SESSION_KEY
from league.web.live import consumer, hub, schema
from tests.conftest import make_player
from tests.helpers import to_in_progress
from tests.web_helpers import (
    WAIT,
    Msg,
    close_code,
    listening,
    run,
    serve,
    session_for,
    signed_in,
    snap,
    socket,
    subscribe,
    until,
)

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def web(league: Community, settings: Any) -> Iterator[Community]:
    yield from serve(league, settings)


# --- Signing in -------------------------------------------------------------------------------


def test_no_session_is_closed_with_4401() -> None:
    async def test() -> None:
        ws = await socket()
        connected, _ = await ws.connect(timeout=WAIT)
        assert connected  # Accepted, so the browser sees why.
        assert await close_code(ws) == 4401

        stale = await socket("no-such-session")
        await stale.connect(timeout=WAIT)
        assert await close_code(stale) == 4401

    run(test)


def test_no_web_server_set_up_is_1011(players: list[Player], settings: Any) -> None:
    settings.WEB_GUILD_ID = 1  # No such server.

    async def test() -> None:
        ws = await socket(await db(session_for, players[0]))
        await ws.connect(timeout=WAIT)
        assert await close_code(ws) == 1011

    run(test)


def test_a_foreign_origin_is_refused(players: list[Player]) -> None:
    async def test() -> None:
        ws = await socket(await db(session_for, players[0]), origin="https://evil.example")
        connected, _ = await ws.connect(timeout=WAIT)
        assert not connected

    run(test)


def test_signing_out_closes_the_players_sockets(players: list[Player]) -> None:
    async def test() -> None:
        key = await db(session_for, players[0])
        ws = await socket(key)
        await ws.connect(timeout=WAIT)
        await until(ws, lambda m: m["t"] == "hello")
        await subscribe(ws, "me")
        other = await signed_in(players[1])
        await subscribe(other, "me")
        await listening()

        def sign_out() -> None:
            """What signing out does (`league.web.auth.session.sign_out`): the session no longer
            names the player, and the player's topic is published."""
            store = SessionStore(key)
            del store[SESSION_KEY]
            store.save()
            live.publish(live.player_topic(players[0].pk))

        await db(sign_out)
        assert await close_code(ws) == 4401
        # Someone else's sign-out leaves this one open.
        await other.send_json_to({"t": "ping"})
        assert (await until(other, lambda m: m["t"] == "pong"))["t"] == "pong"

    run(test)


def test_a_player_made_inactive_is_signed_out(players: list[Player]) -> None:
    async def test() -> None:
        ws = await signed_in(players[0])
        await subscribe(ws, "me")
        await listening()

        def deactivate() -> None:
            Player.objects.filter(pk=players[0].pk).update(is_active=False)
            live.publish(live.player_topic(players[0].pk))

        await db(deactivate)
        assert await close_code(ws) == 4401
        # And can't come back on the same session.
        again = await socket(await db(session_for, players[0]))
        await again.connect(timeout=WAIT)
        assert await close_code(again) == 4401

    run(test)


def test_a_deleted_player_is_closed_with_4403() -> None:
    async def test() -> None:
        player = await db(make_player, 77)
        ws = await signed_in(player)
        await subscribe(ws, "me")
        await listening()

        def delete() -> None:
            Player.objects.filter(pk=player.pk).delete()
            live.publish(live.player_topic(player.pk))

        await db(delete)
        assert await close_code(ws) == 4403

    run(test)


# --- Subscribing ------------------------------------------------------------------------------


def test_subscribe_sends_hello_then_a_snapshot_per_topic(
    popped: Match, players: list[Player]
) -> None:
    async def test() -> None:
        ws = await socket(await db(session_for, players[0]))
        await ws.connect(timeout=WAIT)
        hello = await ws.receive_json_from(timeout=WAIT)
        assert hello["t"] == "hello" and hello["player_id"] == str(players[0].pk)
        assert hello["server_time"].endswith("Z")

        topic = f"match:{popped.pk}"
        got = await subscribe(ws, "me", "queue", "live", topic)
        for message in got.values():
            schema.ServerMessage.model_validate(message)  # Every snap is on the protocol.
        assert got["me"]["data"]["match"]["id"] == str(popped.pk)
        assert got["queue"]["data"]["count"] == 0
        assert [m["id"] for m in got["live"]["data"]["matches"]] == [str(popped.pk)]
        assert got[topic]["rev"] == popped.version
        assert got[topic]["data"]["viewer"]["is_player"] is True

    run(test)


def test_a_missing_or_foreign_match_is_gone(league: Community, players: list[Player]) -> None:
    other = community.ensure(guild_id=4242, name="Elsewhere")
    for player in players:
        queue.join(other.pk, player)
    foreign = Match.objects.get(community=other)

    async def test() -> None:
        ws = await signed_in(await db(make_player, 60))
        got = await subscribe(
            ws, f"match:{foreign.pk}", "match:987654", "match:9999999999999999999"
        )
        for topic, message in got.items():
            assert message == {"t": "gone", "topic": topic, "reason": "not_found"}

    run(test)


def test_a_change_pushes_a_fresh_snapshot(popped: Match, players: list[Player]) -> None:
    waiting = make_player(30)

    async def test() -> None:
        ws = await signed_in(waiting)
        topic = f"match:{popped.pk}"
        got = await subscribe(ws, "me", "queue", "live", topic)
        assert got["me"]["data"]["queue"]["in_queue"] is False
        await ws.send_json_to({"t": "unsub", "topics": ["live"]})
        await listening()

        await db(queue.join, popped.community_id, waiting)
        await until(ws, snap("queue", lambda q: q["count"] == 1))
        await until(ws, snap("me", lambda me: me["queue"]["in_queue"] is True))

        await db(lobby.mark_ready, popped.pk, players[0])
        seen: list[Msg] = []

        def ready(message: Msg) -> bool:
            seen.append(message)
            return snap(topic, lambda m: any(p["is_ready"] for p in m["players"]))(message)

        updated = await until(ws, ready)
        assert updated["rev"] > got[topic]["rev"]
        assert not any(m.get("topic") == "live" for m in seen)  # Unsubscribed.

    run(test)


def test_spectators_get_no_lobby_code(league: Community, players: list[Player]) -> None:
    for player in players:
        queue.join(league.pk, player)
    match = to_in_progress(Match.objects.get())
    outsider = make_player(50)

    async def test() -> None:
        topic = f"match:{match.pk}"
        playing = await signed_in(players[0])
        watching = await signed_in(outsider)
        mine = (await subscribe(playing, topic))[topic]["data"]
        theirs = (await subscribe(watching, topic))[topic]["data"]
        assert mine["lobby_code"] == "ABC123" and mine["viewer"]["is_player"] is True
        assert theirs["lobby_code"] is None and theirs["viewer"]["is_player"] is False

    run(test)


def test_me_never_carries_another_players_place(league: Community) -> None:
    waiting = [make_player(n) for n in range(1, 6)]
    for player in waiting:
        queue.join(league.pk, player)
    queue.leave(league.pk, waiting[1])  # Their place is held.
    me = waiting[2]

    async def test() -> None:
        ws = await signed_in(me)
        first = (await subscribe(ws, "me"))["me"]
        await listening()
        await db(queue.leave, league.pk, waiting[3])  # Places shift: a fresh `me`.
        second = await until(ws, snap("me", lambda data: data["queue"]["position"] == 2))
        for message in (first, second):
            place = message["data"]["queue"]["place"]
            assert place is not None and place["total"] >= 3
            text = str(message)
            for other in waiting:
                if other != me:
                    assert other.display_name not in text
                    assert str(other.discord_user_id) not in text
                    assert f"'{other.pk}'" not in text

    run(test)


def test_match_revs_never_go_backwards(popped: Match, players: list[Player]) -> None:
    async def test() -> None:
        topic = f"match:{popped.pk}"
        ws = await signed_in(players[0])
        revs = [(await subscribe(ws, topic))[topic]["rev"]]
        await listening()
        for player in players[:6]:
            await db(lobby.mark_ready, popped.pk, player)
        last = await until(ws, snap(topic, lambda m: sum(p["is_ready"] for p in m["players"]) == 6))
        revs.append(last["rev"])
        while not await ws.receive_nothing(timeout=0.2):
            message = await ws.receive_json_from(timeout=WAIT)
            if message.get("topic") == topic:
                revs.append(message["rev"])
        assert revs == sorted(revs) and revs[-1] > revs[0]

    run(test)


def test_too_many_topics_is_4409(league: Community, popped: Match) -> None:
    async def test() -> None:
        ws = await signed_in(await db(make_player, 61))
        await subscribe(ws, "me", "queue", "live")
        topics = [f"match:{n}" for n in range(1, 9)]
        await ws.send_json_to({"t": "sub", "topics": topics})
        assert await close_code(ws) == 4409

    run(test)


def test_ping_unknown_messages_and_actions(league: Community) -> None:
    async def test() -> None:
        ws = await signed_in(await db(make_player, 62))
        await ws.send_to(text_data="not json")
        await ws.send_to(bytes_data=b"\x00")
        await ws.send_json_to({"t": "sub", "topics": ["match:abc"]})
        await ws.send_json_to({"t": "nope"})
        await ws.send_json_to({"t": "ping"})
        pong = await ws.receive_json_from(timeout=WAIT)  # Nothing before it: the rest was ignored.
        assert pong["t"] == "pong" and pong["server_time"].endswith("Z")
        await ws.send_json_to({"t": "act", "id": "c-1", "name": "no.such", "args": {}})
        ack = await ws.receive_json_from(timeout=WAIT)
        assert ack == {
            "t": "ack",
            "id": "c-1",
            "ok": False,
            "error": "That didn't work. Refresh and try again.",
            "result": None,
        }

    run(test)


def test_no_ping_closes_with_4408(league: Community, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(consumer.LiveConsumer, "PING_TIMEOUT", 0.3)

    async def test() -> None:
        ws = await signed_in(await db(make_player, 63))
        await asyncio.sleep(0.2)
        await ws.send_json_to({"t": "ping"})
        await until(ws, lambda m: m["t"] == "pong")
        assert await close_code(ws) == 4408

    run(test)


# --- Missed notifications ---------------------------------------------------------------------


def test_the_listener_reconnects_and_resyncs(popped: Match, players: list[Player]) -> None:
    async def test() -> None:
        topic = f"match:{popped.pk}"
        ws = await signed_in(players[0])
        await subscribe(ws, topic)
        pid = await listening()

        def kill() -> None:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_terminate_backend(%s)", [pid])

        await db(kill)
        # Made while the listener is down or reconnecting: heard, or caught by the resync.
        await db(lobby.mark_ready, popped.pk, players[0])
        await until(ws, snap(topic, lambda m: any(p["is_ready"] for p in m["players"])))
        assert await listening() != pid

    run(test)


def test_the_safety_poll_catches_a_silent_change(
    popped: Match, players: list[Player], monkeypatch: pytest.MonkeyPatch
) -> None:
    # The test runs one poll pass itself, so a slow machine can't race a timer against it.
    monkeypatch.setattr(hub, "MATCH_POLL", 3600.0)

    async def test() -> None:
        topic = f"match:{popped.pk}"
        ws = await signed_in(players[0])
        await listening()  # The listener's resync on connect is behind us.
        before = (await subscribe(ws, topic))[topic]["rev"]
        # A version bump nobody published.
        await db(lambda: Match.objects.filter(pk=popped.pk).update(version=F("version") + 1))
        await hub.get()._poll_matches()
        # A resync can repeat the old snapshot; the poll's is the newer one.
        after = await until(ws, lambda m: snap(topic)(m) and m["rev"] > before)
        assert after["rev"] == before + 1

    run(test)


# --- The mailbox ------------------------------------------------------------------------------


def test_a_slow_socket_gets_only_the_newest_snapshot() -> None:
    async def test() -> None:
        sent: list[Msg] = []
        gate = asyncio.Event()

        async def send(message: Msg) -> None:
            await gate.wait()
            sent.append(message)

        async def close(code: int) -> None:
            pass

        conn = hub.Conn(1, 1, None, send, close)
        conn.offer("queue", 1, {"n": 1})  # Picked up by the writer, which then waits on the gate.
        await asyncio.sleep(0)
        for rev in (2, 3, 4):
            conn.offer("queue", rev, {"n": rev})
        conn.offer("match:5", 9, {"n": "m9"})
        conn.offer("match:5", 7, {"n": "m7"})  # Older than what's queued: dropped.
        assert conn.pending() == [{"n": 4}, {"n": "m9"}]
        gate.set()
        for _ in range(5):
            await asyncio.sleep(0)
        assert sent == [{"n": 1}, {"n": 4}, {"n": "m9"}]
        conn.detach()

    asyncio.run(test())
