"""Bebot's /randomdraft: a random ban and pick for both sides. Pure: no I/O."""

from __future__ import annotations

from typing import Any

from discord.ui import Container, LayoutView, TextDisplay

from bot.renderers import style
from league.services.scrims import RandomDraft, RandomHero


def _hero_list(heroes: list[RandomHero]) -> str:
    return style.hero_list(
        [
            style.hero_line(style.hero_emoji_text(hero.unicode_emoji, hero.emoji_id), hero.name)
            for hero in heroes
        ]
    )


def render_random_draft(draft: RandomDraft) -> LayoutView:
    parts = [f"## {style.DRAFT_TITLE} (Random)"]
    for index, side in enumerate(style.SIDES):
        if index:
            parts.append("")
        parts += [
            f"{style.side_emoji(side)} **{style.side_name(side)}**",
            "**Bans:**",
            _hero_list(draft.bans[side]),
            "**Picks:**",
            _hero_list(draft.picks[side]),
        ]
    box: Container[Any] = Container(TextDisplay("\n".join(parts)), accent_colour=style.HK_COLOUR)
    view = LayoutView(timeout=None)
    view.add_item(box)
    return view
