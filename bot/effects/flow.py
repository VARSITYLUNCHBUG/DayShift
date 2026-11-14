"""Keeps a draft message, and the hero grid below it, at the bottom of a channel.

Every board uses this, ranked and scrim. The board message is edited in place while
it's still at the bottom, and posted again below any chat otherwise. The grid is posted afresh
each time, never edited: an edited message gets an "(edited)" tag, which would split the grid.

Post before deleting, so the flow is never missing. Old buttons stay safe in between: they carry
their step, and a stale click gets a polite refusal. Each old message goes as soon as its
replacement is recorded. If that delete fails, it's handed to a delete job of its own, which
retries without the old message's ID ever being lost. Only a crash in the moment between
recording and deleting can still leave one behind.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from bot.effects.gateway import ChannelGone, Gateway

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class FlowMessages:
    """Where the flow is now. `grid_ids` has one entry per grid slot, None where it's empty."""

    channel_id: int
    board_id: int | None
    grid_ids: tuple[int | None, ...]

    @property
    def last_id(self) -> int | None:
        """The bottom of the flow: the last grid message, or the board when there's no grid."""
        for message_id in reversed(self.grid_ids):
            if message_id is not None:
                return message_id
        return self.board_id


class FlowStore(Protocol):
    """Records the flow's message IDs as they change (a match's resources, a draft's row)."""

    async def save_board(self, message_id: int) -> None: ...

    async def save_grid(self, index: int, message_id: int | None) -> None: ...

    async def delete_later(self, channel_id: int, message_id: int) -> None:
        """Queue a delete that failed just now, as a job of its own."""
        ...


async def _delete(
    gateway: Gateway,
    store: FlowStore,
    channel_id: int,
    message_id: int,
    log_extra: dict[str, object],
) -> None:
    try:
        await gateway.delete_message(channel_id, message_id)
    except ChannelGone:
        raise
    except Exception:
        logger.warning(
            "Couldn't delete an old message; retrying apart", extra=log_extra, exc_info=True
        )
        await store.delete_later(channel_id, message_id)


async def at_bottom(gateway: Gateway, flow: FlowMessages) -> bool:
    last = flow.last_id
    return last is not None and await gateway.latest_message_id(flow.channel_id) == last


async def render(
    gateway: Gateway,
    store: FlowStore,
    flow: FlowMessages,
    board: Any,
    grid: Sequence[Any],
    *,
    log_extra: dict[str, object] | None = None,
) -> bool:
    """Show `board` with `grid` below it. Returns whether the board was posted anew.

    `grid` may hold no more messages than `flow` has slots.
    """
    extra = log_extra or {}
    if len(grid) > len(flow.grid_ids):
        # Only a roster far past today's would get here. Show what fits rather than nothing.
        logger.warning("Grid too big for its messages; showing the first ones", extra=extra)
        grid = grid[: len(flow.grid_ids)]
    in_place = False
    if flow.board_id is not None and await at_bottom(gateway, flow):
        try:
            await gateway.edit_view(flow.channel_id, flow.board_id, board)
        except ChannelGone:
            logger.info("The board was deleted; posting it again", extra=extra)
        else:
            in_place = True
    if not in_place:
        message_id = await gateway.send_view(flow.channel_id, board)
        await store.save_board(message_id)
        if flow.board_id is not None:
            await _delete(gateway, store, flow.channel_id, flow.board_id, extra)
    for index, old_id in enumerate(flow.grid_ids):
        if index < len(grid):
            await store.save_grid(index, await gateway.send_view(flow.channel_id, grid[index]))
        elif old_id is not None:
            await store.save_grid(index, None)
        if old_id is not None:
            await _delete(gateway, store, flow.channel_id, old_id, extra)
    return not in_place
