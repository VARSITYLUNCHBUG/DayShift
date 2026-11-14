"""/permissions grant|revoke|list: which roles hold which staff areas.

Only the server owner and Administrators can change grants, and they hold every area
themselves. Discord shows this one command to Administrators only; every other staff command is
visible to all and checked when it runs, because Discord can't show commands by our grants.
"""

from __future__ import annotations

from typing import Any

import discord
from discord import Interaction, app_commands

from bot.commands.setup import sync_staff_access
from bot.db import db
from bot.handlers.common import community_of
from bot.handlers.permissions import require_manager
from bot.routing import guarded, reply
from league.domain.errors import InvalidAction
from league.models import Community
from league.models.permissions import AREA_SCOPE, Area
from league.services import permissions

EVERY_AREA = "all"
AREA_CHOICES = [
    *(app_commands.Choice(name=area.label, value=area.value) for area in Area),
    app_commands.Choice(name="Every area", value=EVERY_AREA),
]

permissions_group = app_commands.Group(
    name="permissions",
    description="Which roles can use which staff commands",
    guild_only=True,
    default_permissions=discord.Permissions(administrator=True),
)


def _areas(choice: app_commands.Choice[str]) -> list[Area]:
    return list(Area) if choice.value == EVERY_AREA else [Area(choice.value)]


def _names(areas: list[Area]) -> str:
    return ", ".join(area.label for area in areas)


async def _start(interaction: Interaction[Any], role: discord.Role | None = None) -> Community:
    await interaction.response.defer(ephemeral=True, thinking=True)
    community = await community_of(interaction)
    require_manager(interaction)
    if role is not None and (role.is_default() or role.guild.id != interaction.guild_id):
        raise InvalidAction("Choose a role from this server, other than @everyone.")
    return community


async def _sync(interaction: Interaction[Any], community: Community) -> None:
    if interaction.guild is not None:
        await sync_staff_access(interaction.guild, community.pk)


@permissions_group.command(name="grant", description="Let a role use an area's staff commands")
@app_commands.describe(role="The staff role", area="What it can do")
@app_commands.choices(area=AREA_CHOICES)
async def permissions_grant(
    interaction: Interaction[Any], role: discord.Role, area: app_commands.Choice[str]
) -> None:
    async def run() -> None:
        community = await _start(interaction, role)
        areas = _areas(area)
        new = await db(permissions.grant, community.pk, role.id, areas, interaction.user.id)
        await _sync(interaction, community)
        if not new:
            await reply(interaction, f"{role.mention} already has {_names(areas)}.")
            return
        await reply(interaction, f"{role.mention} can now use {_names(new)}.")

    await guarded(interaction, run)


@permissions_group.command(name="revoke", description="Take an area's staff commands from a role")
@app_commands.describe(role="The staff role", area="What it should no longer do")
@app_commands.choices(area=AREA_CHOICES)
async def permissions_revoke(
    interaction: Interaction[Any], role: discord.Role, area: app_commands.Choice[str]
) -> None:
    async def run() -> None:
        community = await _start(interaction, role)
        held = await db(permissions.revoke, community.pk, role.id, _areas(area))
        await _sync(interaction, community)
        if not held:
            await reply(interaction, f"{role.mention} didn't have {area.name}.")
            return
        await reply(interaction, f"{role.mention} can no longer use {_names(held)}.")

    await guarded(interaction, run)


def _list_text(community: Community) -> str:
    grants = permissions.grants_by_area(community.pk)
    lines = ["**Staff areas.** The server owner and Administrators hold every area."]
    for area in Area:
        roles = " ".join(f"<@&{role_id}>" for role_id in grants[area]) or "nobody yet"
        lines.append(f"**{area.label}** ({AREA_SCOPE[area]}): {roles}")
    return "\n".join(lines)


@permissions_group.command(name="list", description="Which roles hold each staff area")
async def permissions_list(interaction: Interaction[Any]) -> None:
    async def run() -> None:
        community = await _start(interaction)
        await reply(interaction, await db(_list_text, community))

    await guarded(interaction, run)


GROUPS: tuple[app_commands.Group, ...] = (permissions_group,)
