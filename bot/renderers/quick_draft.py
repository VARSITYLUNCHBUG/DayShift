"""The standalone draft's messages in Bebot's look, and /randomdraft. Pure: no I/O.

The draft message comes first; while drafting, the hero grid follows in messages of its own, as
in the match flow. The draft ID rides in the custom_id's match slot.
"""

from __future__ import annotations

from typing import Any

import discord
from discord import ButtonStyle, SelectOption
from discord.ui import ActionRow, Container, LayoutView, MediaGallery, TextDisplay

from bot.renderers import grid, style
from bot.renderers.board import player_mention
from bot.routing import RouteButton, RouteSelect
from league.domain.engine import ARCHMOTHER, COINFLIP_LABELS, FIRST_PICK, HIDDEN_KING, LAST_PICK
from league.models.quick_drafts import QuickDraftStatus
from league.services.quick_drafts import (
    HeroChoice,
    HeroOption,
    QuickDraftState,
    RandomDraft,
)


def _mention(user_id: int | None, name: str) -> str:
    return player_mention(user_id) if user_id is not None else name


def _view(*items: discord.ui.Item[Any]) -> LayoutView:
    view = LayoutView(timeout=None)
    for item in items:
        view.add_item(item)
    return view


def _emoji_id(state_custom: bool, emoji_id: int | None) -> int | None:
    """Custom emojis only where the bot could use them when the draft started."""
    return emoji_id if state_custom else None


# --- Captains -------------------------------------------------------------------------------


def _captain_buttons(state: QuickDraftState) -> ActionRow[Any]:
    """Bebot's two Become Captain buttons. A claimed side's button is disabled."""
    return ActionRow(
        RouteButton(
            "qd_captain",
            state.id,
            "hk",
            label=f"Become {style.HIDDEN_KING} Captain",
            style=ButtonStyle.danger,
            disabled=state.hk_captain_id is not None,
            emoji=discord.PartialEmoji(name=style.HK_EMOJI),
        ),
        RouteButton(
            "qd_captain",
            state.id,
            "am",
            label=f"Become {style.ARCHMOTHER} Captain",
            style=ButtonStyle.primary,
            disabled=state.am_captain_id is not None,
            emoji=discord.PartialEmoji(name=style.AM_EMOJI),
        ),
    )


def _captains_wanted(state: QuickDraftState) -> LayoutView:
    lines = [f"## {style.draft_title(state.id)}", "Captains: claim a side."]
    for side in style.SIDES:
        _user_id, name = state.captain(side)
        lines.append(f"{style.side_emoji(side)} {style.side_name(side)}: {name or '-'}")
    box: Container[Any] = Container(TextDisplay("\n".join(lines)), accent_colour=style.HK_COLOUR)
    return _view(box, _captain_buttons(state))


# --- Coinflip -------------------------------------------------------------------------------

_CHOICE_STYLE = {
    FIRST_PICK: ButtonStyle.primary,
    LAST_PICK: ButtonStyle.primary,
    HIDDEN_KING: ButtonStyle.danger,
    ARCHMOTHER: ButtonStyle.primary,
}
_CHOICE_EMOJI = {HIDDEN_KING: style.HK_EMOJI, ARCHMOTHER: style.AM_EMOJI}


def _coinflip(state: QuickDraftState) -> LayoutView:
    title = f"### {style.COIN_EMOJI} Captain Coinflip"
    if not state.winner_choice:
        body = (
            f"**{state.coinflip_winner_name}** wins the flip!\n\n"
            f"{_mention(state.coinflip_winner_id, state.coinflip_winner_name)}, "
            "choose your preference:"
        )
    else:
        chose = COINFLIP_LABELS[state.winner_choice]
        body = (
            f"**{state.coinflip_winner_name}** chose: {chose}\n\n"
            f"{_mention(state.coinflip_loser_id, state.coinflip_loser_name)}, "
            "choose your preference:"
        )
    buttons = [
        RouteButton(
            "qd_coin",
            state.id,
            choice,
            label=COINFLIP_LABELS[choice],
            style=_CHOICE_STYLE[choice],
            emoji=(
                discord.PartialEmoji(name=_CHOICE_EMOJI[choice])
                if choice in _CHOICE_EMOJI
                else None
            ),
        )
        for choice in state.options
    ]
    box: Container[Any] = Container(
        TextDisplay(f"{title}\n{body}"), accent_colour=style.COINFLIP_COLOUR
    )
    return _view(box, ActionRow(*buttons))


def _coinflip_done(state: QuickDraftState) -> LayoutView:
    first = style.side_name(state.first_side)
    box: Container[Any] = Container(
        TextDisplay(
            f"### {style.COIN_EMOJI} Captain Coinflip - Complete\n"
            f"**{state.coinflip_winner_name}** chose: {COINFLIP_LABELS[state.winner_choice]}\n"
            f"**{state.coinflip_loser_name}** chose: {COINFLIP_LABELS[state.loser_choice]}\n\n"
            f"{style.HK_EMOJI} {style.HIDDEN_KING}: {state.hk_captain_name}\n"
            f"{style.AM_EMOJI} {style.ARCHMOTHER}: {state.am_captain_name}\n"
            f"{first} bans and picks first. Ready to start the draft!"
        ),
        accent_colour=style.COINFLIP_COLOUR,
    )
    start = RouteButton("qd_start", state.id, label="Start Draft", style=ButtonStyle.success)
    return _view(box, ActionRow(start))


# --- Hero draft -----------------------------------------------------------------------------


def _hero_text(choice: HeroChoice) -> str:
    emoji = style.hero_emoji_text(choice.unicode_emoji)
    return style.hero_line(emoji, choice.name, random_choice=choice.random_choice, auto=choice.auto)


