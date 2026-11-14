"""Staff alert buttons. A dispute's ruling buttons are the match's own (bot/handlers/results.py);
this is Dismiss, for anything else once it's dealt with."""

from __future__ import annotations

from bot.db import db
from bot.handlers.common import actor
from bot.handlers.permissions import require_area
from bot.routing import Context, handles
from league.services import alerts


@handles("alert_dismiss")
async def alert_dismiss(ctx: Context) -> None:
    await ctx.interaction.response.defer()
    alert_id = int(ctx.arg)
    community, area = await db(alerts.area_of, alert_id)
    await require_area(ctx.interaction, community, area)
    await db(alerts.dismiss, alert_id, await actor(ctx.interaction))
