"""Fast ways to the states tests start from, for tests about what happens next.

`tests.helpers` plays a match through every phase with public service calls, which is what the
flow tests are about: about 60 clicks and 1,600 queries a match. A test about results, ratings,
corrections or standing only needs matches that were played, so it builds them here instead:
the lobby pops through the real queue, then the ready check, the captain vote, both drafts and
the coinflip are written as they would have ended, and the game starts through the same
`_start_game` a lobby code goes through. Reporting and confirming then run the real code.
"""

from __future__ import annotations

from django.db import transaction

from league.domain.engine import HIDDEN_KING, Status
from league.models import Community, Match, MatchParticipant, Player
from league.models.matches import Source
from league.services import draft, queue
from league.services.common import now
from tests.helpers import finish, fresh


def in_progress(community: Community, players: list[Player]) -> Match:
    """A ranked match whose game is on: `players[:6]` on team A, the rest on B, and the first of
    each team its captain. Team A is the Hidden King and picked first."""
    assert len(players) == 12
    for player in players:
        queue.join(community.pk, player)
    popped = Match.objects.filter(community=community).order_by("-id").first()
    assert popped is not None and popped.status == Status.READY_CHECK
    with transaction.atomic():
        match = Match.objects.lock(popped.pk)
        stamp = now()
        seats = {p.player_id: p for p in match.participants.filter(is_active=True)}
        for index, player in enumerate(players):
            seat = seats[player.pk]
            seat.ready_at = stamp
            seat.team = "A" if index < 6 else "B"
            seat.is_captain = index in (0, 6)
            seat.checked_in_at = stamp if seat.is_captain else None
            seat.draft_pick_number = None if seat.is_captain else index
        MatchParticipant.objects.bulk_update(
            seats.values(), ["ready_at", "team", "is_captain", "checked_in_at", "draft_pick_number"]
        )
        match.player_first_pick = match.champion_first_pick = match.hidden_king_team = "A"
        match.coinflip_winner = "A"
        match.coinflip_winner_choice = HIDDEN_KING
        match.lobby_code_host = players[0]
        match.status = Status.LOBBY_CODE
        match.save()
        draft._start_game(match, "ABC123", source=Source.SYSTEM, actor=None)
    return fresh(match)


def played(community: Community, players: list[Player], winner: str, number: int) -> Match:
    """A completed match, reported and confirmed: `tests.helpers.play_full_match`, fast."""
    return finish(in_progress(community, players), winner, number)
