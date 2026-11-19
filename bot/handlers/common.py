from __future__ import annotations

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


async def community_of(interaction: Interaction[Any]) -> Community:
    guild_id = interaction.guild_id
    community = await db(community_service.get, guild_id) if guild_id else None
    if community is None:
        raise InvalidAction("This server isn't set up yet. An admin needs to run /setup.")
    return community
