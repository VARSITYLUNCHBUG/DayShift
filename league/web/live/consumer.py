"""The players' websocket: `/ws/`.

A signed-in player subscribes to topics and gets a full snapshot of each, then a fresh one
whenever it changes (`hub`). The protocol is `schema`; close codes are below. Anything the
server can't parse is ignored, so an old or broken page can't take the socket down.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import Any

from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.utils import timezone
from pydantic import ValidationError

from league.web.auth.session import player_of_session
from league.web.live import actions, snapshots
from league.web.live import hub as live_hub
from league.web.live import schema as s
from league.web.live.dbpool import web_db

logger = logging.getLogger(__name__)

CLOSE_SIGNED_OUT = live_hub.CLOSE_SIGNED_OUT  # Not signed in, signed out, or the session's gone.
CLOSE_NOT_ALLOWED = live_hub.CLOSE_NOT_ALLOWED  # The player no longer exists.
CLOSE_NO_PING = 4408
CLOSE_TOO_MANY_TOPICS = 4409
CLOSE_TOO_MANY_ACTIONS = 4429
CLOSE_SERVER_ERROR = 1011


class LiveConsumer(AsyncJsonWebsocketConsumer):  # type: ignore[misc]
    PING_TIMEOUT = 60.0  # Seconds without a ping before the socket is closed.
    MAX_TOPICS = 10
    MAX_ACTIONS = 10  # Per ACTION_WINDOW: far past any player's clicking.
    ACTION_WINDOW = 5.0
    SEEN_IDS = 256  # Action ids remembered, to answer a repeated one only once.

    conn: live_hub.Conn | None = None
    hub: live_hub.Hub | None = None
    _watchdog: asyncio.Task[None] | None = None
    _last_ping = 0.0

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._acted: deque[float] = deque()  # When the recent actions arrived.
        self._seen: dict[str, None] = {}  # Action ids in arrival order.
        self._acting: set[asyncio.Task[None]] = set()
        # One action at a time, in the order sent, while pings and subscriptions carry on.
        self._turn = asyncio.Lock()

    async def connect(self) -> None:
        # Accept first: a refusal before accepting reaches the browser only as a failed
        # handshake, and the page needs the code to know to send the player to sign in.
        await self.accept()
        session = self.scope.get("session")
        # None for no session, a signed-out one, or a player made inactive since.
        player = await player_of_session(session) if session is not None else None
        if player is None:
            await self.close(code=CLOSE_SIGNED_OUT)
            return
        community_id = await web_db(snapshots.web_community_id)
        if community_id is None:
            logger.error("The web's server (WEB_GUILD_ID) isn't set up, so the socket closed.")
            await self.close(code=CLOSE_SERVER_ERROR)
            return
        self.hub = live_hub.get()
        self.conn = self.hub.connect(
            player.pk, community_id, session.session_key, self.send_json, self._close
        )
        self.conn.push(s.Hello(t="hello", server_time=timezone.now(), player_id=str(player.pk)))
        self._last_ping = asyncio.get_running_loop().time()
        self._watchdog = asyncio.create_task(self._watch())

    async def disconnect(self, code: int) -> None:
        if self._watchdog is not None:
            self._watchdog.cancel()
        if self.hub is not None and self.conn is not None:
            self.hub.disconnect(self.conn)

    async def receive(
        self, text_data: str | None = None, bytes_data: bytes | None = None, **kwargs: Any
    ) -> None:
        if self.conn is None or self.conn.closed:
            return
        if text_data is None:
            logger.debug("Ignored a binary websocket message.")
            return
        try:
            message = s.ClientMessage.model_validate_json(text_data).root
        except ValidationError as error:
            logger.debug("Ignored a websocket message: %s", error)
            return
        await self.handle(message)

    async def handle(self, message: s.Subscribe | s.Unsubscribe | s.Ping | s.Act) -> None:
        assert self.hub is not None and self.conn is not None
        match message:
            case s.Ping():
                self._last_ping = asyncio.get_running_loop().time()
                self.conn.push(s.Pong(t="pong", server_time=timezone.now()))
            case s.Subscribe(topics=topics):
                if len(self.conn.topics | set(topics)) > self.MAX_TOPICS:
                    self.hub.close(self.conn, CLOSE_TOO_MANY_TOPICS)
                    return
                self.hub.subscribe(self.conn, dict.fromkeys(topics))
            case s.Unsubscribe(topics=topics):
                self.hub.unsubscribe(self.conn, topics)
            case s.Act():
                self.act(message)

    def act(self, message: s.Act) -> None:
        """An action from the page: past the rate limit (MAX_ACTIONS per ACTION_WINDOW, repeats
        included), and not a repeat, it runs in turn."""
        assert self.hub is not None and self.conn is not None
        now = asyncio.get_running_loop().time()
        while self._acted and now - self._acted[0] >= self.ACTION_WINDOW:
            self._acted.popleft()
        if len(self._acted) >= self.MAX_ACTIONS:
            self.hub.close(self.conn, CLOSE_TOO_MANY_ACTIONS)
            return
        self._acted.append(now)
        if message.id in self._seen:  # Already answered, or about to be.
            return
        self._seen[message.id] = None
        if len(self._seen) > self.SEEN_IDS:
            del self._seen[next(iter(self._seen))]
        task = asyncio.get_running_loop().create_task(self._run(message))
        self._acting.add(task)
        task.add_done_callback(self._acting.discard)

    async def _run(self, message: s.Act) -> None:
        """Run the action, queue the snapshots it changed for this player, then the ack. It's
        never retried: if the socket went meanwhile, the page learns the outcome from its next
        snapshots."""
        assert self.hub is not None and self.conn is not None
        hub, conn = self.hub, self.conn
        async with self._turn:
            if conn.closed:
                return
            reply = await actions.dispatch(
                conn.player_id, conn.community_id, message.name, message.args
            )
            if conn.closed:
                return
            if reply.ok:
                await hub.refresh(conn, reply.topics)
            conn.push(
                s.Ack(t="ack", id=message.id, ok=reply.ok, error=reply.error, result=reply.result)
            )

    async def _watch(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            left = self._last_ping + self.PING_TIMEOUT - loop.time()
            if left <= 0:
                assert self.hub is not None and self.conn is not None
                self.hub.close(self.conn, CLOSE_NO_PING)
                return
            await asyncio.sleep(left)

    async def _close(self, code: int) -> None:
        await self.close(code=code)
