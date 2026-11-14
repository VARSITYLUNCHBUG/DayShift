"""/setup creates the permanent channels. Running it again only fills in whatever is missing.

The first run needs the server owner or an Administrator; after that, the Setup area. Staff
access to the bot's own staff channels follows the grants made with /permissions: every staff
role sees #staff-alerts, and match staff see the scoreboard archive.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

import discord
from discord import Interaction, app_commands

from bot.db import db
from bot.effects.gateway import SELF_TEXT, SELF_VOICE
from bot.handlers.permissions import require_area, require_manager
from bot.routing import guarded, reply
from league.models import Community
from league.models.permissions import Area
from league.services import common, permissions
from league.services import community as community_service

logger = logging.getLogger(__name__)

ARCHIVE_STAFF = discord.PermissionOverwrite(
    view_channel=True, read_message_history=True, send_messages=False
)
ALERTS_STAFF = discord.PermissionOverwrite(view_channel=True, read_message_history=True)


def _is_live(guild: discord.Guild, channel_id: int | None) -> bool:
    return channel_id is not None and guild.get_channel(channel_id) is not None


def _self(client: Any) -> discord.Object:
    return discord.Object(id=client.user.id, type=discord.Member)


async def ensure_channels(interaction: Interaction[Any], row: Community) -> None:
    guild = interaction.guild
    assert guild is not None
    me = _self(interaction.client)
    everyone = guild.default_role
    read_only = discord.PermissionOverwrite(view_channel=True, send_messages=False)
    wiring: dict[str, int | None] = {}

    category: Any = guild.get_channel(row.match_category_id or 0)
    if category is None:
        category = await guild.create_category(
            "Deadlock", overwrites={me: SELF_VOICE}, reason="Draft bot setup"
        )
        wiring["match_category_id"] = category.id

    if not _is_live(guild, row.waiting_room_channel_id):
        voice = await guild.create_voice_channel(
            "Waiting Room", category=category, overwrites={me: SELF_VOICE}
        )
        wiring["waiting_room_channel_id"] = voice.id
    if not _is_live(guild, row.queue_channel_id):
        channel = await guild.create_text_channel(
            "queue", category=category, overwrites={everyone: read_only, me: SELF_TEXT}
        )
        wiring["queue_channel_id"] = channel.id
        wiring["queue_message_id"] = None
    if not _is_live(guild, row.results_channel_id):
        channel = await guild.create_text_channel(
            "results", category=category, overwrites={everyone: read_only, me: SELF_TEXT}
        )
        wiring["results_channel_id"] = channel.id
    if not _is_live(guild, row.archive_channel_id):
        hidden = discord.PermissionOverwrite(view_channel=False)
        channel = await guild.create_text_channel(
            "scoreboard-archive", category=category, overwrites={everyone: hidden, me: SELF_TEXT}
        )
        wiring["archive_channel_id"] = channel.id
    if not _is_live(guild, row.staff_channel_id):
        hidden = discord.PermissionOverwrite(view_channel=False)
        channel = await guild.create_text_channel(
            "staff-alerts", category=category, overwrites={everyone: hidden, me: SELF_TEXT}
        )
        wiring["staff_channel_id"] = channel.id

    if wiring:
        await db(community_service.save_wiring, row.pk, **wiring)


async def _sync_roles(
    guild: discord.Guild,
    channel_id: int | None,
    role_ids: Iterable[int],
    overwrite: discord.PermissionOverwrite,
) -> None:
    """Give exactly these roles the overwrite on one of the bot's staff channels, removing it
    from any other role. Members' own overwrites and @everyone's are left alone."""
    channel = guild.get_channel(channel_id) if channel_id else None
    if not isinstance(channel, discord.TextChannel):
        return
    wanted = {role_id for role_id in role_ids if guild.get_role(role_id) is not None}
    for target in list(channel.overwrites):
        if isinstance(target, discord.Role) and not target.is_default() and target.id not in wanted:
            await channel.set_permissions(target, overwrite=None, reason="Staff access changed")
    for role_id in wanted:
        role = guild.get_role(role_id)
        if role is not None and channel.overwrites_for(role) != overwrite:
            await channel.set_permissions(role, overwrite=overwrite, reason="Staff access changed")


async def sync_staff_access(guild: discord.Guild, community_id: int) -> None:
    """Match the staff channels' role access to the current grants. Best effort: a failure is
    logged and the grants still stand."""
    row = await db(Community.objects.get, pk=community_id)
    match_staff = await db(permissions.role_ids_with, community_id, permissions.MATCH_STAFF_AREAS)
    all_staff = await db(permissions.role_ids_with, community_id, permissions.ALL_AREAS)
    try:
        await _sync_roles(guild, row.archive_channel_id, match_staff, ARCHIVE_STAFF)
        await _sync_roles(guild, row.staff_channel_id, all_staff, ALERTS_STAFF)
    except discord.HTTPException:
        logger.warning("Couldn't update staff channel access", exc_info=True)


def _refresh_queue(community_id: int) -> None:
    common.render_queue(Community.objects.get(pk=community_id))


@app_commands.command(name="setup", description="Create the queue, voice and results channels")
async def setup_command(interaction: Interaction[Any]) -> None:
    async def run() -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild = interaction.guild
        if guild is None:
            await reply(interaction, "Run this in your server.")
            return
        existing = await db(community_service.get, guild.id)
        if existing is None:
            require_manager(interaction)
        else:
            await require_area(interaction, existing, Area.SETUP)
        row = await db(community_service.ensure, guild.id, guild.name)
        await ensure_channels(interaction, row)
        await sync_staff_access(guild, row.pk)
        await db(_refresh_queue, row.pk)
        await reply(
            interaction,
            "Setup done. The queue is live, and staff alerts go to #staff-alerts. Give staff "
            "roles their areas with /permissions grant.",
        )

    await guarded(interaction, run)
