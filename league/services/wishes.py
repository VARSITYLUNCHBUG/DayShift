"""Hero wishes: up to three heroes a player would like to play in their match, ranked.

Only the player's own team sees them (the captain, to draft with, and the teammates), and only on
the web: the Discord board never shows them. A player sets them from the coinflip until the hero
draft ends; after that they stay on show to the team, read-only, until the match ends.

Wishes belong to the player, not the seat. A player swapped to the other team takes them along,
since each team's view is drawn from whoever is on it now, and a sub coming in starts with none.
Banned and taken heroes may be wished for: the page strikes them through.
"""

from __future__ import annotations

from collections.abc import Sequence

from django.db import transaction

from league.domain.engine import Status
from league.domain.errors import InvalidAction, NotAllowed, StaleAction
from league.models import Champion, HeroWish, Match, Player
from league.models.matches import MatchKind
from league.models.web import WISHES_PER_PLAYER

# While the teams are known and the heroes not yet all chosen.
WISHABLE = frozenset({Status.COINFLIP, Status.CHAMPION_DRAFT})
# Wishes stay on show, read-only, after the hero draft, until the match is over.
SHOWN = frozenset(
    {
        Status.COINFLIP,
        Status.CHAMPION_DRAFT,
        Status.LOBBY_CODE,
        Status.IN_PROGRESS,
        Status.AWAITING_CONFIRMATION,
        Status.DISPUTED,
    }
)


def can_wish(kind: str, status: str) -> bool:
    """Whether a match's players may change their wishes now. Scrims have no wishes: their
    captains aren't active players, and nobody else is on the roster."""
    return kind == MatchKind.RANKED and status in WISHABLE


def shown(kind: str, status: str) -> bool:
    return kind == MatchKind.RANKED and status in SHOWN


@transaction.atomic
def set_wishes(match_id: int, player: Player, champion_ids: Sequence[int]) -> list[HeroWish]:
    """Replace the player's wishes with these heroes, most wanted first. An empty list clears
    them."""
    match = Match.objects.lock(match_id)
    if not can_wish(match.kind, match.status):
        raise StaleAction("Hero wishes can only be changed from the coinflip to the hero draft.")
    if not match.participants.filter(player=player, is_active=True).exclude(team="").exists():
        raise NotAllowed("Only the players on a team in this match can wish for heroes.")
    wanted = list(champion_ids)
    if len(wanted) > WISHES_PER_PLAYER:
        raise InvalidAction(f"Wish for up to {WISHES_PER_PLAYER} heroes.")
    if len(set(wanted)) != len(wanted):
        raise InvalidAction("Wish for each hero only once.")
    enabled = set(
        Champion.objects.filter(pk__in=wanted, is_enabled=True).values_list("pk", flat=True)
    )
    pool = set(match.champion_pool)
    if any(pk not in enabled or pk not in pool for pk in wanted):
        raise InvalidAction("That hero isn't in this draft.")
    current = list(
        HeroWish.objects.filter(match=match, player=player)
        .order_by("rank")
        .values_list("champion_id", flat=True)
    )
    if current == wanted:
        return list(HeroWish.objects.filter(match=match, player=player).order_by("rank"))
    HeroWish.objects.filter(match=match, player=player).delete()
    rows = HeroWish.objects.bulk_create(
        HeroWish(match=match, player=player, champion_id=champion_id, rank=rank)
        for rank, champion_id in enumerate(wanted, 1)
    )
    match.bump()  # Publishes the match: the team's pages refresh.
    return rows


def of_players(match_id: int, player_ids: Sequence[int]) -> list[HeroWish]:
    """These players' wishes in the match, by player as given, then rank."""
    order = {player_id: index for index, player_id in enumerate(player_ids)}
    rows = HeroWish.objects.filter(match_id=match_id, player_id__in=order)
    return sorted(rows, key=lambda row: (order[row.player_id], row.rank))
