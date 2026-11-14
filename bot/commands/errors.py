"""Bebot's /seterrorchannel and /clearerrorchannel: where this server's bot errors are posted.

Only this server's own errors go there, summarised. Both need the Setup area.
"""

from __future__ import annotations

from typing import Any

import discord
from discord import Interaction, app_commands

from bot.db import db
from bot.handlers.common import community_of
from bot.handlers.permissions import require_area
from bot.routing import guarded, reply
from league.domain.errors import InvalidAction
from league.models.permissions import Area
from league.services import community as community_service


def _forget(interaction: Interaction[Any]) -> None:
    """Make the error sink look the channel up afresh, instead of after its cache runs out."""
    sink = getattr(interaction.client, "error_sink", None)
    if sink is not None and interaction.guild_id is not None:
        sink.forget(interaction.guild_id)


@app_commands.command(
    name="seterrorchannel", description="Post this server's bot errors in a channel (staff)"
)
@app_commands.describe(channel="Where to post them. Keep it staff-only.")
async def seterrorchannel_command(
    interaction: Interaction[Any], channel: discord.TextChannel
) -> None:
    async def run() -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        community = await community_of(interaction)
        await require_area(interaction, community, Area.SETUP)
        perms = channel.permissions_for(channel.guild.me) if channel.guild.me else None
        if perms is not None and not (perms.view_channel and perms.send_messages):
            raise InvalidAction(f"I can't post in {channel.mention}: I need Send Messages there.")
        await db(community_service.save_wiring, community.pk, error_channel_id=channel.id)
        _forget(interaction)
        await reply(interaction, f"This server's bot errors will be posted in {channel.mention}.")

    await guarded(interaction, run)


@app_commands.command(
    name="clearerrorchannel", description="Stop posting this server's bot errors (staff)"
)
async def clearerrorchannel_command(interaction: Interaction[Any]) -> None:
    async def run() -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        community = await community_of(interaction)
        await require_area(interaction, community, Area.SETUP)
        await db(community_service.save_wiring, community.pk, error_channel_id=None)
        _forget(interaction)
        await reply(interaction, "Bot errors won't be posted in this server any more.")

    await guarded(interaction, run)


COMMANDS: tuple[app_commands.Command[Any, Any, Any], ...] = (
    seterrorchannel_command,
    clearerrorchannel_command,
)
