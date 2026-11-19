"""The #leaderboard channel's messages, and a player's own line of it. Pure: no I/O.

The channel shows the leaderboard as images (bot/renderers/leaderboard_image.py), ten players to
each, one image to a message, so a refresh edits each message's image in place.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import discord
from discord.ui import LayoutView, MediaGallery, TextDisplay

from bot.renderers import leaderboard_image
from league.domain.copy import plural
from league.services.leaderboards import Row

FIGURE_SPACE = "\u2007"  # As wide as a digit, and Discord doesn't collapse it.


def win_rate(value: float | None) -> str:
    return "-" if value is None else f"{value:.0%}"


def file_name(index: int) -> str:
    return f"leaderboard-{index + 1}.png"


def pages(
    rows: list[Row], rating_label: str, season_name: str, updated_at: datetime
) -> list[tuple[LayoutView, tuple[str, bytes]]]:
    """Each message of the leaderboard: its image (ten players) and the view that shows it. The
    last one says how to see your own place in full."""
    pngs = leaderboard_image.images(
        rows, season_name=season_name, rating_label=rating_label, updated_at=updated_at
    )
    out = []
    for index, png in enumerate(pngs):
        name = file_name(index)
        view = LayoutView(timeout=None)
        view.add_item(MediaGallery(discord.MediaGalleryItem(f"attachment://{name}")))
        if index == len(pngs) - 1:
            footer: TextDisplay[Any] = TextDisplay(
                "-# Highest first. Refreshes every hour and after each match. "
                "`/stats` shows yours in full."
            )
            view.add_item(footer)
        out.append((view, (name, png)))
    return out


def page_text(view: LayoutView) -> str:
    """Every text in a card, for tests and size checks."""
    out: list[str] = []
    for item in view.walk_children():
        if isinstance(item, TextDisplay):
            out.append(item.content)
    return "\n".join(out)


def own_text(row: Row | None, total: int, rating_label: str, channel_id: int | None) -> str:
    where = f" Everyone's is in <#{channel_id}>." if channel_id else ""
    if row is None:
        return f"You're not on the leaderboard yet: play a match to get on it.{where}"
    record = f"{plural(row.wins, 'win')}, {plural(row.losses, 'loss', 'losses')}"
    return (
        f"**#{row.rank}** of {total}: **{row.rating}** {rating_label.lower()}, {record} "
        f"({win_rate(row.win_rate)} won).{where}"
    )
