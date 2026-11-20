"""The priority list commands: /prio and /removeprio.

The list follows the match queue (see `league.services.prio`) and isn't posted anywhere. /prio
shows a member their own place, privately; /removeprio needs the Community area.
"""

from __future__ import annotations

from typing import Any

import discord
from discord import Interaction, app_commands

from bot.db import db
from bot.handlers.common import community_of
from bot.handlers.permissions import require_area
from bot.renderers.prio import held_view, place_text
from bot.routing import guarded, reply, reply_view
from league.models.permissions import Area
from league.services import prio


@app_commands.command(name="prio", description="Your place on the priority list")
async def prio_command(interaction: Interaction[Any]) -> None:
    async def run() -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        community = await community_of(interaction)
        place = await db(prio.place_of, community.pk, interaction.user.id)
        if place is not None and place.held_until is not None:
            await reply_view(interaction, held_view(place))
        else:
            await reply(interaction, place_text(place, community.queue_channel_id))

    await guarded(interaction, run)


@app_commands.command(name="removeprio", description="Take someone off the priority list (staff)")
@app_commands.describe(user="The member to take off")
async def removeprio_command(interaction: Interaction[Any], user: discord.Member) -> None:
    async def run() -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        community = await community_of(interaction)
        await require_area(interaction, community, Area.COMMUNITY)
        if await db(prio.remove, community.pk, user.id):
            await reply(interaction, f"Took {user.display_name} off the priority list.")
        else:
            await reply(interaction, f"{user.display_name} isn't on the priority list.")

    await guarded(interaction, run)


COMMANDS: tuple[app_commands.Command[Any, Any, Any], ...] = (prio_command, removeprio_command)
