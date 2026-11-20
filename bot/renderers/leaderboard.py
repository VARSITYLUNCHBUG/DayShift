"""The #leaderboard channel's messages, and a player's own line of it. Pure: no I/O.

The channel shows the leaderboard as images (bot/renderers/leaderboard_image.py), ten players to
each, one image to a message, so a refresh edits each message's image in place.
"""

from __future__ import annotations

import hashlib
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


Page = tuple[LayoutView, tuple[str, bytes]]


def page_key(
    group: list[Row], *, index: int, count: int, total: int, rating_label: str, season_name: str
) -> str:
    """What a page shows, bar its "Updated" time: a refresh that changes none of it leaves that
    message alone, which spares Discord's edit limit."""
    content = repr((group, index, count, total, rating_label, season_name))
    return hashlib.sha256(content.encode()).hexdigest()


def page(
    group: list[Row],
    *,
    index: int,
    count: int,
    total: int,
    rating_label: str,
    season_name: str,
    updated_at: datetime,
) -> Page:
    """One message of the leaderboard: its image (up to ten players) and the view that shows it.
    The last one says how to see your own place in full. Drawing takes a moment: keep it off the
    event loop and the database thread."""
    png = leaderboard_image.render(
        group,
        season_name=season_name,
        rating_label=rating_label,
        total=total,
        updated_at=updated_at,
    )
    name = file_name(index)
    view = LayoutView(timeout=None)
    view.add_item(MediaGallery(discord.MediaGalleryItem(f"attachment://{name}")))
    if index == count - 1:
        footer: TextDisplay[Any] = TextDisplay(
            "-# Highest first. Refreshes every hour and after each match. "
            "`/stats` shows yours in full."
        )
        view.add_item(footer)
    return view, (name, png)


def pages(rows: list[Row], rating_label: str, season_name: str, updated_at: datetime) -> list[Page]:
    """Every message of the leaderboard, ten players to each image."""
    groups = leaderboard_image.split(rows)
    return [
        page(
            group,
            index=index,
            count=len(groups),
            total=len(rows),
            rating_label=rating_label,
            season_name=season_name,
            updated_at=updated_at,
        )
        for index, group in enumerate(groups)
    ]


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
