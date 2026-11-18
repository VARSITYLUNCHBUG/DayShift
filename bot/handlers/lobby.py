from __future__ import annotations

import contextlib

import discord

from bot.db import db
from bot.handlers.common import actor
from bot.renderers.board import render_voice_dm
from bot.routing import Context, handles, reply
from league.models import Match
from league.models.matches import ResourceKind
from league.services import effects, lobby


def _match_channel_url(match_id: int) -> str | None:
    guild_id = Match.objects.filter(pk=match_id).values_list(
        "community__discord_guild_id", flat=True
    )[0]
    channel_id = effects.resource_id(match_id, ResourceKind.TEXT)
    return f"https://discord.com/channels/{guild_id}/{channel_id}" if channel_id else None


@handles("ready")
async def ready(ctx: Context) -> None:
    await ctx.interaction.response.defer()
    await db(lobby.mark_ready, ctx.match_id, await actor(ctx.interaction))
    if ctx.interaction.guild_id is None:
        # From the DM: the DM itself turns into the answer, so its Ready can't be pressed again.
        view = render_voice_dm(
            ctx.match_id,
            None,
            heading="✅ You're ready",
            body="Wait in the Waiting Room and keep an eye on the board.",
            channel_url=await db(_match_channel_url, ctx.match_id),
        )
        with contextlib.suppress(discord.HTTPException):
            await ctx.interaction.edit_original_response(view=view)


@handles("captain_vote")
async def captain_vote(ctx: Context) -> None:
    await ctx.interaction.response.defer(ephemeral=True, thinking=True)
    chosen = await db(
        lobby.cast_captain_votes,
        ctx.match_id,
        await actor(ctx.interaction),
        [int(value) for value in ctx.values],
    )
    names = " and ".join(f"**{player.display_name}**" for player in chosen)
    await reply(ctx.interaction, f"You voted for {names}. Vote again to change it.")


@handles("checkin")
async def checkin(ctx: Context) -> None:
    """A captain's I'm here, before the player draft."""
    await ctx.interaction.response.defer()
    await db(lobby.check_in, ctx.match_id, await actor(ctx.interaction))
