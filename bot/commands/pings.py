"""Bebot's named channel pings: /pingchannel, /removeping, /pings and /ping.

Staff set up a ping per channel ("pugs" mentions @PUGS, at most every 15 minutes, say), and
members send it with a message. Only the mentions staff chose can ping anyone: the message's own
text never does.
"""

from __future__ import annotations

from typing import Any

import discord
from discord import Interaction, app_commands

from bot.db import db
from bot.handlers.common import community_of, require_staff
from bot.routing import guarded, reply
from league.domain.errors import InvalidAction
from league.models import Community
from league.services import pings

MAX_MESSAGE = 2000


async def _staff(interaction: Interaction[Any]) -> Community:
    await interaction.response.defer(ephemeral=True, thinking=True)
    community = await community_of(interaction)
    await require_staff(interaction, community)
    return community


def _unpingable_roles(interaction: Interaction[Any], role_ids: list[int]) -> list[str]:
    """Check the roles belong to this server and aren't @everyone. Returns the ones the ping
    would show but not notify: not mentionable, while the bot lacks Mention Everyone."""
    guild = interaction.guild
    if guild is None:
        raise InvalidAction("Run this in your server.")
    can_mention_any = interaction.app_permissions.mention_everyone
    unpingable = []
    for role_id in role_ids:
        role = guild.get_role(role_id)
        if role is None or role.is_default():  # The @everyone role has the server's own ID.
            raise InvalidAction("Only mention roles from this server, and not @everyone.")
        if not role.mentionable and not can_mention_any:
            unpingable.append(role.name)
    return unpingable


@app_commands.command(
    name="pingchannel", description="Add or replace a named ping in a channel (staff)"
)
@app_commands.describe(
    channel="Where the ping can be sent",
    name="What members type to send it, such as pugs",
    mention="The roles or members it mentions, such as @PUGS",
    timer="Minutes between pings",
    required_role="Only members with this role can send it (empty for everyone)",
)
async def pingchannel_command(
    interaction: Interaction[Any],
    channel: discord.TextChannel,
    name: str,
    mention: str,
    timer: app_commands.Range[int, 1, 10080],
    required_role: discord.Role | None = None,
) -> None:
    async def run() -> None:
        community = await _staff(interaction)
        targets = pings.parse_targets(mention)
        unpingable = _unpingable_roles(interaction, targets.role_ids)
        ping = await db(
            pings.add,
            community.pk,
            channel.id,
            name,
            targets,
            timer,
            required_role.id if required_role else None,
        )
        role_note = f", for members with {required_role.mention}" if required_role else ""
        text = (
            f"Ping `{ping.name}` in {channel.mention}: {ping.mention}, "
            f"every {timer} min{role_note}."
        )
        if unpingable:
            text += (
                f"\n⚠️ {', '.join(unpingable)} can't be mentioned, so it won't notify anyone. "
                "Make the role mentionable, or give me Mention @everyone."
            )
        await reply(interaction, text)

    await guarded(interaction, run)


@app_commands.command(name="removeping", description="Remove a named ping from a channel (staff)")
@app_commands.describe(channel="The channel the ping is in", name="The ping's name")
async def removeping_command(
    interaction: Interaction[Any], channel: discord.TextChannel, name: str
) -> None:
    async def run() -> None:
        community = await _staff(interaction)
        if await db(pings.remove, community.pk, channel.id, name):
            await reply(interaction, f"Removed `{name}` from {channel.mention}.")
        else:
            await reply(interaction, f"There's no ping called `{name}` in {channel.mention}.")

    await guarded(interaction, run)


def _pings_text(channel_id: int) -> str:
    rows = pings.in_channel(channel_id)
    if not rows:
        return "No pings are set up in this channel."
    lines = []
    for row in rows:
        ready = pings.ready_at(row)
        status = f"ready <t:{int(ready.timestamp())}:R>" if ready else "ready now"
        role = f", needs <@&{row.required_role_id}>" if row.required_role_id else ""
        lines.append(
            f"`{row.name}` → {row.mention} (every {row.timer_minutes} min{role}): {status}"
        )
    return "\n".join(lines)[:1900]


@app_commands.command(name="pings", description="The pings you can send in this channel")
async def pings_command(interaction: Interaction[Any]) -> None:
    async def run() -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        await community_of(interaction)
        if interaction.channel_id is None:
            raise InvalidAction("Run this in a server channel.")
        await reply(interaction, await db(_pings_text, interaction.channel_id))

    await guarded(interaction, run)


async def _ping_names(
    interaction: Interaction[Any], current: str
) -> list[app_commands.Choice[str]]:
    if interaction.channel_id is None:
        return []
    rows = await db(pings.in_channel, interaction.channel_id)
    wanted = current.lower()
    return [
        app_commands.Choice(name=row.name, value=row.name) for row in rows if wanted in row.name
    ][:25]


@app_commands.command(name="ping", description="Send this channel's ping with your message")
@app_commands.describe(
    message="What to say after the mention", name="Which ping, if there's more than one"
)
@app_commands.autocomplete(name=_ping_names)
async def ping_command(
    interaction: Interaction[Any], message: str, name: str | None = None
) -> None:
    async def run() -> None:
        # One database call before answering: Discord allows three seconds, and the ping itself
        # has to be the answer, since mentions in a later edit don't notify anyone. A channel
        # only has pings if staff set them up, so there's no separate server check.
        if interaction.guild_id is None or interaction.channel_id is None:
            raise InvalidAction("Run this in a server channel.")
        roles = getattr(interaction.user, "roles", [])
        claim = await db(pings.claim, interaction.channel_id, name, {role.id for role in roles})
        ping = claim.ping
        prefix = f"{ping.mention} "
        content = prefix + " ".join(message.split())[: MAX_MESSAGE - len(prefix)]
        # Only the mentions staff configured ping anyone; nothing typed into the message does.
        allowed = discord.AllowedMentions(
            everyone=False,
            roles=[discord.Object(id=role_id) for role_id in ping.role_ids],
            users=[discord.Object(id=user_id) for user_id in ping.user_ids],
        )
        try:
            await interaction.response.send_message(content, allowed_mentions=allowed)
        except Exception as exc:
            # Nothing went out (refused, timed out, connection dropped): give the cooldown back.
            await db(pings.release, claim)
            if isinstance(exc, discord.HTTPException):
                raise InvalidAction(
                    "Discord didn't take the ping, so its cooldown wasn't used."
                ) from exc
            raise

    await guarded(interaction, run)


COMMANDS: tuple[app_commands.Command[Any, Any, Any], ...] = (
    pingchannel_command,
    removeping_command,
    pings_command,
    ping_command,
)
