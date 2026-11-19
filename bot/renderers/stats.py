"""A player's /stats card. Pure: no I/O.

Laid out like the #leaderboard: no code blocks. The numbers are a quote block of bold labels and
values, the latest rating changes another, numbers first and padded with digit-wide spaces so they
line up. Standing, Steam and captaincy are sentences, so they're plain text between.
"""

from __future__ import annotations

from typing import Any

from discord.ui import Container, LayoutView, Separator, TextDisplay

from bot.renderers import style
from bot.renderers.leaderboard import FIGURE_SPACE, win_rate
from league.domain.copy import plural
from league.services.boards import PlayerStats


def _place(stats: PlayerStats) -> str:
    where = f" · {stats.season}" if stats.season else ""
    if stats.rank is None:
        return f"-# Not on the leaderboard yet{where}"
    return f"-# #{stats.rank} of {stats.ranked} on the leaderboard{where}"


def _numbers(stats: PlayerStats) -> str:
    rows: list[tuple[str, str]] = [(stats.rating_label, f"__{stats.rating}__")]
    if stats.games:
        record = f"{stats.wins}-{stats.losses}"
        rows.append(("Record", f"{record} · {win_rate(stats.wins / stats.games)} won"))
    rows.append(("Played", plural(stats.games, "match", "matches")))
    if stats.placement:
        rows.append(("Placement", stats.placement.removeprefix("placing ")))
    if stats.tier:
        rows.append(("Tier", stats.tier))
    if stats.mvps or stats.keys:
        rows.append(("Awards", f"🏅 {plural(stats.mvps, 'MVP')} · ⭐ {stats.keys} key"))
    if stats.avg_kda is not None:
        k, d, a = stats.avg_kda
        damage = f" · {stats.avg_damage / 1000:.1f}k damage" if stats.avg_damage else ""
        rows.append(("Scoreboards", f"{stats.scoreboards} · {k:.1f}/{d:.1f}/{a:.1f}{damage}"))
    return "\n".join(f"> **{label}** {value}" for label, value in rows)


def _recent(stats: PlayerStats) -> str:
    """The latest rating changes, newest first: "> **+56** · __1240__ · match #4"."""
    deltas = [f"{delta:+d}" for _match, delta, _after in stats.recent]
    afters = [str(after) for _match, _delta, after in stats.recent]
    delta_w = max(map(len, deltas), default=0)
    after_w = max(map(len, afters), default=0)
    lines = []
    for (match_id, _delta, _after), delta, after in zip(stats.recent, deltas, afters, strict=True):
        where = f"match #{match_id}" if match_id else "staff"
        lines.append(
            f"> {FIGURE_SPACE * (delta_w - len(delta))}**{delta}** · "
            f"{FIGURE_SPACE * (after_w - len(after))}__{after}__ · {where}"
        )
    return "**Recent changes**\n" + "\n".join(lines)


def render_stats(stats: PlayerStats, steam_line: str) -> LayoutView:
    items: list[Any] = [
        TextDisplay(f"## {stats.name}\n{_place(stats)}"),
        TextDisplay(_numbers(stats)),
    ]
    if stats.placement:
        items.append(TextDisplay("-# Your rating settles over your first matches."))
    items.append(Separator())
    items.append(
        TextDisplay(f"**Strikes** {stats.strikes}\n**Captain** {stats.captain}.\n{steam_line}")
    )
    if stats.recent:
        items.append(Separator())
        items.append(TextDisplay(_recent(stats)))
    view = LayoutView(timeout=None)
    view.add_item(Container(*items, accent_colour=style.BRAND_COLOUR))
    return view
