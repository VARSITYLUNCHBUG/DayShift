"""The #leaderboard channel's text, and a player's own line of it. Pure: no I/O."""

from __future__ import annotations

from league.services.leaderboards import Row

# Discord allows 2000 characters a message; leave room for the heading and code fences.
PAGE_CHARS = 1800
NAME_WIDTH = 18


def _name(name: str) -> str:
    cleaned = name.replace("`", "'")
    return cleaned if len(cleaned) <= NAME_WIDTH else cleaned[: NAME_WIDTH - 1] + "…"


def win_rate(value: float | None) -> str:
    return "-" if value is None else f"{value:.0%}"


def line(row: Row) -> str:
    record = f"{row.wins}-{row.losses}"
    return (
        f"{row.rank:>4}  {_name(row.name):<{NAME_WIDTH}} {row.rating:>6}  {record:>7}  "
        f"{win_rate(row.win_rate):>4}"
    )


def header(rating_label: str) -> str:
    return f"{'#':>4}  {'Player':<{NAME_WIDTH}} {rating_label:>6}  {'W-L':>7}  {'Win%':>4}"


def pages(rows: list[Row], rating_label: str, title: str) -> list[str]:
    """The table split over as many messages as it needs, the title on the first."""
    if not rows:
        return [f"## {title}\nNobody has played yet."]
    top = header(rating_label)
    chunks: list[list[str]] = [[]]
    size = 0
    for row in rows:
        text = line(row)
        if chunks[-1] and size + len(text) + 1 > PAGE_CHARS:
            chunks.append([])
            size = 0
        chunks[-1].append(text)
        size += len(text) + 1
    result = []
    for index, chunk in enumerate(chunks):
        body = "```\n" + "\n".join([top, *chunk]) + "\n```"
        result.append(f"## {title}\n{body}" if index == 0 else body)
    return result


def own_text(row: Row | None, total: int, rating_label: str, channel_id: int | None) -> str:
    where = f" Everyone's is in <#{channel_id}>." if channel_id else ""
    if row is None:
        return f"You're not on the leaderboard yet: play a match to get on it.{where}"
    record = f"{row.wins} wins, {row.losses} losses"
    return (
        f"**#{row.rank}** of {total}: **{row.rating}** {rating_label.lower()}, {record} "
        f"({win_rate(row.win_rate)} won).{where}"
    )
