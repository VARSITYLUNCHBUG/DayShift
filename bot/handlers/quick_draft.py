"""Clicks on a standalone draft (/startdraft, /captains_coinflip). The match slot holds its ID."""

from __future__ import annotations

from django.conf import settings

from bot.db import db
from bot.routing import Context, handles, reply
from league.domain import copy
from league.services import quick_drafts


def _name(ctx: Context) -> str:
    user = ctx.interaction.user
    return getattr(user, "display_name", None) or user.name


@handles("qd_captain")
async def claim_captain(ctx: Context) -> None:
    await ctx.interaction.response.defer(ephemeral=True, thinking=True)
    label = await db(
        quick_drafts.claim_captain,
        ctx.match_id,
        ctx.arg,
        ctx.interaction.user.id,
        _name(ctx),
        allow_both=settings.DEBUG,  # Lets one person test both sides, as Bebot did.
    )
    await reply(ctx.interaction, copy.now_captain(label))


@handles("qd_coin")
async def coinflip_choice(ctx: Context) -> None:
    await ctx.interaction.response.defer()
    await db(quick_drafts.coinflip_choose, ctx.match_id, ctx.interaction.user.id, ctx.arg)


@handles("qd_start")
async def start_draft(ctx: Context) -> None:
    await ctx.interaction.response.defer()
    await db(quick_drafts.start_after_coinflip, ctx.match_id, ctx.interaction.user.id)


@handles("qd_hero")
async def choose_hero(ctx: Context) -> None:
    await ctx.interaction.response.defer()
    step_index, champion_id = ctx.arg.split(".")  # "<step>.<champion>"
    await db(
        quick_drafts.choose_hero,
        ctx.match_id,
        ctx.interaction.user.id,
        int(step_index),
        int(champion_id),
        ctx.interaction.id,
    )


@handles("qd_pick")
async def pick_hero(ctx: Context) -> None:
    """The dropdown fallback for a roster too big for the grid. The arg is "<step>.<select>"."""
    await ctx.interaction.response.defer()
    await db(
        quick_drafts.choose_hero,
        ctx.match_id,
        ctx.interaction.user.id,
        int(ctx.arg.split(".")[0]),
        int(ctx.values[0]),
        ctx.interaction.id,
    )


@handles("qd_random")
async def random_hero(ctx: Context) -> None:
    await ctx.interaction.response.defer()
    await db(
        quick_drafts.choose_random,
        ctx.match_id,
        ctx.interaction.user.id,
        int(ctx.arg),
        ctx.interaction.id,
    )
