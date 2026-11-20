from __future__ import annotations

from bot.db import db
from bot.handlers.common import actor, community_of
from bot.routing import Context, handles, reply
from league.services import prio, queue

# Success says nothing: the queue board updates in front of them. Refusals still get a reply.


@handles("join")
async def join(ctx: Context) -> None:
    await ctx.interaction.response.defer()
    community = await community_of(ctx.interaction)
    player = await actor(ctx.interaction)
    await db(queue.join, community.pk, player)


@handles("leave")
async def leave(ctx: Context) -> None:
    await ctx.interaction.response.defer()
    community = await community_of(ctx.interaction)
    player = await actor(ctx.interaction)
    await db(queue.leave, community.pk, player)


@handles("let_go")
async def let_go(ctx: Context) -> None:
    """Let it go, on /prio's held place: it's gone now, rather than when the hold runs out."""
    await ctx.interaction.response.defer(ephemeral=True, thinking=True)
    community = await community_of(ctx.interaction)
    player = await actor(ctx.interaction)
    await db(prio.let_go, community.pk, player)
    await reply(
        ctx.interaction, "You let your place go. Join again any time, at the back of the list."
    )
