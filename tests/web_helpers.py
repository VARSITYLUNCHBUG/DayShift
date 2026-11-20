"""Helpers for the websocket tests: real sessions, the real ASGI app, one event loop per test.

A communicator's `receive_output` timing out cancels the app, so wait with `until` or
`close_code`, and use `receive_nothing` to check that nothing arrives.

The communicators are Channels' own (`channels.testing`), less its live-server import, which
needs Daphne: the web process runs on uvicorn, so Daphne isn't installed.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Iterator
from contextlib import suppress
from typing import Any
from unittest import mock

from asgiref.testing import ApplicationCommunicator
from django.conf import settings
from django.contrib.sessions.backends.db import SessionStore
from django.db import connections

import config.asgi
from league.asyncdb import db
from league.models import Community, Match, Player, ScoreboardRead
from league.services import ocr
from league.web.auth.session import SESSION_KEY
from league.web.live import dbpool, hub, listener
from tests.helpers import fresh

type Msg = dict[str, Any]


def _no_op() -> None:
    pass


class Communicator(ApplicationCommunicator):
    """`channels.testing.ApplicationCommunicator`: Channels' own database helpers mustn't close
    the test's connection."""

    async def send_input(self, message: Msg) -> None:
        with mock.patch("channels.db.close_old_connections", _no_op):
            await super().send_input(message)

    async def receive_output(self, timeout: float = 1) -> Msg:
        with mock.patch("channels.db.close_old_connections", _no_op):
            output: Msg = await super().receive_output(timeout)
            return output


class WebsocketCommunicator(Communicator):
    """`channels.testing.WebsocketCommunicator`, for one websocket on the app."""

    def __init__(self, application: Any, path: str, headers: list[tuple[bytes, bytes]]) -> None:
        scope = {
            "type": "websocket",
            "path": path,
            "query_string": b"",
            "headers": headers,
            "subprotocols": [],
        }
        super().__init__(application, scope)

    async def connect(self, timeout: float = 1) -> tuple[bool, Any]:
        await self.send_input({"type": "websocket.connect"})
        response = await self.receive_output(timeout)
        if response["type"] == "websocket.close":
            return False, response.get("code", 1000)
        assert response["type"] == "websocket.accept"
        return True, response.get("subprotocol")

    async def send_to(self, text_data: str | None = None, bytes_data: bytes | None = None) -> None:
        if text_data is not None:
            await self.send_input({"type": "websocket.receive", "text": text_data})
        else:
            await self.send_input({"type": "websocket.receive", "bytes": bytes_data})

    async def send_json_to(self, data: Any) -> None:
        await self.send_to(text_data=json.dumps(data))

    async def receive_json_from(self, timeout: float = 1) -> Any:
        response = await self.receive_output(timeout)
        assert response["type"] == "websocket.send", response
        return json.loads(response["text"])

    async def disconnect(self, code: int = 1000, timeout: float = 1) -> None:
        await self.send_input({"type": "websocket.disconnect", "code": code})
        await self.wait(timeout)


async def http_get(application: Any, path: str) -> Msg:
    """One GET through the ASGI app: its status, headers and whole body."""
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", _HOST.encode())],
        "server": (_HOST, 80),
        "client": ("127.0.0.1", 50000),
    }
    communicator = Communicator(application, scope)
    await communicator.send_input({"type": "http.request", "body": b"", "more_body": False})
    start = await communicator.receive_output(10)
    body = b""
    while True:
        part = await communicator.receive_output(10)
        body += part.get("body", b"")
        if not part.get("more_body"):
            break
    await communicator.wait(10)
    return {"status": start["status"], "headers": start.get("headers", []), "body": body}


_HOST = next((host for host in settings.ALLOWED_HOSTS if host != "*"), "localhost").lstrip(".")
ORIGIN = f"http://{_HOST}:8000"
WAIT = 3.0  # Seconds: a generous ceiling; each step normally takes milliseconds.


def serve(league: Community, django_settings: Any) -> Iterator[Community]:
    """The body of each websocket test module's autouse fixture: the web serves the test
    league, and each test starts with a new hub and database pool."""
    django_settings.WEB_GUILD_ID = league.discord_guild_id
    yield league
    # Each test runs its own event loop: start the next with a new hub and listener.
    hub.reset()
    dbpool.shutdown()


