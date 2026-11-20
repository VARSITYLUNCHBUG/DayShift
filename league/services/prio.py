"""The priority list: who in the live queue has waited longest.

Only people in the match queue are on it. The Waiting Room is a public voice channel, and sitting
in it doesn't mean someone wants to play, so voice has nothing to do with the list:

- Joining the queue puts you on the back of the list.
- Leaving the queue holds your place for 3 minutes. Join again in time and you get your place
  back, on the list and in the queue. Or let it go, and it's gone at once.
- Being put in a match (as it pops, as a ready-check replacement, or subbing in) takes you off,
  as do staff removing you from the queue and a queue clear. After the match you queue again,
  so you go on the back.
- A cancelled lobby puts its ready players back in the queue at their old place, and back on the
  list at the same place.

The list decides who is offered an opening first (see `league.services.subs`). It isn't posted
anywhere: /prio shows each member their own place, privately.
"""

from __future__ import annotations

import logging
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db import transaction

from league.domain.errors import InvalidAction
from league.models import MatchParticipant, Player, PrioEntry
from league.services import live
from league.services.common import now

logger = logging.getLogger(__name__)

GRACE_SECONDS = 180


def _in_match(community_id: int, user_ids: Collection[int]) -> set[int]:
    """Which of these Discord users are in a live match in this server. A match elsewhere
    doesn't count: the bot can run in several servers, and players can be in more than one."""
    rows = MatchParticipant.objects.filter(
        is_active=True,
        match__community_id=community_id,
        player__discord_user_id__in=list(user_ids),
    )
    return set(rows.values_list("player__discord_user_id", flat=True))


# --- Changes, from the queue ------------------------------------------------------------------
# Each runs inside the queue change that caused it, under the community lock.


def joined_queue(community_id: int, player: Player) -> datetime:
    """They joined the queue. Returns their place: the one held for them if they left less than
    3 minutes ago, else now, the back of the list. The queue uses the same time."""
    moment = now()
    entry = (
        PrioEntry.objects.select_for_update()
        .filter(community_id=community_id, discord_user_id=player.discord_user_id)
        .first()
    )
    if entry is not None and (entry.grace_until is None or entry.grace_until > moment):
        entry.grace_until = None
        entry.display_name = player.display_name[:100] or entry.display_name
        entry.save(update_fields=["grace_until", "display_name"])
        live.publish(live.queue_topic(community_id))
        return entry.queued_at
    if entry is not None:
        entry.delete()  # Held, but the hold ran out before the timer got to it.
    PrioEntry.objects.create(
        community_id=community_id,
        discord_user_id=player.discord_user_id,
        display_name=player.display_name[:100] or str(player.discord_user_id),
        queued_at=moment,
    )
    live.publish(live.queue_topic(community_id))
    return moment


def left_queue(community_id: int, user_ids: Collection[int]) -> None:
    """They left the queue themselves: hold their place for 3 minutes."""
    PrioEntry.objects.filter(
        community_id=community_id, discord_user_id__in=list(user_ids), grace_until__isnull=True
    ).update(grace_until=now() + timedelta(seconds=GRACE_SECONDS))
    live.publish(live.queue_topic(community_id))


def requeued(community_id: int, places: Collection[tuple[Player, datetime]]) -> None:
    """A cancelled lobby put these players back in the queue at their old place."""
    for player, queued_at in places:
        PrioEntry.objects.update_or_create(
            community_id=community_id,
            discord_user_id=player.discord_user_id,
            defaults={
                "display_name": player.display_name[:100] or str(player.discord_user_id),
                "queued_at": queued_at,
                "grace_until": None,
            },
        )
    live.publish(live.queue_topic(community_id))


def drop_players(community_id: int, user_ids: Collection[int]) -> None:
    """Off the list now, with no place held: put in a match, or taken out of the queue by staff."""
    PrioEntry.objects.filter(community_id=community_id, discord_user_id__in=list(user_ids)).delete()
    live.publish(live.queue_topic(community_id))


def drop_all(community_id: int) -> None:
    """The queue was cleared."""
    PrioEntry.objects.filter(community_id=community_id).delete()
    live.publish(live.queue_topic(community_id))


@transaction.atomic
def let_go(community_id: int, player: Player) -> None:
    """They gave up the place held for them. Joining again later puts them on the back."""
    deleted, _ = PrioEntry.objects.filter(
        community_id=community_id,
        discord_user_id=player.discord_user_id,
        grace_until__gt=now(),
    ).delete()
    if not deleted:
        raise InvalidAction("You have no place held, so there's nothing to let go.")
    live.publish(live.queue_topic(community_id))


@transaction.atomic
def remove(community_id: int, user_id: int) -> bool:
    """/removeprio. False if they weren't on the list. They stay in the queue, at the back of
    the list's order for openings."""
    deleted, _ = PrioEntry.objects.filter(
        community_id=community_id, discord_user_id=user_id
    ).delete()
    if deleted:
        live.publish(live.queue_topic(community_id))
    return bool(deleted)


# --- Timers ---------------------------------------------------------------------------------


@transaction.atomic
def tick(moment: datetime) -> int:
    """Take off anyone whose hold has run out."""
    expired = PrioEntry.objects.select_for_update().filter(grace_until__lte=moment)
    communities = sorted(set(expired.values_list("community_id", flat=True)))
    deleted, _ = expired.delete()
    live.publish(*(live.queue_topic(community_id) for community_id in communities))
    return deleted


# --- Read model -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PrioLine:
    discord_user_id: int
    name: str
    queued_at: datetime
    grace_until: datetime | None = None


@dataclass(frozen=True, slots=True)
class PrioView:
    lines: list[PrioLine]


def prio_view(community_id: int) -> PrioView:
    """Longest wait first. Anyone in a live match is left off, in case a change was missed."""
    entries = list(PrioEntry.objects.filter(community_id=community_id).order_by("queued_at", "id"))
    busy = _in_match(community_id, [entry.discord_user_id for entry in entries])
    return PrioView(
        [
            PrioLine(entry.discord_user_id, entry.display_name, entry.queued_at, entry.grace_until)
            for entry in entries
            if entry.discord_user_id not in busy
        ]
    )


@dataclass(frozen=True, slots=True)
class PrioPlace:
    """One member's own place, for /prio."""

    position: int  # 1 is next in line.
    total: int
    queued_at: datetime
    held_until: datetime | None = None  # Set while their place is held after leaving.


def place_of(community_id: int, user_id: int) -> PrioPlace | None:
    """Where this member stands, or None if they aren't in the queue or holding a place."""
    lines = prio_view(community_id).lines
    for index, line in enumerate(lines, start=1):
        if line.discord_user_id == user_id:
            return PrioPlace(index, len(lines), line.queued_at, line.grace_until)
    return None
