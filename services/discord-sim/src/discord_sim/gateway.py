"""The gateway websocket at /gateway: HELLO, IDENTIFY, READY, heartbeats, RESUME and dispatches.

Each connection gets an outbound queue drained by one writer task, so frames keep their sequence
order. Sessions outlive their connection for RESUME_WINDOW_SECONDS and buffer what they miss.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import secrets
import time
import zlib
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from aiohttp import WSMsgType, web

from discord_sim import payloads
from discord_sim.config import Config
from discord_sim.eventlog import EventLog
from discord_sim.state import DM, Channel, Message, SimState, User, VoiceChange

GUILDS = 1 << 0
GUILD_MEMBERS = 1 << 1
GUILD_VOICE_STATES = 1 << 7
GUILD_MESSAGES = 1 << 9
DIRECT_MESSAGES = 1 << 12
MESSAGE_CONTENT = 1 << 15

HEARTBEAT_INTERVAL_MS = 41_250
# Real Discord answers a heartbeat after a network round trip. discord.py records when it sent the
# heartbeat only after its keep-alive thread wakes up again, so an instant local ACK can land first
# and read as a whole interval of latency ("Can't keep up ... 41.3s behind"). A delay fixes that.
HEARTBEAT_ACK_DELAY_SECONDS = 0.05
RESUME_WINDOW_SECONDS = 120.0
BUFFER_SIZE = 2_000

DISPATCH = 0
HEARTBEAT = 1
IDENTIFY = 2
PRESENCE_UPDATE = 3
VOICE_STATE_UPDATE = 4
RESUME = 6
RECONNECT = 7
REQUEST_GUILD_MEMBERS = 8
INVALID_SESSION = 9
HELLO = 10
HEARTBEAT_ACK = 11

Frame = dict[str, Any]
Builder = Callable[["Session"], payloads.Payload | None]


@dataclass
class _Close:
    code: int
    reason: str


@dataclass
class Session:
    id: str
    intents: int
    base: str
    seq: int = 0
    buffer: deque[Frame] = field(default_factory=lambda: deque(maxlen=BUFFER_SIZE))
    connection: Connection | None = None
    disconnected_at: float | None = None

    def expired(self, now: float) -> bool:
        return (
            self.connection is None
            and self.disconnected_at is not None
            and now - self.disconnected_at > RESUME_WINDOW_SECONDS
        )


class Connection:
    """One websocket. Frames go out in order through a queue; zlib-stream if the client asked."""

    def __init__(self, ws: web.WebSocketResponse, *, compress: bool) -> None:
        self.ws = ws
        self.session: Session | None = None
        self._compressor = zlib.compressobj() if compress else None
        self._queue: asyncio.Queue[Frame | _Close] = asyncio.Queue()
        self._writer = asyncio.create_task(self._write(), name="gateway-writer")

    def send(self, frame: Frame) -> None:
        self._queue.put_nowait(frame)

    def close(self, code: int, reason: str = "") -> None:
        self._queue.put_nowait(_Close(code, reason))

    async def drain(self) -> None:
        await self._queue.join()

    async def stop(self) -> None:
        self._writer.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._writer

    async def _write(self) -> None:
        while True:
            item = await self._queue.get()
            try:
                if isinstance(item, _Close):
                    await self.ws.close(code=item.code, message=item.reason.encode())
                elif not self.ws.closed:
                    text = json.dumps(item, separators=(",", ":"))
                    if self._compressor is not None:
                        data = self._compressor.compress(text.encode())
                        data += self._compressor.flush(zlib.Z_SYNC_FLUSH)
                        await self.ws.send_bytes(data)
                    else:
                        await self.ws.send_str(text)
            except ConnectionError:
                pass  # The client went away; the reader notices and cleans up.
            finally:
                self._queue.task_done()


class Gateway:
    def __init__(self, config: Config, state: SimState, log: EventLog) -> None:
        self.config = config
        self.state = state
        self.log = log
        self.sessions: dict[str, Session] = {}
        self.connections: set[Connection] = set()

    @property
    def bot_connected(self) -> bool:
        return any(s.connection is not None for s in self.sessions.values())

    # --- Websocket --------------------------------------------------------------------------

    async def handle(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(max_msg_size=16 * 1024 * 1024)
        await ws.prepare(request)
        connection = Connection(ws, compress=request.query.get("compress") == "zlib-stream")
        self.connections.add(connection)
        base = self.config.public_url or f"{request.scheme}://{request.host}"
        try:
            if request.query.get("encoding", "json") != "json":
                connection.close(4002, "Only encoding=json is supported.")
            else:
                connection.send(
                    {
                        "op": HELLO,
                        "d": {"heartbeat_interval": HEARTBEAT_INTERVAL_MS, "_trace": ["sim"]},
                        "s": None,
                        "t": None,
                    }
                )
                async for msg in ws:
                    if msg.type not in (WSMsgType.TEXT, WSMsgType.BINARY):
                        break
                    try:
                        frame = json.loads(msg.data)
                    except ValueError:
                        connection.close(4002, "Error while decoding payload.")
                        continue
                    self._receive(connection, frame, base)
            await connection.drain()
        finally:
            await connection.stop()
            self.connections.discard(connection)
            session = connection.session
            if session is not None and session.connection is connection:
                session.connection = None
                session.disconnected_at = time.monotonic()
                self.log.add("gateway", event="DISCONNECTED", session_id=session.id)
        return ws

    def _receive(self, connection: Connection, frame: Frame, base: str) -> None:
        op = frame.get("op")
        data = frame.get("d")
        if op == HEARTBEAT:
            ack = {"op": HEARTBEAT_ACK, "d": None, "s": None, "t": None}
            asyncio.get_running_loop().call_later(HEARTBEAT_ACK_DELAY_SECONDS, connection.send, ack)
        elif op == IDENTIFY:
            self._identify(connection, data or {}, base)
        elif op == RESUME:
            self._resume(connection, data or {})
        elif connection.session is None:
            connection.close(4003, "Not authenticated.")
        elif op in (PRESENCE_UPDATE, VOICE_STATE_UPDATE, REQUEST_GUILD_MEMBERS):
            self.log.add("gateway", event=f"OP_{op}_IGNORED", data=data)
        else:
            connection.close(4001, "Unknown opcode.")

    def _identify(self, connection: Connection, data: dict[str, Any], base: str) -> None:
        if connection.session is not None:
            connection.close(4005, "Already authenticated.")
            return
        if not self.config.token_ok(str(data.get("token") or "")):
            connection.close(4004, "Authentication failed.")
            return
        intents = int(data.get("intents") or 0)
        if intents & MESSAGE_CONTENT and not self.config.message_content_intent:
            connection.close(4014, "Disallowed intent(s).")
            return
        session = Session(id=secrets.token_hex(16), intents=intents, base=base)
        session.connection = connection
        connection.session = session
        self.sessions[session.id] = session
        resume_url = base.replace("http", "ws", 1) + "/gateway"
        self._send_dispatch(session, "READY", payloads.ready(self.state, session.id, resume_url))
        self._send_dispatch(session, "GUILD_CREATE", payloads.guild_create(self.state, intents))
        self.log.add("gateway", event="IDENTIFY", session_id=session.id, intents=intents)

    def _resume(self, connection: Connection, data: dict[str, Any]) -> None:
        if not self.config.token_ok(str(data.get("token") or "")):
            connection.close(4004, "Authentication failed.")
            return
        session = self.sessions.get(str(data.get("session_id")))
        seq = data.get("seq")
        missed = [f for f in session.buffer if f["s"] > (seq or 0)] if session else []
        complete = (
            session is not None
            and isinstance(seq, int)
            and (not missed or missed[0]["s"] == seq + 1)
            and not session.expired(time.monotonic())
        )
        if session is None or not complete:
            connection.send({"op": INVALID_SESSION, "d": False, "s": None, "t": None})
            self.log.add("gateway", event="INVALID_SESSION", session_id=data.get("session_id"))
            return
        if session.connection is not None:
            session.connection.close(4000, "Session resumed elsewhere.")
        session.connection = connection
        session.disconnected_at = None
        connection.session = session
        for frame in missed:
            connection.send(frame)
        self._send_dispatch(session, "RESUMED", {"_trace": ["sim"]})
        self.log.add("gateway", event="RESUMED", session_id=session.id, replayed=len(missed))

    def _send_dispatch(self, session: Session, event: str, data: payloads.Payload) -> None:
        session.seq += 1
        frame: Frame = {"op": DISPATCH, "t": event, "s": session.seq, "d": data}
        session.buffer.append(frame)
        if session.connection is not None:
            session.connection.send(frame)

    # --- Dispatch ---------------------------------------------------------------------------

    def dispatch(self, event: str, build: Builder, intent: int | None = None) -> int:
        """Send an event to every session with the intent. Returns how many got it."""
        now = time.monotonic()
        for sid in [sid for sid, s in self.sessions.items() if s.expired(now)]:
            del self.sessions[sid]
        sent = 0
        logged: payloads.Payload | None = None
        for session in self.sessions.values():
            if intent is not None and not session.intents & intent:
                continue
            data = build(session)
            if data is None:
                continue
            self._send_dispatch(session, event, data)
            logged = logged or data
            sent += 1
        self.log.add("gateway", event=event, data=logged, sessions=sent)
        return sent

    async def drain(self, timeout: float = 2.0) -> None:
        """Wait for queued frames to go out, so events reach the bot before the REST reply."""
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(
                asyncio.gather(*(c.drain() for c in list(self.connections))), timeout
            )

    async def reconnect_all(self) -> None:
        """Forget every session and ask clients to reconnect; they come back with a fresh READY."""
        for session in self.sessions.values():
            if session.connection is not None:
                session.connection.send({"op": RECONNECT, "d": None, "s": None, "t": None})
        self.sessions.clear()
        await self.drain()

    async def shutdown(self) -> None:
        for connection in list(self.connections):
            connection.close(4000, "The sim is shutting down.")
        await self.drain()

    # --- Typed events -----------------------------------------------------------------------

    def channel_event(self, event: str, channel: Channel) -> None:
        if channel.type == DM:
            return  # Bots don't get CHANNEL_CREATE for DMs.
        self.dispatch(event, lambda _s: payloads.channel(self.state, channel), GUILDS)

    def message_create(self, message: Message) -> None:
        self._message_event("MESSAGE_CREATE", message)

    def message_update(self, message: Message) -> None:
        self._message_event("MESSAGE_UPDATE", message)

    def _message_event(self, event: str, message: Message) -> None:
        if message.ephemeral:
            return
        dm = message.channel_id in self.state.dm_channels
        intent = DIRECT_MESSAGES if dm else GUILD_MESSAGES

        def build(session: Session) -> payloads.Payload:
            hide = (
                not dm
                and not session.intents & MESSAGE_CONTENT
                and message.author_id != self.state.bot_user.id
                and self.state.bot_user.id not in message.mentions
            )
            return payloads.message(self.state, message, session.base, hide_content=hide)

        self.dispatch(event, build, intent)

    def message_delete(self, message: Message) -> None:
        if message.ephemeral:
            return
        dm = message.channel_id in self.state.dm_channels
        data: payloads.Payload = {"id": str(message.id), "channel_id": str(message.channel_id)}
        if not dm:
            data["guild_id"] = str(self.state.guild.id)
        self.dispatch("MESSAGE_DELETE", lambda _s: data, DIRECT_MESSAGES if dm else GUILD_MESSAGES)

    def voice_state_update(self, change: VoiceChange) -> None:
        data = payloads.voice_state(
            self.state,
            change.state,
            user_id=change.user_id,
            session_id=change.session_id,
            full=True,
        )
        self.dispatch("VOICE_STATE_UPDATE", lambda _s: data, GUILD_VOICE_STATES)

    def member_event(self, event: str, user_id: int) -> None:
        """GUILD_MEMBER_ADD or GUILD_MEMBER_UPDATE, for sessions with the members intent."""
        data = payloads.member(self.state, self.state.guild.members[user_id]) | {
            "guild_id": str(self.state.guild.id)
        }
        self.dispatch(event, lambda _s: data, GUILD_MEMBERS)

    def member_remove(self, user: User) -> None:
        data = {"guild_id": str(self.state.guild.id), "user": payloads.user(user)}
        self.dispatch("GUILD_MEMBER_REMOVE", lambda _s: data, GUILD_MEMBERS)

    def role_create(self, role_id: int) -> None:
        data = {
            "guild_id": str(self.state.guild.id),
            "role": payloads.role(self.state.guild.roles[role_id]),
        }
        self.dispatch("GUILD_ROLE_CREATE", lambda _s: data, GUILDS)

    def interaction_create(self, build: Callable[[str], payloads.Payload]) -> bool:
        """Interactions go to one connected session only, as on Discord. False if none is."""
        for session in self.sessions.values():
            if session.connection is not None:
                data = build(session.base)
                self._send_dispatch(session, "INTERACTION_CREATE", data)
                self.log.add("gateway", event="INTERACTION_CREATE", data=data, sessions=1)
                return True
        return False
