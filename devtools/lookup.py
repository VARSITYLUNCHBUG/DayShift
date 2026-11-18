"""Finding the community, matches, players and champions a request names."""

from __future__ import annotations

from django.db.models import Q

from devtools.errors import BadRequest, Conflict, NotFound
from league.domain.draft_plan import build_plan, team_for_role
from league.domain.engine import Status
from league.models import Champion, Community, Match, Player, QueueEntry, Season, SubOffer
from league.models.subs import UNRESOLVED, OfferStatus
from league.services.common import captain_of, mode_of


def community_or_none() -> Community | None:
    """The dev league: there is one community per dev database."""
    return Community.objects.select_related("active_mode").order_by("pk").first()


def community() -> Community:
    row = community_or_none()
    if row is None:
        raise Conflict("There is no community yet. Run manage.py dev_seed, or POST reset.")
    return row


def open_season(league: Community) -> Season:
    season = Season.objects.filter(community=league, ended_at__isnull=True).first()
    if season is None:
        raise Conflict("No season is open.")
    return season


def match(ref: str | int) -> Match:
    query = Match.objects.select_related("mode_version", "season", "community")
    row = query.order_by("-pk").first() if ref == "latest" else query.filter(pk=int(ref)).first()
    if row is None:
        raise NotFound(f"No match {ref}.")
    return row


def player(player_id: int | str) -> Player:
    try:
        pk = int(player_id)
    except (TypeError, ValueError) as exc:
        raise BadRequest(f"Not a player id: {player_id!r}.") from exc
    row = Player.objects.filter(pk=pk).first()
    if row is None:
        raise NotFound(f"No player {pk}.")
    return row


def champion(ref: str | int) -> Champion:
    """A champion by id, slug, name or alias."""
    text = str(ref).strip()
    query = Champion.objects.all()
    row = (
        query.filter(pk=int(text)).first()
        if text.isdigit()
        else query.filter(Q(slug=text.lower()) | Q(name__iexact=text)).first()
        or query.filter(aliases__contains=[text.lower()]).first()
    )
    if row is None:
        raise BadRequest(f"No champion {ref!r}.")
    return row


def acting_captain(row: Match) -> Player:
    """The captain whose turn it is in the player draft or the champion draft."""
    step = build_plan(mode_of(row))[row.step_index]
    first = row.player_first_pick if step.action == "player_pick" else row.champion_first_pick
    return captain_of(row, team_for_role(step.role, first)).player


def _nth(players: list[Player], index: str, what: str) -> Player:
    try:
        number = int(index)
    except ValueError as exc:
        raise BadRequest(f"Not a number in {what}:{index}.") from exc
    if not 1 <= number <= len(players):
        raise BadRequest(f"There is no {what} number {number} (there are {len(players)}).")
    return players[number - 1]


def _reported(row: Match) -> set[int]:
    return set(row.submissions.values_list("captain_id", flat=True))


def select_player(row: Match, ref: int | str) -> Player:
    """A player id, or a selector such as `captain:A` (see README, act)."""
    if isinstance(ref, int) or str(ref).isdigit():
        return player(ref)
    kind, _, arg = str(ref).partition(":")
    active = [p.player for p in row.participants.filter(is_active=True).select_related("player")]
    if kind == "captain" and arg in {"A", "B"}:
        return captain_of(row, arg).player
    if kind == "acting":
        if row.status not in {Status.PLAYER_DRAFT, Status.CHAMPION_DRAFT}:
            raise Conflict(f"Nobody is drafting: the match is {row.status}.")
        return acting_captain(row)
    if kind == "host":
        if row.lobby_code_host is None:
            raise Conflict("The match has no lobby code host yet.")
        return row.lobby_code_host
    if kind == "other_captain":
        reported = _reported(row)
        for team in ("A", "B"):
            captain = captain_of(row, team).player
            if captain.pk not in reported:
                return captain
        raise Conflict("Both captains have already reported.")
    if kind == "participant":
        return _nth(active, arg, "participant")
    if kind == "non_captain":
        captains = set(
            row.participants.filter(is_captain=True, is_active=True).values_list(
                "player_id", flat=True
            )
        )
        return _nth([p for p in active if p.pk not in captains], arg, "non_captain")
    if kind == "queued":
        entries = QueueEntry.objects.select_related("player").order_by("joined_at", "pk")
        return _nth([entry.player for entry in entries], arg, "queued")
    if kind == "offered":
        offer = (
            SubOffer.objects.filter(request__match=row, status=OfferStatus.PENDING)
            .select_related("player")
            .order_by("-pk")
            .first()
        )
        if offer is None:
            raise Conflict("No sub offer is pending for this match.")
        return offer.player
    if kind == "requester":
        request = row.sub_requests.filter(status__in=UNRESOLVED).order_by("-pk").first()
        if request is None or request.requested_by is None:
            raise Conflict("No sub request by a player is open for this match.")
        return request.requested_by
    raise BadRequest(f"Unknown player selector {ref!r}.")
