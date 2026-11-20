"""The match chats on the web: the lobby chat while the teams are being made, then each team's own.

There is one chat a player can see at a time, chosen from the match's status:

- The lobby chat, for everyone on the roster, is open in the captain vote, the check-in and the
  player draft.
- Each team's chat, for that team's roster only, is open from the coinflip until the game ends,
  then read-only until the result is settled. Once the match is over there's none.
- A scrim has no lobby chat; its teams' chats are open during its hero draft.

A player who is subbed out leaves the roster, and with it the chat. Messages are plain text and
web-only: the Discord bot never shows them.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

from django.db import transaction
from django.utils import timezone

from league.domain.engine import Status
from league.domain.errors import InvalidAction, NotAllowed, StaleAction
from league.models import ChatMessage, ChatScope, Match, Player
from league.models.matches import MatchKind
from league.models.web import CHAT_MAX_CHARS

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
