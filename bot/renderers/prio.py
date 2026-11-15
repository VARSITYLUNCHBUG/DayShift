"""What /prio tells a member about their own place. Pure: no I/O.

Times are Discord timestamps, so they count on the reader's screen.
"""

from __future__ import annotations

from datetime import datetime

from league.services.prio import PrioPlace


def _stamp(moment: datetime) -> str:
    return f"<t:{int(moment.timestamp())}:R>"


def place_text(place: PrioPlace | None, queue_channel_id: int | None) -> str:
    if place is None:
        where = f" Join it in <#{queue_channel_id}>." if queue_channel_id else ""
        return f"You're not in the queue, so you have no priority place.{where}"
    if place.held_until is not None:
        return (
            f"You left the queue. Your place, **#{place.position}** of {place.total}, is held "
            f"until {_stamp(place.held_until)}. Join again before then to keep it."
        )
    return (
        f"You're **#{place.position}** of {place.total} on the priority list, waiting since "
        f"{_stamp(place.queued_at)}."
    )
