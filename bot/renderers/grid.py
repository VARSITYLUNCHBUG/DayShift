"""The hero grid's layout, shared by the match board and the standalone draft. Pure: no I/O.

The grid sits in messages of its own directly below the draft message. They hold nothing else,
so they stack into one grid. Each turn they are posted afresh rather than edited, so no
"(edited)" tag splits the grid.
"""

from __future__ import annotations

from typing import Any

import discord
from discord.ui import ActionRow, LayoutView

# Discord caps a string select at 25 options, and an action row at 5 buttons.
SELECT_LIMIT = 25
BUTTONS_PER_ROW = 5
# A message holds 40 components, counting each row and button, so a message of nothing but rows
# holds 6 full rows. The grid gets up to two such messages of its own; a bigger roster falls back
# to selects.
ROWS_PER_GRID_MESSAGE = 6
GRID_MESSAGES = 2


def chunks(items: list[Any], size: int = SELECT_LIMIT) -> list[list[Any]]:
    return [items[start : start + size] for start in range(0, len(items), size)]


def button_rows(buttons: list[Any]) -> list[ActionRow[Any]]:
    return [ActionRow(*chunk) for chunk in chunks(buttons, BUTTONS_PER_ROW)]


def fits(rows: list[ActionRow[Any]]) -> bool:
    return len(rows) <= ROWS_PER_GRID_MESSAGE * GRID_MESSAGES


def messages(rows: list[ActionRow[Any]]) -> list[LayoutView]:
    """Split the grid's rows into its messages, balanced, so neither half looks an afterthought."""
    if not rows:
        return []
    count = -(-len(rows) // ROWS_PER_GRID_MESSAGE)
    per_message = -(-len(rows) // count)
    views = []
    for start in range(0, len(rows), per_message):
        view = LayoutView(timeout=None)
        for row in rows[start : start + per_message]:
            view.add_item(row)
        views.append(view)
    return views


def hero_emoji(emoji_id: int | None, unicode_emoji: str) -> discord.PartialEmoji | None:
    """A hero's custom emoji if it has one, else its plain fallback. Custom ones need only an ID."""
    if emoji_id:
        return discord.PartialEmoji(name="c", id=emoji_id)
    if unicode_emoji:
        return discord.PartialEmoji(name=unicode_emoji)
    return None
