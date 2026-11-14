"""Bebot's standalone draft commands: /startdraft, /stopdraft, /captains_coinflip, /coinflip and
/randomdraft. They work in any channel of a set-up server and never touch ratings.

The draft message is posted by the outbox, like every board, so a command only records the draft
and says so. It checks first that the bot can post and read in the channel, because a draft it
can't show would hold the channel until it timed out.
"""

from __future__ import annotations

import secrets
from typing import Any

import discord
from discord import Interaction, app_commands

from bot.db import db
from bot.handlers.common import community_of, is_staff
from bot.renderers.quick_draft import render_coinflip, render_random_draft
from bot.routing import guarded, reply
from league.domain.errors import InvalidAction
from league.services import quick_drafts


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
        custom_emojis = can_post_here(interaction)
        await db(
            quick_drafts.start,
            community.pk,
            _channel_id(interaction),
            interaction.user.id,
            custom_emojis=custom_emojis,
        )
        await reply(interaction, "Posting the draft. Captains: claim a side.")

    await guarded(interaction, run)


@app_commands.command(name="stopdraft", description="Stop the draft running in this channel")
async def stopdraft_command(interaction: Interaction[Any]) -> None:
    async def run() -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        community = await community_of(interaction)
        await db(
            quick_drafts.stop,
            _channel_id(interaction),
            interaction.user.id,
            staff=is_staff(interaction, community),
        )
        await reply(interaction, "Draft stopped.")

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
        custom_emojis = can_post_here(interaction)
        await db(
            quick_drafts.start_coinflip,
            community.pk,
            _channel_id(interaction),
            interaction.user.id,
            (captain1.id, _name(captain1)),
            (captain2.id, _name(captain2)),
            custom_emojis=custom_emojis,
        )
        await reply(interaction, "Flipping the coin...")

    await guarded(interaction, run)


@app_commands.command(
    name="coinflip", description="Flip a coin: who takes The Hidden King (first pick)"
)
@app_commands.describe(player1="One player", player2="The other player")
async def coinflip_command(
    interaction: Interaction[Any], player1: discord.Member, player2: discord.Member
) -> None:
    async def run() -> None:
        if player1.id == player2.id:
            raise InvalidAction("You can't flip a coin between the same player!")
        first = (player1.id, _name(player1))
        second = (player2.id, _name(player2))
        winner, loser = (first, second) if secrets.randbelow(2) == 0 else (second, first)
        await interaction.response.send_message(
            view=render_coinflip(winner, loser),
            allowed_mentions=discord.AllowedMentions(users=[player1, player2]),
        )

    await guarded(interaction, run)


@app_commands.command(
    name="randomdraft", description="Random bans and picks for both sides, in this server's mode"
)
async def randomdraft_command(interaction: Interaction[Any]) -> None:
    async def run() -> None:
        community = await community_of(interaction)  # Before answering: refusals stay private.
        await interaction.response.defer(thinking=True)
        draft = await db(quick_drafts.random_draft, community)
        await interaction.followup.send(view=render_random_draft(draft))

    await guarded(interaction, run)


COMMANDS: tuple[app_commands.Command[Any, Any, Any], ...] = (
    startdraft_command,
    stopdraft_command,
    captains_coinflip_command,
    coinflip_command,
    randomdraft_command,
)
