"""What /prio tells a member about their own place. Pure: no I/O.

Times are Discord timestamps, so they count on the reader's screen.
A held place comes with Let it go, to give it up before its hold runs out.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from discord import ButtonStyle
from discord.ui import ActionRow, Container, LayoutView, TextDisplay

from bot.routing import RouteButton
from league.services.prio import PrioPlace


def _stamp(moment: datetime) -> str:
    return f"<t:{int(moment.timestamp())}:R>"


def place_text(place: PrioPlace | None, queue_channel_id: int | None) -> str:
    if place is None:
        where = f" Join it in <#{queue_channel_id}>." if queue_channel_id else ""
        return f"You're not in the queue, so you have no priority place.{where}"
    if place.held_until is not None:
        return (
            f"You left the queue. Your place, **#{place.position}** of {place.total}, is held "
            f"until {_stamp(place.held_until)}. Join again before then to keep it."
        )
    return (
        f"You're **#{place.position}** of {place.total} on the priority list, waiting since "
        f"{_stamp(place.queued_at)}."
    )


def held_view(place: PrioPlace) -> LayoutView:
    """/prio for a held place: the place, with Let it go to give it up now."""
    box: Container[Any] = Container(
        TextDisplay(place_text(place, None)),
        ActionRow(RouteButton("let_go", label="Let it go", style=ButtonStyle.secondary)),
    )
    view = LayoutView(timeout=None)
    view.add_item(box)
    return view
