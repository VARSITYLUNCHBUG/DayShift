"""/setup creates the permanent channels. Running it again only fills in whatever is missing.

The first run needs the server owner or an Administrator; after that, the Setup area. Staff
access to the bot's own staff channels follows the grants made with /permissions: every staff
role sees #staff-alerts, and match staff see the scoreboard archive.

With a PUG role set (`/setup pug_role:`), only that role sees the queue, the Waiting Room, the
results and the leaderboard. Without one, everyone does.
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


HIDDEN = discord.PermissionOverwrite(view_channel=False)
READ_ONLY = discord.PermissionOverwrite(view_channel=True, send_messages=False)
VOICE_OPEN = discord.PermissionOverwrite(view_channel=True, connect=True)


def _player_overwrites(
    guild: discord.Guild, me: discord.Object, pug_role_id: int | None, *, voice: bool
) -> dict[Any, discord.PermissionOverwrite]:
    """Who sees a channel players use: everyone, or only the PUG role when one is set."""
    own = SELF_VOICE if voice else SELF_TEXT
    allowed = VOICE_OPEN if voice else READ_ONLY
    role = guild.get_role(pug_role_id) if pug_role_id else None
    if role is None:
        return {guild.default_role: allowed, me: own} if not voice else {me: own}
    return {guild.default_role: HIDDEN, role: allowed, me: own}


CATEGORY_NAME = "Deadlock"
# Every channel /setup makes, by the name it gives it.
TEXT_CHANNELS = ("queue", "results", "leaderboard", "scoreboard-archive", "staff-alerts")
WAITING_ROOM = "Waiting Room"


def existing_category(guild: discord.Guild) -> Any:
    """A Deadlock category an earlier setup made (on this server, before its database was
    reset): the one holding most of our channels, as long as it has a #queue. None if there's
    none, so setup makes one."""
    best, best_count = None, 0
    for category in guild.categories:
        if category.name != CATEGORY_NAME:
            continue
        names = {channel.name for channel in category.channels}
        if "queue" not in names:
            continue
        count = len(names & {*TEXT_CHANNELS, WAITING_ROOM})
        if count > best_count:
            best, best_count = category, count
    return best


def _in_category(category: Any, name: str, kind: type) -> Any:
    return next(
        (c for c in category.channels if c.name == name and isinstance(c, kind)),
        None,
    )


async def ensure_channels(interaction: Interaction[Any], row: Community) -> bool:
    """Fill in whatever is missing. Returns True when an existing category was reused."""
    guild = interaction.guild
    assert guild is not None
    me = _self(interaction.client)
    everyone = guild.default_role
    text_access = _player_overwrites(guild, me, row.pug_role_id, voice=False)
    wiring: dict[str, int | list[int] | None] = {}
    reused = False

    category: Any = guild.get_channel(row.match_category_id or 0)
    if category is None:
        category = existing_category(guild)
        reused = category is not None
        if category is None:
            category = await guild.create_category(
                CATEGORY_NAME, overwrites={me: SELF_VOICE}, reason="DayShift setup"
            )
        wiring["match_category_id"] = category.id

    async def text(name: str, overwrites: dict[Any, discord.PermissionOverwrite]) -> int:
        found = _in_category(category, name, discord.TextChannel) if reused else None
        if found is not None:
            return int(found.id)
        channel = await guild.create_text_channel(name, category=category, overwrites=overwrites)
        return int(channel.id)

    if not _is_live(guild, row.waiting_room_channel_id):
        found = _in_category(category, WAITING_ROOM, discord.VoiceChannel) if reused else None
        if found is None:
            found = await guild.create_voice_channel(
                WAITING_ROOM,
                category=category,
                overwrites=_player_overwrites(guild, me, row.pug_role_id, voice=True),
            )
        wiring["waiting_room_channel_id"] = found.id
    if not _is_live(guild, row.queue_channel_id):
        wiring["queue_channel_id"] = await text("queue", text_access)
        wiring["queue_message_id"] = None
    if not _is_live(guild, row.results_channel_id):
        wiring["results_channel_id"] = await text("results", text_access)
    if not _is_live(guild, row.leaderboard_channel_id):
        wiring["leaderboard_channel_id"] = await text("leaderboard", text_access)
        wiring["leaderboard_message_ids"] = []
    staff_only = {everyone: discord.PermissionOverwrite(view_channel=False), me: SELF_TEXT}
    if not _is_live(guild, row.archive_channel_id):
        wiring["archive_channel_id"] = await text("scoreboard-archive", staff_only)
    if not _is_live(guild, row.staff_channel_id):
        wiring["staff_channel_id"] = await text("staff-alerts", staff_only)

    if wiring:
        await db(community_service.save_wiring, row.pk, **wiring)
    return reused


async def sync_pug_access(guild: discord.Guild, community_id: int) -> None:
    """Make the queue, Waiting Room, results and leaderboard visible to the PUG role alone, or to
    everyone when none is set. Best effort, like staff access."""
    row = await db(Community.objects.get, pk=community_id)
    role = guild.get_role(row.pug_role_id) if row.pug_role_id else None
    everyone = guild.default_role
    targets = (
        (row.queue_channel_id, READ_ONLY),
        (row.results_channel_id, READ_ONLY),
        (row.leaderboard_channel_id, READ_ONLY),
        (row.waiting_room_channel_id, VOICE_OPEN),
    )
    try:
        for channel_id, allowed in targets:
            channel = guild.get_channel(channel_id) if channel_id else None
            if not isinstance(channel, discord.TextChannel | discord.VoiceChannel):
                continue
            voice = isinstance(channel, discord.VoiceChannel)
            if role is None:
                # Everyone again: a voice channel needs no overwrite for that.
                wanted = None if voice else allowed
                if channel.overwrites_for(everyone) != (wanted or discord.PermissionOverwrite()):
                    await channel.set_permissions(everyone, overwrite=wanted, reason="PUG access")
                continue
            if channel.overwrites_for(everyone) != HIDDEN:
                await channel.set_permissions(everyone, overwrite=HIDDEN, reason="PUG access")
            if channel.overwrites_for(role) != allowed:
                await channel.set_permissions(role, overwrite=allowed, reason="PUG access")
    except discord.HTTPException:
        logger.warning("Couldn't update PUG channel access", exc_info=True)


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


async def _clear_old_panels(interaction: Interaction[Any], community_id: int) -> None:
    """A reused #queue and #leaderboard still hold the old setup's panel and pages, whose
    message IDs went with the old database. Delete the bot's own messages there so the fresh ones
    are the only ones. A bot can always delete its own messages. Best effort."""
    row = await db(Community.objects.get, pk=community_id)
    me = interaction.client.user
    guild = interaction.guild
    assert guild is not None and me is not None
    for channel_id in (row.queue_channel_id, row.leaderboard_channel_id):
        channel = guild.get_channel(channel_id) if channel_id else None
        if not isinstance(channel, discord.TextChannel):
            continue
        try:
            async for message in channel.history(limit=100):
                if message.author.id == me.id:
                    await message.delete()
        except discord.HTTPException:
            logger.warning("Couldn't clear an old panel", exc_info=True)


def _refresh_queue(community_id: int) -> None:
    from league.services import leaderboards

    community = Community.objects.get(pk=community_id)
    common.render_queue(community)
    leaderboards.request(community)


@app_commands.command(
    name="setup", description="Create the queue, voice, results and leaderboard channels"
)
@app_commands.describe(
    pug_role="Only this role sees the PUG channels and can use /leaderboard. Empty: keep as is"
)
async def setup_command(
    interaction: Interaction[Any], pug_role: discord.Role | None = None
) -> None:
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
        if pug_role is not None:
            await db(community_service.save_wiring, row.pk, pug_role_id=pug_role.id)
            row = await db(Community.objects.get, pk=row.pk)
        reused = await ensure_channels(interaction, row)
        if reused:
            await _clear_old_panels(interaction, row.pk)
        await sync_staff_access(guild, row.pk)
        await sync_pug_access(guild, row.pk)
        await db(_refresh_queue, row.pk)
        access = (
            f"Only {pug_role.mention} sees the PUG channels."
            if pug_role is not None
            else "Set a PUG role with `/setup pug_role:` to limit who sees the PUG channels."
            if row.pug_role_id is None
            else ""
        )
        again = "It reused the Deadlock category already here. " if reused else ""
        await reply(
            interaction,
            f"Setup done. {again}The queue is live, the leaderboard is in #leaderboard, and staff "
            "alerts go to #staff-alerts. Give staff roles their areas with /permissions grant. "
            f"{access}",
        )

    await guarded(interaction, run)