def _captains(state: QuickDraftState, final: bool) -> str:
    rows = [f"{style.CAPTAIN_EMOJI} **Captains**"]
    for side in style.SIDES:
        user_id, name = state.captain(side)
        emoji = style.side_emoji(side)
        if not final and side == state.acting_side:
            timer = style.countdown(state.deadline_at)
            rows.append(f"{emoji} {_mention(user_id, name)} {state.step_action} a hero!{timer}")
        else:
            rows.append(f"{emoji} {name}")
    return "\n".join(rows)


def summary_text(state: QuickDraftState, *, final: bool) -> str:
    """Bebot's draft summary: captains, bans, then each side's heroes."""
    bans = [_hero_text(c) for c in state.actions if c.action == "ban"]
    parts = [
        _captains(state, final),
        "",
        f"{style.BAN_EMOJI} **Bans**",
        style.hero_list(bans),
    ]
    for side in style.SIDES:
        picks = [_hero_text(c) for c in state.actions if c.action == "pick" and c.side == side]
        parts += ["", f"{style.side_emoji(side)} **{style.side_name(side)}**"]
        parts.append(style.hero_list(picks))
    if final:
        parts += ["", "# GLHF"]
    else:
        parts += ["", style.timeline_block(state.steps, state.step_index)]
    return "\n".join(parts)


def _hero_button(state: QuickDraftState, hero: HeroOption) -> RouteButton:
    # Bebot's grey hero buttons. Taken heroes stay in place, greyed out, so nothing shifts.
    return RouteButton(
        "qd_hero",
        state.id,
        f"{state.step_index}.{hero.id}",
        label=hero.name[:80],
        style=ButtonStyle.secondary,
        disabled=hero.taken,
        emoji=grid.hero_emoji(_emoji_id(state.custom_emojis, hero.emoji_id), hero.unicode_emoji),
    )


def _random_button(state: QuickDraftState) -> RouteButton:
    return RouteButton(
        "qd_random",
        state.id,
        state.step_index,
        label="Random",
        style=ButtonStyle.primary,
        emoji=discord.PartialEmoji(name="🎲"),
    )


def _hero_selects(state: QuickDraftState) -> list[ActionRow[Any]]:
    """Only for a roster too big for the grid: dropdowns take far fewer components."""
    noun = "Ban" if state.step_action == "ban" else "Pick"
    options = [
        SelectOption(
            label=hero.name[:100],
            value=str(hero.id),
            emoji=grid.hero_emoji(
                _emoji_id(state.custom_emojis, hero.emoji_id), hero.unicode_emoji
            ),
        )
        for hero in state.available
    ]
    return [
        ActionRow(
            RouteSelect(
                "qd_pick",
                state.id,
                f"{state.step_index}.{index}",
                options=chunk,
                placeholder=f"{noun} a hero: {chunk[0].label} to {chunk[-1].label}"[:150],
            )
        )
        for index, chunk in enumerate(grid.chunks(options))
    ]


def render_grid(state: QuickDraftState) -> list[LayoutView]:
    """The hero grid below the draft message: every hero in place, 🎲 Random last."""
    if state.status != QuickDraftStatus.DRAFTING:
        return []
    random_row: ActionRow[Any] = ActionRow(_random_button(state))
    rows = [*grid.button_rows([_hero_button(state, hero) for hero in state.heroes]), random_row]
    if not grid.fits(rows):
        rows = [*_hero_selects(state), random_row]
    return grid.messages(rows)


def _drafting(state: QuickDraftState) -> LayoutView:
    title = f"## {style.draft_title(state.id, state.draft_name)}"
    box: Container[Any] = Container(
        TextDisplay(f"{title}\n{summary_text(state, final=False)}"),
        accent_colour=style.side_colour(state.acting_side or state.first_side),
    )
    return _view(box)


def _completed(state: QuickDraftState) -> LayoutView:
    last_side = state.steps[-1][1] if state.steps else state.first_side
    title = f"## {style.draft_title(state.id, state.draft_name)}"
    box: Container[Any] = Container(
        TextDisplay(f"{title}\n{summary_text(state, final=True)}"),
        accent_colour=style.side_colour(last_side),
    )
    if state.gif_url:
        box.add_item(MediaGallery(discord.MediaGalleryItem(state.gif_url)))
    return _view(box)


def render_draft(state: QuickDraftState) -> LayoutView:
    if state.status == QuickDraftStatus.CAPTAINS:
        return _captains_wanted(state)
    if state.status == QuickDraftStatus.COINFLIP:
        return _coinflip(state)
    if state.status == QuickDraftStatus.READY:
        return _coinflip_done(state)
    if state.status == QuickDraftStatus.DRAFTING:
        return _drafting(state)
    if state.status == QuickDraftStatus.COMPLETED:
        return _completed(state)
    return _view(TextDisplay("Draft stopped."))


# --- /randomdraft -------------------------------------------------------------------------


def _option_list(heroes: list[HeroOption]) -> str:
    return style.hero_list(
        [style.hero_line(style.hero_emoji_text(hero.unicode_emoji), hero.name) for hero in heroes]
    )


def render_random_draft(draft: RandomDraft) -> LayoutView:
    parts = [f"## {style.DRAFT_TITLE} (Random)"]
    for index, side in enumerate(style.SIDES):
        if index:
            parts.append("")
        parts += [
            f"{style.side_emoji(side)} **{style.side_name(side)}**",
            "**Bans:**",
            _option_list(draft.bans[side]),
            "**Picks:**",
            _option_list(draft.picks[side]),
        ]
    box: Container[Any] = Container(TextDisplay("\n".join(parts)), accent_colour=style.HK_COLOUR)
    return _view(box)
