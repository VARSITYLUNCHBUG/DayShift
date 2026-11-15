from __future__ import annotations

from typing import Any

from discord import ButtonStyle
from discord.ui import ActionRow, Container, LayoutView, TextDisplay

from bot.renderers import style
from bot.routing import RouteButton
from league.services.boards import QueueView

MAX_NAMES_SHOWN = 30


def render_queue(view_model: QueueView) -> LayoutView:
    names = view_model.players[:MAX_NAMES_SHOWN]
    listing = "\n".join(f"{index}. {name}" for index, name in enumerate(names, start=1)) or "Empty"
    if len(view_model.players) > MAX_NAMES_SHOWN:
        listing += f"\n...and {len(view_model.players) - MAX_NAMES_SHOWN} more"
    needed = view_model.capacity - view_model.size
    heading = f"## Queue: {view_model.size}/{view_model.capacity}"
    if 0 < needed < view_model.capacity:
        heading += f" · {needed} more to start"
    box: Container[Any] = Container(
        TextDisplay(f"{heading}\n{listing}"),
        ActionRow(
            RouteButton("join", label="Join", style=ButtonStyle.success),
            RouteButton("leave", label="Leave", style=ButtonStyle.danger),
        ),
        accent_colour=style.QUEUE_COLOUR,
    )
    view = LayoutView(timeout=None)
    view.add_item(box)
    return view
