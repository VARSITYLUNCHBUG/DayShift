"""Fan-out inside the web process: from "this changed" to fresh snapshots on open sockets.

One hub per process, no Redis and no channel layer: the web runs one process, and Postgres
NOTIFY (`listener`) already tells it what changed. The hub maps each database topic to the
snapshots that show it, rebuilds each one once, and offers the result to every socket watching:

- `match:{id}` → that match's watchers, the server's `live` list, and the `me` of everyone on
  its roster before and after the change (so someone subbed out sees it too).
- `queue:{cid}` → the server's queue, and every `me` there (priority places shift).
- `player:{pk}` → that player's `me`, and a check that each of their sockets is still signed in
  (signing out publishes this).

A topic is never built twice at once: a change during a build marks it to run once more after.
Each socket holds only the newest snapshot of each topic, so a slow browser skips to the latest
instead of working through a backlog. A safety poll catches anything a lost notification missed.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import time
from collections.abc import Awaitable, Callable, Coroutine, Iterable
from contextlib import suppress
from importlib import import_module
from typing import Any, Literal, NamedTuple, overload

from django.conf import settings
from pydantic import BaseModel

from league.models import Match, Player
from league.web.auth.session import SESSION_KEY
from league.web.live import listener, snapshots
from league.web.live import schema as s
from league.web.live.dbpool import web_db

logger = logging.getLogger(__name__)

MATCH_POLL = 15.0  # Seconds between checks of watched matches' versions.
FULL_POLL = 60.0  # Seconds between rebuilds of every queue, live list and `me` in use.
MAX_ID = 2**63 - 1  # A match topic past this can't name a row.
REFRESH_WAIT = 5.0  # Seconds an action's ack waits for its snapshots before going anyway.

CLOSE_SIGNED_OUT = 4401
CLOSE_NOT_ALLOWED = 4403

type Message = dict[str, Any]
type Send = Callable[[Message], Awaitable[None]]
type Close = Callable[[int], Coroutine[Any, Any, None]]


class Key(NamedTuple):
    """Something the hub builds. `id` is the player for `me` and `auth`, the server for `queue`
    and `live`, and the match for `match`."""

    kind: Literal["me", "queue", "live", "match", "auth"]
    id: int
    community_id: int = 0  # `me` only: whose server.


class Conn:
    """One open socket, as the hub sees it: who it is, what it watches, what it's about to get."""

    def __init__(
        self, player_id: int, community_id: int, session_key: str | None, send: Send, close: Close
    ) -> None:
        self.player_id = player_id
        self.community_id = community_id
        self.session_key = session_key
        self.topics: set[str] = set()
        self.closed = False
        self._send = send
        self._close = close
        # Pending messages in send order. A snapshot is keyed by its topic, so a newer one takes
        # the older one's place; anything else gets a key of its own.
        self._outbox: dict[str, Message] = {}
        self._revs: dict[str, int] = {}  # The highest rev queued per topic.
        self._seq = itertools.count()
        self._wake = asyncio.Event()
        loop = asyncio.get_running_loop()
        self._writer = loop.create_task(self._write())
        self._closing: asyncio.Task[None] | None = None

    def push(self, message: BaseModel) -> None:
        """A message that isn't a snapshot (hello, pong, ack): sent in order, never replaced."""
        self._put(f"#{next(self._seq)}", message.model_dump(mode="json"))

    def offer(self, topic: str, rev: int, message: Message) -> None:
        """The newest snapshot of a topic. One older than what this socket already has is
        dropped, so a rev never goes backwards."""
        if rev < self._revs.get(topic, rev):
            return
        self._revs[topic] = rev
        self._put(topic, message)

    def gone(self, topic: str) -> None:
        self.forget(topic)
        self._put(topic, s.Gone(t="gone", topic=topic, reason="not_found").model_dump(mode="json"))

    def forget(self, topic: str) -> None:
        self._outbox.pop(topic, None)
        self._revs.pop(topic, None)

    def pending(self) -> list[Message]:
        """What's queued and not yet sent. For tests."""
        return list(self._outbox.values())

    def detach(self) -> None:
        """Stop sending: the socket is gone."""
        self.closed = True
        self._writer.cancel()

    def shut(self, code: int) -> None:
        """Close the socket with this code."""
        if self._closing is not None:
            return
        self.detach()
        self._closing = asyncio.get_running_loop().create_task(self._close(code))

    def _put(self, key: str, message: Message) -> None:
        if self.closed:
            return
        self._outbox[key] = message
        self._wake.set()

    async def _write(self) -> None:
        while True:
            await self._wake.wait()
            self._wake.clear()
            while self._outbox:
                key = next(iter(self._outbox))
                message = self._outbox.pop(key)
                try:
                    await self._send(message)
                except Exception as error:  # The socket went away mid-send.
                    logger.debug("A websocket send failed: %s", error)
                    return


