"""The bot's one look, Bebot's: side names, emojis, the colours of every screen, the turn strip.

Ported from Bebot's bot/config/ui.py and bot/utils.py, so every screen reads the way the
community knows it. Every renderer takes its colours from here. Pure: no I/O.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

HIDDEN_KING = "The Hidden King"
ARCHMOTHER = "The Archmother"
HK_EMOJI = "🔶"
AM_EMOJI = "🔷"
BAN_EMOJI = "🚫"
CAPTAIN_EMOJI = "👑"
COIN_EMOJI = "🪙"
DRAFT_TITLE = "🏆 Draft 🏆"
# Bebot's colours: discord.Color.orange() and .blue() for each side's turn, purple for the
# coinflip, blue for the queue and priority list, green for the lobby and a finished draft.
HK_COLOUR = 0xE67E22
AM_COLOUR = 0x3498DB
COINFLIP_COLOUR = 0x800080
QUEUE_COLOUR = AM_COLOUR
PRIO_COLOUR = AM_COLOUR
LOBBY_COLOUR = 0x2ECC71
DONE_COLOUR = 0x00FF00
# Ours, in the same discord.Color family: a step waiting on someone, a void, a staff alert.
ATTENTION_COLOUR = 0xF1C40F
VOID_COLOUR = 0x95A5A6
ALERT_COLOUR = 0xE74C3C
# DayShift's own bubblegum, for the league's own pages: the leaderboard and a player's stats.
BRAND_COLOUR = 0xFF8DC3
# No real timer runs this long. One further out was paused by the dev tools, which park
# deadlines ten years ahead; say so instead of "in 10 years".
PAUSED_BEYOND = timedelta(days=365)
# What Bebot appended to a hero chosen for the captain.
RANDOM_CHOICE = " (random choice)"
RANDOMED = " (randomed)"
TIMELINE_RULE = "─────────────────────────────────────"

SIDES = ("hk", "am")


def side_name(side: str) -> str:
    return HIDDEN_KING if side == "hk" else ARCHMOTHER


def side_emoji(side: str) -> str:
    return HK_EMOJI if side == "hk" else AM_EMOJI


def side_colour(side: str) -> int:
    return HK_COLOUR if side == "hk" else AM_COLOUR


def draft_title(number: int, name: str = "") -> str:
    return f"🏆 Draft #{number}: {name} 🏆" if name else f"🏆 Draft #{number} 🏆"


def is_paused(moment: datetime) -> bool:
    return moment - datetime.now(UTC) > PAUSED_BEYOND


def relative(moment: datetime, fmt: str = "R") -> str:
    """A Discord timestamp ("in 40 seconds"), or "paused" for a timer the dev tools parked."""
    if fmt == "R" and is_paused(moment):
        return "(paused)"
    return f"<t:{int(moment.timestamp())}:{fmt}>"


def countdown(deadline_at: datetime | None) -> str:
    """Bebot's " ⌛ 40s remaining", as a timestamp Discord counts down without edits."""
    if deadline_at is None:
        return ""
    return f" ⌛ {relative(deadline_at)}"


def hero_emoji_text(unicode_emoji: str) -> str:
    """The emoji to show before a hero's name in text: its plain emoji, or nothing.

    Never a custom emoji: in message text Discord only draws one if the bot is in the server that
    owns it, and the hero emojis belong to Bebot's server, so others see a bare ":mina:". Buttons
    are different: they reference the emoji by ID and draw it anywhere.
    """
    return unicode_emoji


def hero_line(emoji: str, name: str, *, random_choice: bool = False, auto: bool = False) -> str:
    suffix = RANDOM_CHOICE if random_choice else RANDOMED if auto else ""
    return f"{emoji} {name}{suffix}".strip()


def hero_list(lines: Sequence[str]) -> str:
    """Bebot printed "None" for an empty list, and so do we."""
    return "\n".join(lines) if lines else "None"


def timeline(steps: Sequence[tuple[str, str]], current: int | None) -> str:
    """Bebot's turn strip: bans on one line, picks on the next, the current turn in brackets.

    `steps` is (action, side) for each ban or pick, in order. A faithful port of Bebot's
    generate_turn_str, spacing quirks included, so the strip lines up as players remember it.
    """
    ban_parts: list[str] = []
    pick_parts: list[str] = []
    last_action: str | None = None
    first_pick_seen = False
    first_ban_after_pick_seen = False
    in_second_ban = False
    for index, (action, side) in enumerate(steps):
        emoji = side_emoji(side)
        if index == current:
            emoji = f"[{emoji}]"
        if last_action is not None and last_action != action:
            if not first_pick_seen and action != "ban":
                ban_parts.append("  ")
                pick_parts.append("  ")
                first_pick_seen = True
            elif first_pick_seen and not first_ban_after_pick_seen and action == "ban":
                ban_parts.append("    ")
                pick_parts.append("")
                first_ban_after_pick_seen = True
                in_second_ban = True
        if action == "ban":
            ban_parts.append(emoji)
            pick_parts.append(" " * len(emoji))
        else:
            if in_second_ban:
                pick_parts.append(" " * len(emoji))
                in_second_ban = False
            pick_parts.append(emoji)
            ban_parts.append(" " * len(emoji))
        last_action = action
    ban_str = "".join(ban_parts).rstrip()
    pick_str = "".join(pick_parts).rstrip()
    if any(char != " " for char in ban_str):
        return f"Bans\n{ban_str}\n{TIMELINE_RULE}\nPicks\n{pick_str}"
    emojis = [side_emoji(side) for _action, side in steps]
    if current is not None and 0 <= current < len(emojis):
        emojis[current] = f"[{emojis[current]}]"
    return " ".join(emojis)


def timeline_block(steps: Sequence[tuple[str, str]], current: int | None) -> str:
    return f"```\n{timeline(steps, current)}\n```"
