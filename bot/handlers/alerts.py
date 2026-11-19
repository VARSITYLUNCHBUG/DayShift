"""Staff alert buttons. A dispute's ruling buttons are the match's own (bot/handlers/results.py);
this is Dismiss, for anything else once it's dealt with, and an early leave's Void."""

from __future__ import annotations

from bot.db import db
from bot.handlers.common import actor
from bot.handlers.permissions import require_area
from bot.routing import Context, handles
from league.services import alerts, early_leave


@handles("early_leave_void")
async def early_leave_void(ctx: Context) -> None:
    """Void from the early-leave card: the same as /match early_leave, without needing the leaver
    to still be in the server."""
    await ctx.interaction.response.defer()
    alert_id = int(ctx.arg)
    community, area = await db(alerts.area_of, alert_id)
    await require_area(ctx.interaction, community, area)
    await db(early_leave.void_from_alert, ctx.match_id, await actor(ctx.interaction))


@handles("alert_dismiss")
async def alert_dismiss(ctx: Context) -> None:
    await ctx.interaction.response.defer()
    alert_id = int(ctx.arg)
    community, area = await db(alerts.area_of, alert_id)
    await require_area(ctx.interaction, community, area)
    await db(alerts.dismiss, alert_id, await actor(ctx.interaction))
