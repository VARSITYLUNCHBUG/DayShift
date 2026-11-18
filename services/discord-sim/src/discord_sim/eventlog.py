"""A ring buffer of everything that happened: REST calls, gateway dispatches, control actions.

`/_sim/log` reads it as JSON and `/_sim/events` streams it as Server-Sent Events.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections import deque
from typing import Any

Entry = dict[str, Any]
# What a subscriber reads: an entry, or None when its stream should end.
Feed = asyncio.Queue[Entry | None]


class EventLog:
    def __init__(self, size: int) -> None:
        self._entries: deque[Entry] = deque(maxlen=size)
        self._seq = 0
        self._subscribers: set[Feed] = set()

    def add(self, kind: str, **fields: Any) -> Entry:
        self._seq += 1
        entry: Entry = {"seq": self._seq, "time": time.time(), "kind": kind, **fields}
        self._entries.append(entry)
        for queue in list(self._subscribers):
            if queue.full():
                # A reader that fell behind. Ending its stream makes the browser reconnect with
                # Last-Event-ID, and the replay from the ring buffer fills the gap.
                self._end(queue)
            else:
                queue.put_nowait(entry)
        return entry

    def since(self, seq: int = 0, limit: int = 500) -> list[Entry]:
        return [e for e in self._entries if e["seq"] > seq][:limit]

    @property
    def last_seq(self) -> int:
        return self._seq

    def subscribe(self) -> Feed:
        queue: Feed = asyncio.Queue(maxsize=1_000)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: Feed) -> None:
        self._subscribers.discard(queue)

    def close(self) -> None:
        """End every stream, so open /_sim/events requests don't hold up shutdown."""
        for queue in list(self._subscribers):
            self._end(queue)

    def _end(self, queue: Feed) -> None:
        self._subscribers.discard(queue)
        with contextlib.suppress(asyncio.QueueEmpty):
            while True:
                queue.get_nowait()
        queue.put_nowait(None)
