"""Keeps a draft message, and the hero grid below it, at the bottom of a channel.

Every board uses this, ranked and scrim. The board message is edited in place while it's still
in view, and posted again below any chat otherwise. The grid is edited in place too while its
messages keep their number, and only what changed is sent: a draft step that changes the board
alone costs one edit, not two grid posts and two deletes. A grid that grows or shrinks is posted
afresh, and so is a grid that would no longer sit straight under its board.

Post before deleting, so the flow is never missing. Old buttons stay safe in between: they carry
their step, and a stale click gets a polite refusal. Once every replacement is recorded, each old
message is handed to a delete job of its own, which runs in a lane of its own and retries
without the old message's ID ever being lost. Only a crash in the moment between recording and
queueing the delete can still leave one behind.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from bot.effects.gateway import ChannelGone, EditCapped, Gateway

logger = logging.getLogger(__name__)

# What each board message shows with its grid, by board message ID, and when it was drawn. A
# render that would draw the same thing, with the board still last, is skipped: no edit, no
# grid repost. Every few hours it draws anyway, which also notices a message someone deleted.
# A restart starts empty, so the startup reconcile draws every board once.
_SHOWN: dict[int, tuple[str, str, datetime]] = {}  # The board's and the grid's fingerprints.
RECHECK = timedelta(hours=3)


def digest(*views: Any) -> str:
    """A fingerprint of what views show: their components, custom IDs included."""
    payload = json.dumps([view.to_components() for view in views], sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def _shown(board_id: int | None) -> tuple[str, str] | None:
    """What the board and its grid were last drawn with, while that's recent enough to trust."""
    shown = _SHOWN.get(board_id) if board_id is not None else None
    if shown is None or datetime.now(UTC) - shown[2] >= RECHECK:
        return None
    return shown[0], shown[1]


def forget_shown() -> None:
    _SHOWN.clear()


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
        """Queue the delete of a replaced message, as a job of its own."""
        ...


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
    bottom: bool | None = None,
) -> bool:
    """Show `board` with `grid` below it. Returns whether the board was posted anew.

    `grid` may hold no more messages than `flow` has slots. `bottom` is whether the flow is
    still last in the channel, when the caller has just checked.
    """
    extra = log_extra or {}
    if len(grid) > len(flow.grid_ids):
        # Only a roster far past today's would get here. Show what fits rather than nothing.
        logger.warning("Grid too big for its messages; showing the first ones", extra=extra)
        grid = grid[: len(flow.grid_ids)]
    board_print, grid_print = digest(board), digest(*grid)
    if flow.board_id is not None and bottom is None:
        bottom = await at_bottom(gateway, flow)
    shown = _shown(flow.board_id)
    if bottom and shown == (board_print, grid_print):
        logger.debug("Board unchanged and still in view; nothing to do", extra=extra)
        return False
    in_place = False
    if flow.board_id is not None and bottom:
        if shown is not None and shown[0] == board_print:
            in_place = True  # Only the grid changed.
        else:
            try:
                await gateway.edit_view(flow.channel_id, flow.board_id, board)
            except ChannelGone:
                logger.info("The board was deleted; posting it again", extra=extra)
            except EditCapped:
                logger.info("The board is too old to edit again; posting it anew", extra=extra)
            else:
                in_place = True
    grid_done = False
    if in_place:
        grid_done = await _grid_in_place(
            gateway, flow, grid, unchanged=shown is not None and shown[1] == grid_print
        )
        if not grid_done and grid and not await at_bottom(gateway, flow):
            # A notice sits below the board: a grid posted now would land under it, apart from
            # its board. Post the board again, with the grid straight under it.
            in_place = False
    board_id = flow.board_id
    old_ids: list[int] = []
    if not in_place:
        board_id = await gateway.send_view(flow.channel_id, board)
        await store.save_board(board_id)
        if flow.board_id is not None:
            _SHOWN.pop(flow.board_id, None)
            old_ids.append(flow.board_id)
    if not grid_done:
        for index, old_id in enumerate(flow.grid_ids):
            if index < len(grid):
                await store.save_grid(index, await gateway.send_view(flow.channel_id, grid[index]))
            elif old_id is not None:
                await store.save_grid(index, None)
            if old_id is not None:
                old_ids.append(old_id)
    # The old messages go once the new ones are up and recorded, as jobs of their own: they go
    # one at a time at the pace Discord's delete bucket allows (5 every few seconds per channel),
    # and the board never waits on them.
    for old_id in old_ids:
        await store.delete_later(flow.channel_id, old_id)
    if board_id is not None:
        _SHOWN[board_id] = (board_print, grid_print, datetime.now(UTC))
    return not in_place


async def _grid_in_place(
    gateway: Gateway, flow: FlowMessages, grid: Sequence[Any], *, unchanged: bool
) -> bool:
    """Edit the grid where it is. False when it has to be posted afresh instead: it gained or
    lost a message, or one of its messages is gone or too old to edit."""
    present = [message_id for message_id in flow.grid_ids if message_id is not None]
    if present != list(flow.grid_ids[: len(grid)]) or len(present) != len(grid):
        return False
    if unchanged:
        return True
    try:
        for message_id, view in zip(present, grid, strict=True):
            await gateway.edit_view(flow.channel_id, message_id, view)
    except (ChannelGone, EditCapped):
        return False
    return True
