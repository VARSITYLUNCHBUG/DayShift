from __future__ import annotations

from collections.abc import Callable
from typing import Any

from discord import Interaction

from bot.db import db
from league.domain.errors import InvalidAction
from league.models import Community, Player
from league.services import community as community_service


async def actor(interaction: Interaction[Any]) -> Player:
    """The Player for whoever clicked. First interaction creates the row."""
    user = interaction.user
    return await db(Player.objects.from_discord, user.id, user.display_name)


def _checked_player(
    user_id: int, display_name: str, check: Callable[[int, Player], object], match_id: int
) -> Player:
    player = Player.objects.from_discord(user_id, display_name)
    check(match_id, player)
    return player


async def checked_actor(
    interaction: Interaction[Any], check: Callable[[int, Player], object], match_id: int
) -> Player:
    """The Player who clicked, after `check(match_id, player)` passes, in one trip to the
    database thread. For buttons that open a form: a form must be the first response, inside
    Discord's 3 seconds, and each trip can queue behind other work on that one thread."""
    user = interaction.user
    return await db(_checked_player, user.id, user.display_name, check, match_id)


async def community_of(interaction: Interaction[Any]) -> Community:
    guild_id = interaction.guild_id
    community = await db(community_service.get, guild_id) if guild_id else None
    if community is None:
        raise InvalidAction("This server isn't set up yet. An admin needs to run /setup.")
    return community