def _topic(key: Key) -> str:
    return f"match:{key.id}" if key.kind == "match" else key.kind


# --- Database work, on the web_db threads ------------------------------------------------------


def _match_change(
    match_id: int, want_body: bool
) -> tuple[int | None, frozenset[int], snapshots.MatchBody | None]:
    """After a match changed: its server, its roster now, and its body if anyone's watching."""
    community_id = Match.objects.filter(pk=match_id).values_list("community_id", flat=True).first()
    if community_id is None:
        return None, frozenset(), None
    body = snapshots.build_match(match_id) if want_body else None
    return community_id, snapshots.roster_of(match_id), body


def _versions_of(match_ids: list[int]) -> dict[int, int]:
    return dict(Match.objects.filter(pk__in=match_ids).values_list("pk", "version"))


def _session_holders(
    player_id: int, session_keys: Iterable[str | None]
) -> tuple[bool, dict[str | None, Any]]:
    """Whether the player still exists, and whom each session is signed in as now: None once
    signed out, or once the player is made inactive (`league.web.auth.session`)."""
    player = Player.objects.filter(pk=player_id).values_list("is_active", flat=True).first()
    engine = import_module(settings.SESSION_ENGINE)
    holders = {
        key: engine.SessionStore(key).get(SESSION_KEY) if key else None for key in session_keys
    }
    if not player:
        holders = dict.fromkeys(holders)
    return player is not None, holders


# --- The hub ----------------------------------------------------------------------------------


