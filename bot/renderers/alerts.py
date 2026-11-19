"""Staff alert cards. Pure: no I/O."""

from __future__ import annotations

import re
from typing import Any

from discord import ButtonStyle
from discord.ui import ActionRow, Container, LayoutView, TextDisplay

from bot.renderers import style
from bot.routing import RouteButton
from league.models.alerts import AlertKind, AlertStatus
from league.services.alerts import AlertCard

TITLES = {
    AlertKind.DISPUTE: "needs a decision",
    AlertKind.EARLY_LEAVE: "may have an early leave",
    AlertKind.API_MISMATCH: "doesn't match deadlock-api",
    AlertKind.API_ABANDON: "has an abandon on deadlock-api",
    AlertKind.OCR_MISMATCH: "doesn't match its scoreboard",
    AlertKind.AWARD_FREEZE: "froze an award share",
    AlertKind.LOBBY_FAILED: "couldn't be set up",
}


def _when(moment: Any) -> str:
    return f"<t:{int(moment.timestamp())}:R>"


def _title(card: AlertCard) -> str:
    subject = f"Match #{card.match_id}" if card.match_id is not None else "Staff alert"
    if card.status == AlertStatus.OPEN:
        return f"### ⚠️ {subject} {TITLES[card.kind]}"
    # Closed: say what it was, not what it needed.
    done = "resolved" if card.status == AlertStatus.RESOLVED else "dismissed"
    return f"### {'✅' if done == 'resolved' else '☑️'} {subject}: {card.kind.label}, {done}"


def _footer(card: AlertCard) -> str:
    parts = [card.area.label]
    if card.match_channel_id is not None:
        parts.append(f"<#{card.match_channel_id}>")
    parts.append(_when(card.created_at))
    return "-# " + " · ".join(parts)


def _closed_line(card: AlertCard) -> str:
    who = f" by {card.closed_by}" if card.closed_by else ""
    when = f" {_when(card.closed_at)}" if card.closed_at else ""
    verb = "Resolved" if card.status == AlertStatus.RESOLVED else "Dismissed"
    detail = f": {card.outcome}" if card.outcome and card.outcome != "Dismissed" else ""
    return f"**{verb}{who}**{when}{detail}"


def _buttons(card: AlertCard) -> ActionRow[Any]:
    match_id = card.match_id or 0
    if card.kind == AlertKind.DISPUTE:
        first, second = card.team_names
        return ActionRow(
            RouteButton(
                "resolve_a", match_id, label=f"{first} won"[:80], style=ButtonStyle.primary
            ),
            RouteButton(
                "resolve_b", match_id, label=f"{second} won"[:80], style=ButtonStyle.primary
            ),
            RouteButton("resolve_void", match_id, label="Void", style=ButtonStyle.danger),
        )
    dismiss = RouteButton("alert_dismiss", match_id, card.alert_id, label="Dismiss")
    if card.kind == AlertKind.EARLY_LEAVE and card.leaver_name:
        void = RouteButton(
            "early_leave_void",
            match_id,
            card.alert_id,
            label=f"Void: {card.leaver_name} left early"[:80],
            style=ButtonStyle.danger,
        )
        return ActionRow(void, dismiss)
    return ActionRow(dismiss)


def render_alert(card: AlertCard) -> LayoutView:
    is_open = card.status == AlertStatus.OPEN
    lines = [_title(card), card.text]
    if is_open and card.ping_role_ids:
        lines.append(" ".join(f"<@&{role_id}>" for role_id in card.ping_role_ids))
    if not is_open:
        lines.append(_closed_line(card))
    lines.append(_footer(card))
    colour = {
        AlertStatus.OPEN: style.ALERT_COLOUR,
        AlertStatus.RESOLVED: style.LOBBY_COLOUR,
        AlertStatus.DISMISSED: style.VOID_COLOUR,
    }[card.status]
    box: Container[Any] = Container(TextDisplay("\n".join(lines)), accent_colour=colour)
    if is_open:
        box.add_item(_buttons(card))
    view = LayoutView(timeout=None)
    view.add_item(box)
    return view


def match_notice(card: AlertCard) -> str:
    """The short note left in the match channel: staff have it, nobody is pinged. Sentences that
    tell staff which command to run stay on the staff card."""
    sentences = [part for part in re.split(r"(?<=[.!?])\s+", card.text) if "`/" not in part]
    return f"Sent to staff: {' '.join(sentences)}"
