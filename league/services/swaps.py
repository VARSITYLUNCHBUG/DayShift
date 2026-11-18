"""Captains swapping two players between their teams, after the player draft.

One captain offers one of their players for one of the other team's. The other captain accepts
and the two change teams, voice channels included; declines; or lets it lapse. Captains stay
where they are. Swaps are open from the coinflip until the game starts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db import transaction

from league.domain.engine import Status
from league.domain.errors import InvalidAction, NotAllowed, StaleAction
from league.models import Match, MatchParticipant, Player, PlayerSwap
from league.models.swaps import SwapStatus
from league.services.common import (
    active_participants,
    add_effect,
    bump,
    lock_match,
    now,
    render_board,
    require_not_on_hold,
)

# The player draft is over and the game hasn't started: teams can still change.
SWAPPABLE = frozenset({Status.COINFLIP, Status.CHAMPION_DRAFT, Status.LOBBY_CODE})
ANSWER_SECONDS = 60


def pending(match: Match) -> PlayerSwap | None:
    return (
        PlayerSwap.objects.filter(match=match, status=SwapStatus.PENDING)
        .select_related("requested_by", "give", "take")
        .first()
    )


def _require_swappable(match: Match) -> None:
    if match.status not in SWAPPABLE:
        raise StaleAction("Teams can only be swapped between the player draft and the game.")


def _captain(match: Match, player: Player) -> MatchParticipant:
    row = active_participants(match).filter(player=player, is_captain=True).first()
    if row is None:
        raise NotAllowed("Only a captain can swap players.")
    return row


def _other(team: str) -> str:
    return "B" if team == "A" else "A"


@dataclass(frozen=True, slots=True)
class SwapChoice:
    player_id: int
    name: str


def _choices(match: Match, team: str) -> list[SwapChoice]:
    rows = active_participants(match).filter(team=team, is_captain=False).order_by("id")
    return [SwapChoice(row.player_id, row.player.display_name) for row in rows]


def own_options(match_id: int, captain: Player) -> list[SwapChoice]:
    """Who this captain can offer: their own players, not themself."""
    match = Match.objects.get(pk=match_id)
    _require_swappable(match)
    if pending(match) is not None:
        raise InvalidAction("A swap is already waiting for an answer.")
    return _choices(match, _captain(match, captain).team)


def their_options(match_id: int, captain: Player) -> list[SwapChoice]:
    """Who this captain can ask for: the other team's players, not their captain."""
    match = Match.objects.get(pk=match_id)
    _require_swappable(match)
    return _choices(match, _other(_captain(match, captain).team))


@transaction.atomic
def propose(match_id: int, captain: Player, give_id: int, take_id: int) -> PlayerSwap:
    match = lock_match(match_id)
    _require_swappable(match)
    require_not_on_hold(match)
    own = _captain(match, captain)
    if pending(match) is not None:
        raise InvalidAction("A swap is already waiting for an answer.")
    give = active_participants(match).filter(player_id=give_id, team=own.team).first()
    take = active_participants(match).filter(player_id=take_id, team=_other(own.team)).first()
    if give is None or take is None or give.is_captain or take.is_captain:
        raise InvalidAction("Choose one of your players and one of theirs. Captains stay put.")
    moment = now()
    swap = PlayerSwap.objects.create(
        match=match,
        requested_by=captain,
        give=give.player,
        take=take.player,
        deadline_at=moment + timedelta(seconds=ANSWER_SECONDS),
        created_at=moment,
    )
    other = active_participants(match).filter(team=_other(own.team), is_captain=True).first()
    if other is not None:
        add_effect(
            match.community,
            "ping",
            {
                "user_ids": [other.player.discord_user_id],
                "text": f"{captain.display_name} offers **{give.player.display_name}** for "
                f"**{take.player.display_name}**. Accept or decline on the board.",
            },
            match=match,
        )
    bump(match)
    render_board(match)
    return swap


@transaction.atomic
def answer(match_id: int, captain: Player, swap_id: int, accept: bool) -> PlayerSwap:
    """The other captain accepts or declines. Either captain can decline, so the one who asked
    can also withdraw it."""
    match = lock_match(match_id)
    swap = pending(match)
    if swap is None or swap.pk != swap_id:
        raise StaleAction("That swap has already been answered.")
    _require_swappable(match)
    _captain(match, captain)
    if not accept:
        _close(swap, SwapStatus.DECLINED, captain)
        bump(match)
        render_board(match)
        return swap
    if captain.pk == swap.requested_by_id:
        raise NotAllowed("The other captain has to accept this.")
    require_not_on_hold(match)
    give = active_participants(match).filter(player=swap.give).first()
    take = active_participants(match).filter(player=swap.take).first()
    if give is None or take is None or give.team == take.team or not give.team:
        _close(swap, SwapStatus.EXPIRED, None)
        bump(match)
        render_board(match)
        raise StaleAction("Those players aren't on opposite teams any more.")
    give.team, take.team = take.team, give.team
    give.save(update_fields=["team"])
    take.save(update_fields=["team"])
    _close(swap, SwapStatus.ACCEPTED, captain)
    add_effect(
        match.community,
        "swap_team_voice",
        {
            "moves": [
                {"discord_user_id": give.player.discord_user_id, "team": give.team},
                {"discord_user_id": take.player.discord_user_id, "team": take.team},
            ]
        },
        match=match,
    )
    add_effect(
        match.community,
        "ping_lobby",
        {
            "text": f"Swapped: **{give.player.display_name}** and "
            f"**{take.player.display_name}** have changed teams."
        },
        match=match,
    )
    bump(match)
    render_board(match)
    return swap


def _close(swap: PlayerSwap, status: str, actor: Player | None) -> None:
    swap.status = status
    swap.resolved_by = actor
    swap.resolved_at = now()
    swap.save(update_fields=["status", "resolved_by", "resolved_at"])


def tick(moment: datetime) -> int:
    """Unanswered swaps lapse, and so does any left over when the match moved on."""
    fired = 0
    due = PlayerSwap.objects.filter(status=SwapStatus.PENDING, deadline_at__lte=moment)
    for swap_id, match_id in due.values_list("pk", "match_id"):
        with transaction.atomic():
            match = lock_match(match_id)
            swap = PlayerSwap.objects.get(pk=swap_id)
            if swap.status != SwapStatus.PENDING:
                continue
            _close(swap, SwapStatus.EXPIRED, None)
            bump(match)
            render_board(match)
            fired += 1
    return fired
