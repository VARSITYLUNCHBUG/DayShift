"""A load test on a real Discord server: many matches at once, through every phase, with chat
flooding each match channel. Dev only (`manage.py dev_loadtest`).

The matches are played by the autopilot through the services, one move per match per tick, so
the bot's effect worker does every Discord request exactly as it would for real players: boards,
grids, pings, DMs, channels, voice. Chat comes from webhooks the bot makes in each match channel,
at the most Discord lets webhooks post there (about 30 messages a minute a channel), each message
several lines tall, so the channel scrolls as fast as a slowed-down room of twelve. Run the bot
with DISCORD_REQUEST_LOG on and read the result with `devtools/loadtest_report.py`.

Stand-in players have made-up Discord IDs, so their DMs, voice moves and member permissions are
refused by Discord (400 and 404, which don't count towards its ban). Real members would add
those requests; the report says how many were made.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx
from django.conf import settings

from devtools import autopilot, control, lookup, timers
from devtools.errors import Conflict
from league.domain.engine import TERMINAL
from league.models import Match, MatchParticipant, MatchResource, Player, QueueEntry
from league.models.matches import ResourceKind
from league.services import runtime

logger = logging.getLogger(__name__)

PLAYERS_PER_MATCH = 12
WEBHOOK_NAME = "loadtest chat"
WORDS = [
    "gg",
    "go",
    "mid",
    "push",
    "no",
    "wait",
    "ban",
    "him",
    "pick",
    "vindicta",
    "lol",
    "why",
    "ff",
    "sure",
    "ok",
    "ready",
    "rotate",
]


@dataclass(eq=False)  # Threads must stay hashable.
class Chat(threading.Thread):
    """Chat in one match channel through two webhooks, until stopped."""

    channel_id: int
    rate: float
    lines: int
    stop: threading.Event
    sent: int = 0
    limited: int = 0
    errors: int = 0
    hooks: list[dict[str, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        super().__init__(name=f"chat:{self.channel_id}", daemon=True)

    def run(self) -> None:
        api = settings.DISCORD_API_BASE
        bot = httpx.Client(headers={"Authorization": f"Bot {settings.DISCORD_TOKEN}"}, timeout=15)
        try:
            for _ in range(2):
                made = bot.post(
                    f"{api}/channels/{self.channel_id}/webhooks", json={"name": WEBHOOK_NAME}
                )
                if made.status_code >= 300:
                    logger.warning("No webhook for chat", extra={"status": made.status_code})
                    return
                self.hooks.append(made.json())
            self._chat(api)
        finally:
            for hook in self.hooks:
                bot.delete(f"{api}/webhooks/{hook['id']}")
            bot.close()

    def _chat(self, api: str) -> None:
        client = httpx.Client(timeout=15)
        n, next_at = 0, time.monotonic()
        while not self.stop.is_set() and self.limited <= 5:
            self.stop.wait(max(0.0, next_at - time.monotonic()))
            next_at += 1 / self.rate
            hook = self.hooks[n % len(self.hooks)]
            player = n % PLAYERS_PER_MATCH + 1
            body = "\n".join(
                " ".join(WORDS[(player * 7 + n * 3 + k * 5 + j) % len(WORDS)] for j in range(4))
                for k in range(self.lines)
            )
            reply = client.post(
                f"{api}/webhooks/{hook['id']}/{hook['token']}",
                json={
                    "content": body,
                    "username": f"Player {player}",
                    "allowed_mentions": {"parse": []},
                },
            )
            n += 1
            if reply.status_code == 429:
                self.limited += 1
                self.stop.wait(float(reply.json().get("retry_after", 1)) + 0.1)
                next_at = time.monotonic()
            elif reply.status_code >= 300:
                self.errors += 1
                if reply.status_code == 404:
                    return  # The channel closed.
            else:
                self.sent += 1
        client.close()


@dataclass
class Result:
    matches: list[int]
    seconds: float
    moves: int
    chat_sent: int
    chat_limited: int
    unfinished: list[int]


def _players(count: int) -> list[Player]:
    """`count` players free to queue, making stand-ins for any shortfall."""
    busy = MatchParticipant.objects.filter(is_active=True).values("player_id")
    free = (
        Player.objects.exclude(pk__in=busy)
        .exclude(pk__in=QueueEntry.objects.values("player_id"))
        .exclude(dev_profile__retired=True)
        .count()
    )
    missing = count - free
    while missing > 0:
        batch = min(missing, control.MAX_NEW_PLAYERS)
        control.create_players(batch, name_prefix="Load")
        missing -= batch
    return control.free_players(count)


def _text_channel(match_id: int) -> int | None:
    return (
        MatchResource.objects.filter(
            match_id=match_id, kind=ResourceKind.TEXT, deleted_at__isnull=True
        )
        .values_list("discord_id", flat=True)
        .first()
    )


def run(
    matches: int,
    *,
    tick: float = 2.0,
    moves_per_tick: int = 2,
    chat_rate: float = 0.45,
    chat_lines: int = 9,
    timeout: float = 1800,
    say: Callable[[str], None] = print,
) -> Result:
    """Pop `matches` matches at once and play them all to the end, chat flooding each."""
    league = lookup.community()
    settings_row = runtime.of(league)
    if settings_row.max_concurrent_matches < matches:
        runtime.update(league, max_concurrent_matches=matches)
    timers.pause_all()  # Only this test moves the matches on, so every run plays the same.
    players = _players(matches * PLAYERS_PER_MATCH)
    before = Match.objects.order_by("-pk").values_list("pk", flat=True).first() or 0
    started = time.monotonic()
    control.join_queue_players(league, players)
    ids = list(Match.objects.filter(pk__gt=before).order_by("pk").values_list("pk", flat=True))
    say(f"Popped {len(ids)} matches: {ids}")
    stop = threading.Event()
    chats: dict[int, Chat] = {}
    moves = 0
    try:
        while time.monotonic() - started < timeout:
            live = 0
            for match_id in ids:
                if chat_rate > 0 and match_id not in chats and (text := _text_channel(match_id)):
                    chats[match_id] = Chat(text, chat_rate, chat_lines, stop)
                    chats[match_id].start()
                match = Match.objects.get(pk=match_id)
                if match.status in TERMINAL:
                    continue
                live += 1
                for _ in range(moves_per_tick):
                    try:
                        next_moves = autopilot.next_moves(match)
                    except Conflict:
                        break  # Waiting on the bot, deadlock-api's lobby, or a sub.
                    if not next_moves:
                        break
                    try:
                        autopilot.make(match, next_moves[0], autopilot.SERVICE)
                    except Conflict as exc:
                        say(f"Match #{match_id}: {exc}")
                        break
                    moves += 1
                    match = Match.objects.get(pk=match_id)
                    if match.status in TERMINAL:
                        break
            if not live:
                break
            time.sleep(tick)
    finally:
        stop.set()
        for chat in chats.values():
            chat.join(timeout=30)
    unfinished = list(
        Match.objects.filter(pk__in=ids).exclude(status__in=TERMINAL).values_list("pk", flat=True)
    )
    return Result(
        matches=ids,
        seconds=time.monotonic() - started,
        moves=moves,
        chat_sent=sum(chat.sent for chat in chats.values()),
        chat_limited=sum(chat.limited for chat in chats.values()),
        unfinished=unfinished,
    )
