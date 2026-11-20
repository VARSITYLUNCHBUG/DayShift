from __future__ import annotations

from datetime import datetime
from typing import Any

from discord import ButtonStyle
from discord.ui import ActionRow, Button, Container, Item, LayoutView, TextDisplay

from bot.renderers import style
from bot.routing import RouteButton
from league.services.boards import QueueView

MAX_NAMES_SHOWN = 30


def render_queue(view_model: QueueView) -> LayoutView:
    names = view_model.players[:MAX_NAMES_SHOWN]
    listing = "\n".join(f"{index}. {name}" for index, name in enumerate(names, start=1)) or "Empty"
    if len(view_model.players) > MAX_NAMES_SHOWN:
        listing += f"\n...and {len(view_model.players) - MAX_NAMES_SHOWN} more"
    needed = view_model.capacity - view_model.size
    heading = f"## Queue: {view_model.size}/{view_model.capacity}"
    if 0 < needed < view_model.capacity:
        heading += f" · {needed} more to start"
    box: Container[Any] = Container(
        TextDisplay(f"{heading}\n{listing}"),
        ActionRow(
            RouteButton("join", label="Join", style=ButtonStyle.success),
            RouteButton("leave", label="Leave", style=ButtonStyle.danger),
        ),
        accent_colour=style.QUEUE_COLOUR,
    )
    view = LayoutView(timeout=None)
    view.add_item(box)
    return view


# --- The idle check-in, by DM ------------------------------------------------------------------
# A DM has no server, so its buttons carry the server's community ID.


def render_check_in_dm(
    community_id: int, server: str, remove_at: datetime, queue_url: str | None
) -> LayoutView:
    """Asks someone who has sat in the queue a while whether they're still there."""
    text = (
        f"## Still queueing?\nYou've been in the **{server}** queue a while. Press **Keep me "
        f"in** to keep your place, or you'll be taken out {style.relative(remove_at)}.\n"
        "-# Being taken out costs nothing: no strike, no cooldown."
    )
    buttons: list[Item[Any]] = [
        RouteButton("queue_stay", 0, community_id, label="Keep me in", style=ButtonStyle.success),
        RouteButton("queue_leave", 0, community_id, label="Leave queue"),
    ]
    if queue_url:
        buttons.append(Button(label="Open queue", url=queue_url))
    view = LayoutView(timeout=None)
    view.add_item(
        Container(TextDisplay(text), ActionRow(*buttons), accent_colour=style.QUEUE_COLOUR)
    )
    return view


def render_idle_removed_dm(
    server: str, *, warned: bool, idle_minutes: int, queue_url: str | None
) -> LayoutView:
    """They were taken out of the queue for idling."""
    why = "You didn't answer the check-in" if warned else f"You'd been in it {idle_minutes} min"
    text = (
        f"## Taken out of the queue\n{why}, so you're out of the **{server}** queue. There's no "
        "penalty. Join again in the next 3 minutes and you get your place back."
    )
    items: list[Item[Any]] = [TextDisplay(text)]
    if queue_url:
        items.append(ActionRow(Button(label="Open queue", url=queue_url)))
    view = LayoutView(timeout=None)
    view.add_item(Container(*items, accent_colour=style.VOID_COLOUR))
    return view


def render_check_in_answered(text: str) -> LayoutView:
    """What the check-in turns into once it's answered, so its buttons can't be pressed again."""
    view = LayoutView(timeout=None)
    view.add_item(Container(TextDisplay(f"## Queue\n{text}"), accent_colour=style.VOID_COLOUR))
    return view
