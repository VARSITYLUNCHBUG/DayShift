"""Captains swapping two players. The service checks everything again under the match lock."""

from __future__ import annotations

from typing import Any

from discord import ButtonStyle
from discord.ui import ActionRow, Container, LayoutView, TextDisplay

from bot.db import db
from bot.handlers.common import actor
from bot.renderers.grid import BUTTONS_PER_ROW
from bot.routing import Context, RouteButton, handles, reply
from league.services import swaps


def _picker(text: str, buttons: list[RouteButton]) -> LayoutView:
    box: Container[Any] = Container(TextDisplay(text))
    for start in range(0, len(buttons), BUTTONS_PER_ROW):
        box.add_item(ActionRow(*buttons[start : start + BUTTONS_PER_ROW]))
    view = LayoutView(timeout=None)
    view.add_item(box)
    return view


@handles("swap_open")
async def swap_open(ctx: Context) -> None:
    """First, which of your players to offer."""
    await ctx.interaction.response.defer(ephemeral=True, thinking=True)
    options = await db(swaps.own_options, ctx.match_id, await actor(ctx.interaction))
    if not options:
        await reply(ctx.interaction, "You have no players to offer.")
        return
    buttons = [
        RouteButton("swap_give", ctx.match_id, choice.player_id, label=choice.name[:80])
        for choice in options
    ]
    view = _picker("Which of your players do you want to swap?", buttons)
    await ctx.interaction.followup.send(view=view, ephemeral=True)


@handles("swap_give")
async def swap_give(ctx: Context) -> None:
    """Then, which of theirs to ask for. The arg is the player you're offering."""
    await ctx.interaction.response.defer()
    options = await db(swaps.their_options, ctx.match_id, await actor(ctx.interaction))
    buttons = [
        RouteButton(
            "swap_take",
            ctx.match_id,
            f"{ctx.arg}.{choice.player_id}",
            label=choice.name[:80],
            style=ButtonStyle.primary,
        )
        for choice in options
    ]
    view = _picker("And which of their players do you want for them?", buttons)
    await ctx.interaction.edit_original_response(view=view)


@handles("swap_take")
async def swap_take(ctx: Context) -> None:
    """Send the offer. The arg is "<yours>.<theirs>"."""
    await ctx.interaction.response.defer()
    give, take = ctx.arg.split(".")
    swap = await db(swaps.propose, ctx.match_id, await actor(ctx.interaction), int(give), int(take))
    done = _picker(
        f"Offered **{swap.give.display_name}** for **{swap.take.display_name}**. "
        "The other captain answers on the board.",
        [],
    )
    await ctx.interaction.edit_original_response(view=done)


@handles("swap_yes")
async def swap_yes(ctx: Context) -> None:
    await ctx.interaction.response.defer()
    await db(swaps.answer, ctx.match_id, await actor(ctx.interaction), int(ctx.arg), True)


@handles("swap_no")
async def swap_no(ctx: Context) -> None:
    await ctx.interaction.response.defer()
    await db(swaps.answer, ctx.match_id, await actor(ctx.interaction), int(ctx.arg), False)
