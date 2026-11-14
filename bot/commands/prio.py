"""Bebot's voice priority list commands: /priolist, /prio, /refresh and /removeprio.

The list follows the Waiting Room set up with /setup. /priolist, /refresh and /removeprio need
the Community area; /prio is open to everyone.
"""

from __future__ import annotations

from typing import Any

import discord
from discord import Interaction, app_commands

from bot.db import db
from bot.handlers.common import community_of
from bot.handlers.permissions import require_area
from bot.renderers.prio import prio_text
from bot.routing import guarded, reply
from league.domain.errors import InvalidAction
from league.models import Community
from league.models.permissions import Area
from league.services import prio


async def _staff(interaction: Interaction[Any]) -> Community:
    await interaction.response.defer(ephemeral=True, thinking=True)
    community = await community_of(interaction)
    await require_area(interaction, community, Area.COMMUNITY)
    return community


@app_commands.command(name="priolist", description="Post the priority list in this channel (staff)")
async def priolist_command(interaction: Interaction[Any]) -> None:
    async def run() -> None:
        community = await _staff(interaction)
        if not community.waiting_room_channel_id:
            raise InvalidAction(
                "The list follows the Waiting Room, which isn't set up: run /setup."
            )
        perms = interaction.app_permissions
        if not (perms.view_channel and perms.send_messages):
            raise InvalidAction("I can't post here. I need View Channel and Send Messages.")
        if interaction.channel_id is None:
            raise InvalidAction("Run this in a server channel.")
        await db(prio.set_display, community.pk, interaction.channel_id)
        await reply(interaction, "Posting the priority list here. It updates on its own.")

    await guarded(interaction, run)


@app_commands.command(name="prio", description="Who has waited longest in the Waiting Room")
async def prio_command(interaction: Interaction[Any]) -> None:
    async def run() -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        community = await community_of(interaction)
        await reply(interaction, prio_text(await db(prio.prio_view, community.pk))[:1900])

    await guarded(interaction, run)


@app_commands.command(name="refresh", description="Re-post the priority list's message (staff)")
async def refresh_command(interaction: Interaction[Any]) -> None:
    async def run() -> None:
        community = await _staff(interaction)
        if not await db(prio.repost, community.pk):
            raise InvalidAction("There's no priority list yet. Use /priolist first.")
        await reply(interaction, "Posting the priority list again, below the chat.")

    await guarded(interaction, run)


@app_commands.command(name="removeprio", description="Take someone off the priority list (staff)")
@app_commands.describe(user="The member to take off")
async def removeprio_command(interaction: Interaction[Any], user: discord.Member) -> None:
    async def run() -> None:
        community = await _staff(interaction)
        if await db(prio.remove, community.pk, user.id):
            await reply(interaction, f"Took {user.display_name} off the priority list.")
        else:
            await reply(interaction, f"{user.display_name} isn't on the priority list.")

    await guarded(interaction, run)


COMMANDS: tuple[app_commands.Command[Any, Any, Any], ...] = (
    priolist_command,
    prio_command,
    refresh_command,
    removeprio_command,
)