class Hub:
    def __init__(self, match_poll: float | None = None, full_poll: float | None = None) -> None:
        self.loop = asyncio.get_running_loop()
        self.match_poll = MATCH_POLL if match_poll is None else match_poll
        self.full_poll = FULL_POLL if full_poll is None else full_poll
        self._conns: set[Conn] = set()
        self._players: dict[int, set[Conn]] = {}
        self._subs: dict[Key, set[Conn]] = {}
        # Builds: one task per key at most; `_changed` asks for a rebuild for everyone watching,
        # `_waiting` for a first snapshot for just these sockets.
        self._running: dict[Key, asyncio.Task[None]] = {}
        self._changed: set[Key] = set()
        self._waiting: dict[Key, set[Conn]] = {}
        self._done: dict[Key, list[asyncio.Future[None]]] = {}  # Settled with `_waiting`'s build.
        self._rosters: dict[int, frozenset[int]] = {}  # The last roster seen per match.
        self._versions: dict[int, int] = {}  # The last version built per watched match.
        self._rev = 0
        self._poller: asyncio.Task[None] | None = None

    # --- Lifecycle

    def start(self) -> None:
        self._poller = self.loop.create_task(self._poll())
        listener.start(on_topic=self._from_thread(self.notify), on_connect=self._resync_soon)

    async def stop(self) -> None:
        await asyncio.to_thread(listener.stop)
        tasks = [task for task in (self._poller, *self._running.values()) if task is not None]
        for conn in list(self._conns):
            self.disconnect(conn)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def _from_thread(self, fn: Callable[[str], None]) -> Callable[[str], None]:
        def post(topic: str) -> None:
            with suppress(RuntimeError):  # The loop has closed.
                self.loop.call_soon_threadsafe(fn, topic)

        return post

    def _resync_soon(self) -> None:
        with suppress(RuntimeError):
            self.loop.call_soon_threadsafe(self.resync)

    # --- Sockets

    def connect(
        self, player_id: int, community_id: int, session_key: str | None, send: Send, close: Close
    ) -> Conn:
        conn = Conn(player_id, community_id, session_key, send, close)
        self._conns.add(conn)
        self._players.setdefault(player_id, set()).add(conn)
        return conn

    def disconnect(self, conn: Conn) -> None:
        if conn not in self._conns:
            return
        self._conns.discard(conn)
        same = self._players.get(conn.player_id, set())
        same.discard(conn)
        if not same:
            self._players.pop(conn.player_id, None)
        for topic in list(conn.topics):
            self._drop(conn, topic)
        conn.detach()

    def close(self, conn: Conn, code: int) -> None:
        self.disconnect(conn)
        conn.shut(code)

    def subscribe(self, conn: Conn, topics: Iterable[str]) -> None:
        """Watch these topics. Each gets a snapshot (or `gone`) now, even if already watched."""
        for topic in topics:
            if topic.startswith("match:") and int(topic.removeprefix("match:")) > MAX_ID:
                conn.gone(topic)
                continue
            key = self._key(conn, topic)
            if topic not in conn.topics:
                conn.topics.add(topic)
                self._subs.setdefault(key, set()).add(conn)
            self._schedule(key, conn)

    def unsubscribe(self, conn: Conn, topics: Iterable[str]) -> None:
        for topic in topics:
            if topic in conn.topics:
                self._drop(conn, topic)
            conn.forget(topic)

    def _key(self, conn: Conn, topic: str) -> Key:
        if topic == "me":
            return Key("me", conn.player_id, conn.community_id)
        if topic == "queue":
            return Key("queue", conn.community_id)
        if topic == "live":
            return Key("live", conn.community_id)
        return Key("match", int(topic.removeprefix("match:")))

    def _drop(self, conn: Conn, topic: str) -> None:
        conn.topics.discard(topic)
        key = self._key(conn, topic)
        watching = self._subs.get(key)
        if watching is None:
            return
        watching.discard(conn)
        if not watching:
            del self._subs[key]
            if key.kind == "match":
                self._versions.pop(key.id, None)

    # --- What changed

    def notify(self, topic: str) -> None:
        """A database topic from `league.services.live`."""
        if not self._conns:
            return
        kind, _, raw = topic.partition(":")
        try:
            ident = int(raw)
        except ValueError:
            logger.debug("Ignored the live topic %r.", topic)
            return
        if kind == "match":
            self._schedule(Key("match", ident))
        elif kind == "queue":
            self._schedule_if_watched(Key("queue", ident))
            for key in self._me_keys(lambda key: key.community_id == ident):
                self._schedule(key)
        elif kind == "player":
            for key in self._me_keys(lambda key: key.id == ident):
                self._schedule(key)
            if ident in self._players:
                self._schedule(Key("auth", ident))
        else:
            logger.debug("Ignored the live topic %r.", topic)

    def resync(self) -> None:
        """Rebuild everything served: notifications may have been missed."""
        for key in list(self._subs):
            self._schedule(key)
        for player_id in list(self._players):
            self._schedule(Key("auth", player_id))

    async def refresh(self, conn: Conn, topics: Iterable[str], wait: float | None = None) -> None:
        """After this socket's own action: rebuild what it changed for this socket and wait for
        the builds, so their snapshots are queued before the ack. Everyone else, this socket
        included, still gets the usual refresh when the notification arrives."""
        keys = {key for topic in topics for key in self._affected(conn, topic)}
        done = [self._schedule(key, conn) for key in keys]
        if not done:
            return
        _, late = await asyncio.wait(done, timeout=REFRESH_WAIT if wait is None else wait)
        if late:
            logger.warning("An action's snapshots took too long; acking without them.")

    def _affected(self, conn: Conn, topic: str) -> list[Key]:
        """What this socket watches that a database topic changes."""
        kind, _, raw = topic.partition(":")
        try:
            ident = int(raw)
        except ValueError:
            return []
        watched: list[str] = []
        if kind == "match":
            watched = [f"match:{ident}", "live", "me"]
        elif kind == "queue" and ident == conn.community_id:
            watched = ["queue", "me"]
        elif kind == "player" and ident == conn.player_id:
            watched = ["me"]
        return [self._key(conn, name) for name in watched if name in conn.topics]

    def _me_keys(self, which: Callable[[Key], bool]) -> list[Key]:
        return [key for key in self._subs if key.kind == "me" and which(key)]

    def _schedule_if_watched(self, key: Key) -> None:
        if key in self._subs:
            self._schedule(key)

    # --- Builds

    @overload
    def _schedule(self, key: Key) -> None: ...
    @overload
    def _schedule(self, key: Key, conn: Conn) -> asyncio.Future[None]: ...
    def _schedule(self, key: Key, conn: Conn | None = None) -> asyncio.Future[None] | None:
        """Build `key` for everyone watching it (a change), or for one socket that just asked.
        The socket's build starts after this call, so it reads anything committed before; the
        future settles once its snapshot is queued."""
        done: asyncio.Future[None] | None = None
        if conn is None:
            self._changed.add(key)
        else:
            self._waiting.setdefault(key, set()).add(conn)
            done = self.loop.create_future()
            self._done.setdefault(key, []).append(done)
        if key not in self._running:
            self._running[key] = self.loop.create_task(self._drive(key))
        return done

    async def _drive(self, key: Key) -> None:
        try:
            while key in self._changed or self._waiting.get(key):
                changed = key in self._changed
                self._changed.discard(key)
                waiting = self._waiting.pop(key, set())
                done = self._done.pop(key, [])
                try:
                    await self._build(key, changed, waiting)
                except Exception:
                    logger.exception("Couldn't refresh %s.", key)
                finally:
                    for future in done:
                        if not future.done():
                            future.set_result(None)
        finally:
            self._running.pop(key, None)

    def _targets(self, key: Key, changed: bool, waiting: set[Conn]) -> list[Conn]:
        watching = self._subs.get(key, set())
        return list(watching) if changed else [conn for conn in waiting if conn in watching]

    def _next_rev(self) -> int:
        # Milliseconds since the epoch where possible, so revs keep rising across a restart.
        self._rev = max(self._rev + 1, time.time_ns() // 1_000_000)
        return self._rev

    async def _build(self, key: Key, changed: bool, waiting: set[Conn]) -> None:
        if key.kind == "match":
            await self._build_match(key, changed, waiting)
            return
        if key.kind == "auth":
            await self._check_sessions(key.id)
            return
        if not self._targets(key, changed, waiting):
            return
        message: s.MeSnapMessage | s.QueueSnapMessage | s.LiveSnapMessage
        if key.kind == "me":
            me = await web_db(snapshots.build_me, key.id, key.community_id)
            if me is None:  # The player is gone.
                for conn in list(self._players.get(key.id, ())):
                    self.close(conn, CLOSE_NOT_ALLOWED)
                return
            message = s.MeSnapMessage(t="snap", topic="me", rev=self._next_rev(), data=me)
        elif key.kind == "queue":
            queue = await web_db(snapshots.build_queue, key.id)
            message = s.QueueSnapMessage(t="snap", topic="queue", rev=self._next_rev(), data=queue)
        else:
            matches = await web_db(snapshots.build_live, key.id)
            message = s.LiveSnapMessage(t="snap", topic="live", rev=self._next_rev(), data=matches)
        payload = message.model_dump(mode="json")
        for conn in self._targets(key, changed, waiting):
            conn.offer(message.topic, message.rev, payload)

    async def _build_match(self, key: Key, changed: bool, waiting: set[Conn]) -> None:
        watched = key in self._subs
        if changed:
            community_id, roster, body = await web_db(_match_change, key.id, watched)
            self._follow_roster(key.id, community_id, roster)
            if community_id is not None:
                self._schedule_if_watched(Key("live", community_id))
            if not watched:
                return
        else:
            body = await web_db(snapshots.build_match, key.id)
        if body is not None and key in self._subs:
            self._versions[key.id] = body.version
        self._send_match(key, body, self._targets(key, changed, waiting))

    def _follow_roster(
        self, match_id: int, community_id: int | None, roster: frozenset[int]
    ) -> None:
        """Refresh `me` for everyone who was or is on the match: joining, leaving and status
        changes all show there."""
        before = self._rosters.pop(match_id, frozenset())
        served = {conn.community_id for conn in self._conns}
        if roster and community_id in served:
            self._rosters[match_id] = roster
        everyone = before | roster
        for me in self._me_keys(lambda key: key.id in everyone):
            self._schedule(me)

    def _send_match(self, key: Key, body: snapshots.MatchBody | None, targets: list[Conn]) -> None:
        topic = _topic(key)
        public: Message | None = None
        for conn in targets:
            # Not there, or not this server's: the same answer, so neither is revealed.
            if body is None or body.community_id != conn.community_id:
                self._drop(conn, topic)
                conn.gone(topic)
                continue
            if conn.player_id in body.participants:
                payload = self._match_message(topic, body, conn.player_id)
            else:
                if public is None:
                    public = self._match_message(topic, body, None)
                payload = public
            conn.offer(topic, body.version, payload)

    @staticmethod
    def _match_message(topic: str, body: snapshots.MatchBody, viewer: int | None) -> Message:
        snap = snapshots.project_match(body, viewer)
        message = s.MatchSnapMessage(t="snap", topic=topic, rev=body.version, data=snap)
        return message.model_dump(mode="json")

    async def _check_sessions(self, player_id: int) -> None:
        """Close this player's sockets whose session no longer signs them in."""
        conns = list(self._players.get(player_id, ()))
        if not conns:
            return
        exists, holders = await web_db(
            _session_holders, player_id, {conn.session_key for conn in conns}
        )
        for conn in conns:
            if not exists:
                self.close(conn, CLOSE_NOT_ALLOWED)
            elif holders.get(conn.session_key) != player_id:
                self.close(conn, CLOSE_SIGNED_OUT)

    # --- Safety poll

    async def _poll(self) -> None:
        last_matches = last_full = self.loop.time()
        while True:
            await asyncio.sleep(min(self.match_poll, self.full_poll))
            now = self.loop.time()
            try:
                if now - last_matches >= self.match_poll:
                    last_matches = now
                    await self._poll_matches()
                if now - last_full >= self.full_poll:
                    last_full = now
                    for key in list(self._subs):
                        if key.kind != "match":
                            self._schedule(key)
                    for player_id in list(self._players):
                        self._schedule(Key("auth", player_id))
            except Exception:
                logger.exception("The live safety poll failed.")

    async def _poll_matches(self) -> None:
        watched = [key.id for key in self._subs if key.kind == "match"]
        if not watched:
            return
        versions = await web_db(_versions_of, watched)
        for match_id in watched:
            if versions.get(match_id) != self._versions.get(match_id):
                self._schedule(Key("match", match_id))


# --- The process's hub ------------------------------------------------------------------------

_hub: Hub | None = None


def get() -> Hub:
    """The process's hub, started on first use (uvicorn runs without lifespan events)."""
    global _hub
    loop = asyncio.get_running_loop()
    if _hub is None or _hub.loop is not loop:
        reset()
        _hub = Hub()
        _hub.start()
    return _hub


async def stop() -> None:
    """Stop the hub and its listener, on the hub's loop."""
    global _hub
    hub, _hub = _hub, None
    if hub is not None:
        await hub.stop()


def reset() -> None:
    """Forget the hub and stop the listener, from anywhere (a test whose loop has closed)."""
    global _hub
    _hub = None
    listener.stop()
