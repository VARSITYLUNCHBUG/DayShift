"""Bebot's priority list message. Pure: no I/O.

Waits are Discord timestamps, so they count up on every viewer's screen without the bot editing
the message each minute.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from discord.ui import Container, LayoutView, TextDisplay

from bot.renderers import style
from league.services.prio import PrioView

# A message holds 4000 characters of text; each line is about 110 with its two timestamps.
MAX_LINES = 30
LEGEND = "-# 🟢 In the Waiting Room · ⏳ Left: keeps their place until the time shown"


def _stamp(moment: datetime) -> str:
    return f"<t:{int(moment.timestamp())}:R>"


def prio_text(view_model: PrioView) -> str:
    lines = []
    for index, line in enumerate(view_model.lines[:MAX_LINES], start=1):
        if line.grace_until is not None:
            status = f"⏳ **{line.name}** waiting since {_stamp(line.queued_at)}"
            lines.append(f"`{index}.` {status}, place held until {_stamp(line.grace_until)}")
        else:
            lines.append(f"`{index}.` 🟢 **{line.name}** waiting since {_stamp(line.queued_at)}")
    if len(view_model.lines) > MAX_LINES:
        lines.append(f"...and {len(view_model.lines) - MAX_LINES} more")
    return "\n".join(lines) if lines else "Nobody is waiting."


def render_prio(view_model: PrioView) -> LayoutView:
    box: Container[Any] = Container(
        TextDisplay(f"### Priority list\n{prio_text(view_model)}"),
        TextDisplay(LEGEND),
        accent_colour=style.PRIO_COLOUR,
    )
    view = LayoutView(timeout=None)
    view.add_item(box)
    return view
