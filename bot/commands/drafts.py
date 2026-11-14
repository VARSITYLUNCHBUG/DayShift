"""Bebot's scrim commands: /startdraft, /stopdraft, /captains_coinflip and /randomdraft.
A scrim is a match of its own kind, run in any channel of a set-up server, recorded and never
rated. Scrims are run by staff: starting and stopping one needs the Scrims area. /randomdraft is
open to everyone.

The draft message is posted by the outbox, like every board, so a command only records the draft
and says so. It checks first that the bot can post and read in the channel, because a draft it
can't show would hold the channel until it timed out.
"""

from __future__ import annotations

from typing import Any

import discord
from discord import Interaction, app_commands

from bot.db import db
from bot.handlers.common import actor, community_of
from bot.handlers.permissions import require_area
from bot.renderers.random_draft import render_random_draft
from bot.routing import guarded, reply
from league.domain import copy
from league.domain.errors import InvalidAction
from league.models.permissions import Area
from league.services import common, scrims


def _channel_id(interaction: Interaction[Any]) -> int:
    if interaction.channel_id is None:
        raise InvalidAction("Run this in a server channel.")
    return interaction.channel_id


def can_post_here(interaction: Interaction[Any]) -> bool:
    """Refuse a draft the bot couldn't show. Returns whether custom hero emojis will work."""
    perms = interaction.app_permissions
    in_thread = isinstance(interaction.channel, discord.Thread)
    can_send = perms.send_messages_in_threads if in_thread else perms.send_messages
    missing = [
        name
        for name, granted in (
            ("View Channel", perms.view_channel),
            ("Send Messages in Threads" if in_thread else "Send Messages", can_send),
            ("Read Message History", perms.read_message_history),
        )
        if not granted
    ]
    if missing:
        raise InvalidAction(f"I can't run a draft here. I need: {', '.join(missing)}.")
    return perms.use_external_emojis


def _name(user: discord.abc.User) -> str:
    return getattr(user, "display_name", None) or user.name


@app_commands.command(name="startdraft", description="Start a hero draft in this channel")
async def startdraft_command(interaction: Interaction[Any]) -> None:
    async def run() -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        community = await community_of(interaction)
        await require_area(interaction, community, Area.SCRIMS)
        custom_emojis = can_post_here(interaction)
        await db(
            scrims.start_claim,
            community.pk,
            _channel_id(interaction),
            await actor(interaction),
            custom_emojis=custom_emojis,
        )
        await reply(interaction, "Posting the draft. Captains: claim a side.")

    await guarded(interaction, run)


@app_commands.command(name="stopdraft", description="Stop the draft running in this channel")
async def stopdraft_command(interaction: Interaction[Any]) -> None:
    async def run() -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        community = await community_of(interaction)
        await require_area(interaction, community, Area.SCRIMS)
        await db(scrims.stop, _channel_id(interaction), await actor(interaction))
        await reply(interaction, copy.DRAFT_STOPPED)

    await guarded(interaction, run)


@app_commands.command(
    name="captains_coinflip",
    description="Flip a coin between two captains: the winner chooses first, then the draft runs",
)
@app_commands.describe(captain1="One captain", captain2="The other captain")
async def captains_coinflip_command(
    interaction: Interaction[Any], captain1: discord.Member, captain2: discord.Member
) -> None:
    async def run() -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        if captain1.bot or captain2.bot:
            raise InvalidAction("Captains have to be people.")
        community = await community_of(interaction)
        await require_area(interaction, community, Area.SCRIMS)
        custom_emojis = can_post_here(interaction)
        first = await db(common.get_or_create_player, captain1.id, _name(captain1))
        second = await db(common.get_or_create_player, captain2.id, _name(captain2))
        await db(
            scrims.start_coinflip,
            community.pk,
            _channel_id(interaction),
            await actor(interaction),
            first,
            second,
            custom_emojis=custom_emojis,
        )
        await reply(interaction, "Flipping the coin...")

    await guarded(interaction, run)


@app_commands.command(
    name="randomdraft", description="Random bans and picks for both sides, in this server's mode"
)
async def randomdraft_command(interaction: Interaction[Any]) -> None:
    async def run() -> None:
        community = await community_of(interaction)  # Before answering: refusals stay private.
        await interaction.response.defer(thinking=True)
        draft = await db(scrims.random_draft, community)
        await interaction.followup.send(view=render_random_draft(draft))

    await guarded(interaction, run)


COMMANDS: tuple[app_commands.Command[Any, Any, Any], ...] = (
    startdraft_command,
    stopdraft_command,
    captains_coinflip_command,
    randomdraft_command,
)
