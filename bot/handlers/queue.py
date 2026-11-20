from __future__ import annotations

import contextlib
from collections.abc import Awaitable, Callable

import discord

from bot.db import db
from bot.handlers.common import actor, community_of
from bot.renderers import style
from bot.renderers.queue import render_check_in_answered
from bot.routing import Context, handles
from league.domain.errors import InvalidAction
from league.services import queue

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


# --- The idle check-in DM. It has no server, so the button carries the community ID. ---------


async def _answer_check_in(ctx: Context, answer: Callable[[], Awaitable[str]]) -> None:
    """Swap the check-in for its answer, so its buttons can't be pressed again. A refusal (they
    were already taken out, or the queue popped) becomes the answer too."""
    await ctx.interaction.response.defer()
    try:
        text = await answer()
    except InvalidAction as exc:
        text = exc.message
    with contextlib.suppress(discord.HTTPException):
        await ctx.interaction.edit_original_response(view=render_check_in_answered(text))


@handles("queue_stay")
async def queue_stay(ctx: Context) -> None:
    async def answer() -> str:
        remove_at = await db(queue.stay, int(ctx.arg), await actor(ctx.interaction))
        if remove_at is None:
            return "✅ You're staying in the queue."
        return f"✅ You're staying in the queue. We'll check again {style.relative(remove_at)}."

    await _answer_check_in(ctx, answer)


@handles("queue_leave")
async def queue_leave(ctx: Context) -> None:
    async def answer() -> str:
        await db(queue.leave, int(ctx.arg), await actor(ctx.interaction))
        return "You've left the queue."

    await _answer_check_in(ctx, answer)
