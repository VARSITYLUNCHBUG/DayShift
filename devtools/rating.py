"""Setting a fake player's rating, always through the ledger so check_ledger stays clean."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import cast

from django.db import transaction

from devtools.errors import BadRequest
from league.domain.ratings_algo import d6
from league.models import Player, Season
from league.services import ratings


def set_rating(season: Season, player: Player, rating: int) -> int:
    """Seed a player to an exact shown rating. Their uncertainty goes back to the season's start,
    so mu = rating / display_scale + 3 sigma. Returns the rating they got."""
    if rating < 0:
        raise BadRequest("A rating can't be below 0.")
    params = ratings.params_for(season)
    sigma = d6(params["sigma"])
    mu = d6(Decimal(rating) / Decimal(str(params["display_scale"])) + 3 * sigma)
    # Seeding takes a band or a mu; any number goes through d6, so a Decimal is fine.
    event = ratings.seed_player(
        season, player, cast(int, mu), actor=None, reason=f"dev: rating {rating}"
    )
    return event.rating_after


def seed_ratings(season: Season, values: Sequence[tuple[Player, int]]) -> None:
    """Seed several at once. The season row lock serialises the ledger's run numbering."""
    with transaction.atomic():
        Season.objects.select_for_update().get(pk=season.pk)
        for player, value in values:
            set_rating(season, player, value)
