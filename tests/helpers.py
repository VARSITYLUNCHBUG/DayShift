"""Drive a match through its phases using only public service calls."""

from __future__ import annotations

from league.domain.draft_plan import build_plan, team_for_role
from league.domain.engine import (
    ARCHMOTHER,
    FIRST_PICK,
    HIDDEN_KING,
    LAST_PICK,
    Status,
)
from league.models import Community, Match, Player
from league.models.matches import MatchKind
from league.services import draft, lobby, queue, results
from league.services.results import ImageRef


def image(number: int = 1) -> ImageRef:
    return ImageRef(
        sha256=f"{number:064x}",
        archive_channel_id=1,
        archive_message_id=1000 + number,
        attachment_id=2000 + number,
        extension="png",
    )


def fresh(match: Match) -> Match:
    return Match.objects.select_related("mode_version", "season", "community").get(pk=match.pk)


def ready_all(match: Match) -> Match:
    match = fresh(match)
    if match.status == Status.READY_CHECK:
        for participant in match.participants.filter(is_active=True, ready_at__isnull=True):
            lobby.mark_ready(match.pk, participant.player)
    return fresh(match)


def vote_only(match: Match) -> Match:
    """Settle the captain vote: everyone votes for the first two players by ID. The captains
    still have to check in.

    With the votes tied, skill, then games, then the seed decide who captains team A.
    """
    match = fresh(match)
    if match.status == Status.CAPTAIN_PHASE:
        active = list(match.participants.filter(is_active=True).order_by("id"))
        chosen = [active[0].player_id, active[1].player_id]
        for participant in active:
            if fresh(match).status != Status.CAPTAIN_PHASE:
                break
            lobby.cast_captain_votes(match.pk, participant.player, chosen)
    return fresh(match)


def check_in_captains(match: Match) -> Match:
    """Both captains press I'm here, which starts the player draft."""
    match = fresh(match)
    if match.status == Status.CAPTAIN_CHECKIN:
        for participant in match.participants.filter(
            is_active=True, is_captain=True, checked_in_at__isnull=True
        ):
            lobby.check_in(match.pk, participant.player)
    return fresh(match)


def vote_captains(match: Match) -> Match:
    """Settle the captain vote and check the captains in: the player draft is on."""
    return check_in_captains(vote_only(match))


def settle_coinflip_for(match: Match, hk_team: str = "A") -> Match:
    """Play the captain coinflip so `hk_team` is The Hidden King and bans and picks first."""
    match = fresh(match)
    if match.status != Status.COINFLIP:
        return match
    winner = match.coinflip_winner
    loser = "B" if winner == "A" else "A"
    if match.kind != MatchKind.SCRIM:
        # Ranked: the winner picks a side, and the Hidden King bans and picks first.
        choice = HIDDEN_KING if winner == hk_team else ARCHMOTHER
        draft.choose_coinflip(match.pk, match.captain_of(winner).player, choice)
        return fresh(match)
    side = HIDDEN_KING if winner == hk_team else ARCHMOTHER
    draft.choose_coinflip(match.pk, match.captain_of(winner).player, side)
    order = FIRST_PICK if loser == hk_team else LAST_PICK
    draft.choose_coinflip(match.pk, match.captain_of(loser).player, order)
    return fresh(match)


def run_player_draft(match: Match) -> Match:
    match = fresh(match)
    while match.status == Status.PLAYER_DRAFT:
        step = build_plan(match.mode)[match.step_index]
        team = team_for_role(step.role, match.player_first_pick)
        captain = match.captain_of(team).player
        target = match.participants.filter(is_active=True, team="").order_by("id").first()
        draft.pick_player(match.pk, captain, match.step_index, target.player_id)
        match = fresh(match)
    return match


def acting_captain(match: Match) -> Player:
    """The captain whose turn it is, in the player draft or the champion draft."""
    match = fresh(match)
    step = build_plan(match.mode)[match.step_index]
    first = match.player_first_pick if step.action == "player_pick" else match.champion_first_pick
    return match.captain_of(team_for_role(step.role, first)).player


def confirm_teams(match: Match) -> Match:
    """Both captains press Teams ready: the hero draft starts."""
    match = fresh(match)
    for team in ("A", "B"):
        if match.status == Status.TEAM_CONFIRM:
            draft.confirm_teams(match.pk, match.captain_of(team).player)
            match = fresh(match)
    return match


def to_champion_draft(match: Match) -> Match:
    """From the ready check to the first champion draft step."""
    return confirm_teams(settle_coinflip_for(run_player_draft(vote_captains(ready_all(match)))))


def run_champion_draft(match: Match) -> Match:
    match = confirm_teams(settle_coinflip_for(match))
    while match.status == Status.CHAMPION_DRAFT:
        step = build_plan(match.mode)[match.step_index]
        team = team_for_role(step.role, match.champion_first_pick)
        captain = match.captain_of(team).player
        champion = draft.available_champions(match)[0]
        draft.choose_champion(match.pk, captain, match.step_index, champion)
        match = fresh(match)
    return match


def fail_api_lobby(match: Match) -> Match:
    """deadlock-api couldn't make the lobby, so the host is asked for a code."""
    match = fresh(match)
    if match.status == Status.LOBBY_CODE and not match.api_lobby_failed:
        draft.api_lobby_failed(match.pk, "test: no API")
    return fresh(match)


def to_in_progress(match: Match) -> Match:
    match = fail_api_lobby(run_champion_draft(to_champion_draft(match)))
    draft.submit_lobby_code(match.pk, match.lobby_code_host, "ABC123")
    return fresh(match)


def finish(match: Match, winner: str = "A", number: int = 1) -> Match:
    """Report and confirm a result, from a match already in progress."""
    match = fresh(match)
    first = match.captain_of("A").player
    second = match.captain_of("B").player
    results.submit_report(match.pk, first, winner, image(number))
    results.confirm(match.pk, second)
    return fresh(match)


def play_full_match(community: Community, players: list[Player], winner: str, number: int) -> Match:
    for player in players:
        queue.join(community.pk, player)
    match = Match.objects.filter(community=community).order_by("-id").first()
    return finish(to_in_progress(match), winner, number)
