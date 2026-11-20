"""The match chats on the web: the lobby chat while the teams are being made, then each team's own.

There is one chat a player can see at a time, chosen from the match's status:

- The lobby chat, for everyone on the roster, is open in the captain vote, the check-in and the
  player draft.
- Each team's chat, for that team's roster only, is open from the coinflip until the game ends,
  then read-only until the result is settled. Once the match is over there's none.
- A scrim has no lobby chat; its teams' chats are open during its hero draft.

A player who is subbed out leaves the roster, and with it the chat. Messages are plain text and
web-only: the Discord bot never shows them.

Between the messages, system lines say what happened (`system_lines`): the captains and the player
draft in the lobby chat; the hero draft, swaps, subs and the start of the game in the team chats.
They're made from the match's own records as the chat is read, so nothing is stored twice.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from django.db import transaction
from django.utils import timezone

from league.domain.engine import Status
from league.domain.errors import InvalidAction, NotAllowed, StaleAction
from league.models import (
    ChatMessage,
    ChatScope,
    DraftAction,
    Match,
    MatchParticipant,
    MatchTransition,
    Player,
    PlayerSwap,
    SubRequest,
)
from league.models.matches import DraftActionKind, MatchKind, Source
from league.models.subs import SubStatus
from league.models.swaps import SwapStatus
from league.models.web import CHAT_MAX_CHARS
from league.services.boards import team_name

HISTORY = 100  # Lines a chat shows, the latest.
RATE_COUNT = 5  # Messages a player may send in a match...
RATE_WINDOW = timedelta(seconds=10)  # ...within this long.
SLOW_DOWN = "Slow down a little."

LOBBY_OPEN = frozenset({Status.CAPTAIN_PHASE, Status.CAPTAIN_CHECKIN, Status.PLAYER_DRAFT})
TEAM_OPEN = frozenset(
    {Status.COINFLIP, Status.CHAMPION_DRAFT, Status.LOBBY_CODE, Status.IN_PROGRESS}
)
TEAM_READ_ONLY = frozenset({Status.AWAITING_CONFIRMATION, Status.DISPUTED})
SCRIM_TEAM_OPEN = frozenset({Status.CHAMPION_DRAFT})
TEAM_CLOSED = "Team chat closed when the game ended."

type Kind = Literal["lobby", "team"]


@dataclass(frozen=True, slots=True)
class Room:
    """The chat a match has now: whose it is, and whether it takes new messages."""

    kind: Kind
    open: bool
    closed_reason: str | None = None


def room(kind: str, status: str) -> Room | None:
    """The chat this match shows its players now, if any."""
    if kind == MatchKind.SCRIM:
        return Room("team", True) if status in SCRIM_TEAM_OPEN else None
    if status in LOBBY_OPEN:
        return Room("lobby", True)
    if status in TEAM_OPEN:
        return Room("team", True)
    if status in TEAM_READ_ONLY:
        return Room("team", False, TEAM_CLOSED)
    return None


def scope_of(kind: Kind, team: str) -> ChatScope | None:
    """Where a player's messages go in this room: the lobby, or their own team's chat."""
    if kind == "lobby":
        return ChatScope.LOBBY
    if team == "A":
        return ChatScope.TEAM_A
    if team == "B":
        return ChatScope.TEAM_B
    return None


def clean(body: str) -> str:
    """Control characters out, newlines kept (a Windows line break becomes a plain one), and the
    ends trimmed."""
    kept = "".join(char for char in body if char == "\n" or unicodedata.category(char) != "Cc")
    return kept.strip()


@transaction.atomic
def send(match_id: int, player: Player, body: str) -> ChatMessage:
    """Post a message to the chat this player can see in the match now."""
    match = Match.objects.lock(match_id)
    current = room(match.kind, match.status)
    if current is None:
        raise StaleAction("There's no chat in this match right now.")
    if not current.open:
        raise StaleAction(current.closed_reason or "This chat is closed.")
    seat = match.participants.filter(player=player, removed_reason="").first()
    scope = scope_of(current.kind, seat.team) if seat is not None else None
    if scope is None:
        raise NotAllowed("Only the players in this match can chat here.")
    text = clean(body)
    if not text:
        raise InvalidAction("Write something first.")
    if len(text) > CHAT_MAX_CHARS:
        raise InvalidAction(f"Keep it to {CHAT_MAX_CHARS} characters.")
    # `created_at` is stamped with Django's clock, so the window is measured on the same one.
    since = timezone.now() - RATE_WINDOW
    recent = ChatMessage.objects.filter(match=match, player=player, created_at__gt=since)
    if recent.count() >= RATE_COUNT:
        raise InvalidAction(SLOW_DOWN)
    message = ChatMessage.objects.create(match=match, scope=scope, player=player, body=text)
    match.bump()  # Publishes the match: the chat's readers refresh.
    return message


def latest(match_id: int, scope: ChatScope) -> list[ChatMessage]:
    """The chat's last lines, oldest first, with their senders."""
    rows = (
        ChatMessage.objects.filter(match_id=match_id, scope=scope)
        .select_related("player")
        .order_by("-id")[:HISTORY]
    )
    return list(reversed(rows))


