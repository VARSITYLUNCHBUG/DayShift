"""Who may use staff commands. A member holds every area their roles are granted; the server
owner and Administrators hold every area, so a fresh server is never locked out."""

from __future__ import annotations

from typing import Any

import discord
from discord import Interaction

from bot.db import db
from league.domain.errors import NotAllowed
from league.models import Community, Match
from league.models.permissions import Area
from league.services import permissions


def is_manager(interaction: Interaction[Any]) -> bool:
    """The server owner or an Administrator: the only people who can change grants."""
    user = interaction.user
    if not isinstance(user, discord.Member):
        return False
    guild = interaction.guild
    if guild is not None and guild.owner_id == user.id:
        return True
    return bool(user.guild_permissions.administrator)


async def member_areas(interaction: Interaction[Any], community: Community) -> frozenset[Area]:
    user = interaction.user
    if not isinstance(user, discord.Member):
        return frozenset()  # Outside a server.
    if is_manager(interaction):
        return permissions.ALL_AREAS
    role_ids = [role.id for role in user.roles]
    return await db(permissions.areas_for_roles, community.pk, role_ids)


async def has_area(interaction: Interaction[Any], community: Community, *areas: Area) -> bool:
    """Whether the member holds any of these areas."""
    return not (await member_areas(interaction, community)).isdisjoint(areas)


def _labels(areas: tuple[Area, ...]) -> str:
    names = [area.label for area in areas]
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} or {names[-1]}"


async def require_area(interaction: Interaction[Any], community: Community, *areas: Area) -> None:
    """Refuse unless the member holds at least one of these areas."""
    if not await has_area(interaction, community, *areas):
        raise NotAllowed(f"You don't have permission to do that. It needs {_labels(areas)} access.")


def community_of_match(match_id: int) -> Community:
    return Match.objects.select_related("community").get(pk=match_id).community


async def require_area_for_match(
    interaction: Interaction[Any], match_id: int, *areas: Area
) -> Community:
    community = await db(community_of_match, match_id)
    await require_area(interaction, community, *areas)
    return community


def require_manager(interaction: Interaction[Any]) -> None:
    if not is_manager(interaction):
        raise NotAllowed("Only the server owner and Administrators can do that.")