def run(test: Callable[[], Awaitable[None]]) -> None:
    async def go() -> None:
        try:
            await test()
        finally:
            for ws in list(_open):
                # A timed-out receive has already cancelled the app.
                with suppress(Exception, asyncio.CancelledError):
                    await ws.disconnect()
            _open.clear()
            await hub.stop()
            await db(connections.close_all)

    asyncio.run(go())


_open: list[WebsocketCommunicator] = []


def session_for(player: Player) -> str:
    store = SessionStore()
    store[SESSION_KEY] = player.pk
    store.save()
    assert store.session_key is not None
    return store.session_key


async def socket(session_key: str | None = None, *, origin: str = ORIGIN) -> WebsocketCommunicator:
    headers = [(b"host", _HOST.encode()), (b"origin", origin.encode())]
    if session_key is not None:
        headers.append((b"cookie", f"{settings.SESSION_COOKIE_NAME}={session_key}".encode()))
    ws = WebsocketCommunicator(config.asgi.application, "/ws/", headers=headers)
    _open.append(ws)
    return ws


async def signed_in(player: Player) -> WebsocketCommunicator:
    """A socket for this player, past `hello`."""
    ws = await socket(await db(session_for, player))
    connected, _ = await ws.connect(timeout=WAIT)
    assert connected
    hello = await ws.receive_json_from(timeout=WAIT)
    assert hello["t"] == "hello" and hello["player_id"] == str(player.pk)
    return ws


async def until(ws: WebsocketCommunicator, want: Callable[[Msg], bool]) -> Msg:
    """The first message that matches, skipping others (duplicates after a resync, say)."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + WAIT
    while True:
        message: Msg = await ws.receive_json_from(timeout=max(deadline - loop.time(), 0.01))
        if want(message):
            return message


def snap(topic: str, check: Callable[[Msg], bool] = lambda data: True) -> Callable[[Msg], bool]:
    return lambda m: m["t"] == "snap" and m["topic"] == topic and check(m["data"])


async def close_code(ws: WebsocketCommunicator) -> int:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + WAIT
    while True:
        output = await ws.receive_output(timeout=max(deadline - loop.time(), 0.01))
        if output["type"] == "websocket.close":
            code: int = output.get("code", 1000)
            return code


async def subscribe(ws: WebsocketCommunicator, *topics: str) -> dict[str, Msg]:
    await ws.send_json_to({"t": "sub", "topics": list(topics)})
    got: dict[str, Msg] = {}
    while set(got) != set(topics):
        message = await until(ws, lambda m: m["t"] in {"snap", "gone"})
        got.setdefault(message["topic"], message)
    return got


async def listening() -> int:
    """Wait until the listener's LISTEN is live; its backend pid."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + WAIT
    while loop.time() < deadline:
        current = listener.current()
        if current is not None and current.backend_pid is not None:
            return current.backend_pid
        await asyncio.sleep(0.02)
    raise AssertionError("The listener never started listening.")


def read_scoreboard(match: Match, strangers: int = 1) -> ScoreboardRead:
    """The reader's output for the first report's screenshot, ingested: every row shows the
    player's own name and drafted hero, except the first `strangers` non-captains on each team,
    who show under in-game names nobody can place."""
    match = fresh(match)
    submission = match.submissions.filter(verdict="report").order_by("id").first()
    assert submission is not None, "Report the result first."
    hk = match.hidden_king_team
    blocks = []
    for team, side in ((hk, "Hidden King"), ("B" if hk == "A" else "A", "Archmother")):
        rows = list(
            match.participants.filter(team=team, removed_reason="")
            .select_related("player")
            .order_by("-is_captain", "id")
        )
        heroes = [
            action.target_champion.name
            for action in match.draft_actions.filter(team=team, action="pick")
            .exclude(target_champion=None)
            .select_related("target_champion")
            if action.target_champion is not None
        ]
        players = []
        for number, row in enumerate(rows):
            stranger = 0 < number <= strangers
            players.append(
                {
                    "name": f"stranger_{team}{number}" if stranger else row.player.display_name,
                    "hero": heroes[number] if number < len(heroes) else None,
                    "badge": None,
                    "k": "5",
                    "d": "4",
                    "a": "9",
                }
            )
        blocks.append({"name": side, "players": players})
    return ocr.ingest(submission.pk, {"winner": "Hidden King", "teams": blocks})