# --- System lines -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SystemLine:
    """Something that happened, shown between the messages. `key` is unique within a chat."""

    key: str
    body: str
    at: datetime


def system_lines(match_id: int, scope: ChatScope) -> list[SystemLine]:
    """What happened in the match that this chat's readers should see, oldest first, the last
    `HISTORY`. The lobby chat: the captains and each player pick. A team chat: the start of the
    hero draft, every ban and pick, swaps, subs once the teams are set, and the game starting.
    Bans, picks and swaps are on the board for everyone, so both teams' chats get them."""
    captains = {
        row.team: row.player.display_name
        for row in MatchParticipant.objects.filter(
            match_id=match_id, is_captain=True, is_active=True
        ).select_related("player")
    }

    def side(team: str) -> str:
        return team_name(captains[team]) if team in captains else "A team"

    transitions = list(MatchTransition.objects.filter(match_id=match_id).order_by("id"))
    # When the teams were set: the lobby chat's events are before it, the team chats' after.
    teams_set = next(
        (t.created_at for t in transitions if t.to_status in TEAM_OPEN | SCRIM_TEAM_OPEN), None
    )
    lobby = scope == ChatScope.LOBBY
    lines: list[SystemLine] = []

    for t in transitions:
        if lobby and t.to_status == Status.PLAYER_DRAFT and {"A", "B"} <= captains.keys():
            body = f"{captains['A']} and {captains['B']} are the captains. The player draft is on."
            lines.append(SystemLine(f"t{t.pk}", body, t.created_at))
        elif not lobby and t.to_status == Status.CHAMPION_DRAFT:
            lines.append(SystemLine(f"t{t.pk}", "The hero draft is on.", t.created_at))
        elif not lobby and t.to_status == Status.IN_PROGRESS:
            lines.append(SystemLine(f"t{t.pk}", "The game is on. Good luck.", t.created_at))

    actions = DraftAction.objects.filter(match_id=match_id).select_related(
        "actor", "target_player", "target_champion"
    )
    for a in actions.order_by("step_index"):
        timed_out = a.source == Source.TIMEOUT
        who = a.actor.display_name if a.actor and not timed_out else side(a.team)
        if a.action == DraftActionKind.PLAYER_PICK and lobby and a.target_player:
            picked = a.target_player.display_name
            body = (
                f"Time ran out: {picked} goes to {side(a.team)}."
                if timed_out
                else f"{who} picked {picked}."
            )
        elif a.action != DraftActionKind.PLAYER_PICK and not lobby and a.target_champion:
            hero = a.target_champion.name
            verb = "banned" if a.action == DraftActionKind.BAN else "picked"
            if timed_out:
                body = f"Time ran out, so {side(a.team)} {verb} a random hero: {hero}."
            elif a.random_choice:
                body = f"{who} {verb} a random hero: {hero}."
            else:
                body = f"{who} {verb} {hero}."
        else:
            continue
        lines.append(SystemLine(f"d{a.pk}", body, a.created_at))

    if not lobby:
        swaps = PlayerSwap.objects.filter(match_id=match_id, status=SwapStatus.ACCEPTED)
        for swap in swaps.select_related("give", "take"):
            if swap.resolved_at is None:
                continue
            body = f"{swap.give.display_name} and {swap.take.display_name} swapped teams."
            lines.append(SystemLine(f"w{swap.pk}", body, swap.resolved_at))

    subs = SubRequest.objects.filter(match_id=match_id, status=SubStatus.FILLED)
    for sub in subs.select_related("leaving", "filled_by"):
        if sub.resolved_at is None or sub.filled_by is None:
            continue
        before_teams = teams_set is None or sub.resolved_at < teams_set
        if before_teams != lobby:
            continue
        body = f"{sub.filled_by.display_name} came in for {sub.leaving.display_name}."
        lines.append(SystemLine(f"s{sub.pk}", body, sub.resolved_at))

    lines.sort(key=lambda line: line.at)
    return lines[-HISTORY:]
