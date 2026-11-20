"""deadlock-api's scoreboard, posted as a reply under a match's results. Pure: no I/O."""

from __future__ import annotations

from typing import Any

from discord.ui import Container, LayoutView, Separator, TextDisplay

from bot.renderers import style
from league.services.api_results import MatchStats, StatsRow

FIG = "\u2007"  # As wide as a digit: pads the K/D/A so the numbers line up, as results.py does.
GAME_MODES = {1: "Standard match", 4: "Street Brawl"}
# (label, the row's field) for the best-in-the-match lines.
LEADERS = (
    ("kills", "kills"),
    ("damage", "damage"),
    ("souls", "souls"),
    ("assists", "assists"),
    ("healing", "healing"),
    ("objective", "objective"),
)


def k(value: int) -> str:
    """37000 -> 37k, 9200 -> 9.2k, 797 -> 797, rounded as the scoreboard shows them."""
    if value >= 9_950:
        return f"{round(value / 1000)}k"
    if value >= 1_000:
        return f"{value / 1000:.1f}k".replace(".0k", "k")
    return str(value)


def _duration(seconds: int | None) -> str:
    if seconds is None:
        return ""
    minutes, secs = divmod(seconds, 60)
    return f"{minutes}:{secs:02d}"


def team_block(rows: list[StatsRow], side: str, *, won: bool) -> str:
    kills = sum(row.kills for row in rows)
    souls = sum(row.souls for row in rows)
    trophy = "🏆 " if won else ""
    head = (
        f"{trophy}{style.side_emoji(side)} **{style.side_name(side)}** · {kills} kills · "
        f"{k(souls)} souls"
    )
    kdas = [f"{row.kills}/{row.deaths}/{row.assists}" for row in rows]
    width = max(map(len, kdas), default=0)
    lines = [head]
    for row, kda in zip(rows, kdas, strict=True):
        lines.append(f"> {FIG * (width - len(kda))}**{kda}** · {row.name} · {row.hero}")
        lines.append(
            f"> -# {k(row.souls)} souls · {k(row.damage)} damage · {k(row.objective)} objective"
            f" · {k(row.healing)} healing"
        )
    return "\n".join(lines)


def leaders(rows: list[StatsRow]) -> str:
    lines = ["**Best in the match**"]
    for label, field in LEADERS:
        top = max(rows, key=lambda row: getattr(row, field))
        lines.append(f"> **{k(getattr(top, field))} {label}** · {top.name} · {top.hero}")
    return "\n".join(lines)


def _title(stats: MatchStats) -> str:
    hk_souls, am_souls = (sum(row.souls for row in rows) for rows in (stats.hk, stats.am))
    if stats.winner:
        won = f": {style.side_emoji(stats.winner)} {style.side_name(stats.winner)} won"
        first, second = (am_souls, hk_souls) if stats.winner == "am" else (hk_souls, am_souls)
    else:
        won, first, second = "", hk_souls, am_souls
    details = [GAME_MODES.get(stats.game_mode or 0, "Match")]
    if stats.duration_s is not None:
        details.append(_duration(stats.duration_s))
    if stats.start_time:
        details.append(f"<t:{stats.start_time}:f>")  # Each reader's own time zone.
    details.append(f"souls {k(first)} to {k(second)}")
    return f"## Deadlock match {stats.deadlock_match_id}{won}\n-# {' · '.join(details)}"


def blocks(stats: MatchStats) -> list[str | None]:
    """The post's text blocks in order; None is a separator. The winners come first."""
    order = ("am", "hk") if stats.winner == "am" else ("hk", "am")
    rows = {"hk": stats.hk, "am": stats.am}
    out: list[str | None] = [_title(stats)]
    out += [team_block(rows[side], side, won=side == stats.winner) for side in order if rows[side]]
    everyone = stats.hk + stats.am
    if everyone:
        out += [None, leaders(everyone)]
    return out


def render_match_stats(stats: MatchStats) -> LayoutView:
    box: Container[Any] = Container(accent_colour=style.DONE_COLOUR)
    for block in blocks(stats):
        box.add_item(Separator() if block is None else TextDisplay(block))
    view = LayoutView(timeout=None)
    view.add_item(box)
    return view
