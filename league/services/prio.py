"""Bebot's voice priority list (/priolist): who has waited longest in the Waiting Room.

It's a display for running inhouses by hand, alongside the match queue, and follows the match
lifecycle rather than every voice move:

- Joining the Waiting Room puts you on the list. Leaving starts a 5 minute grace period; come
  back in time and you keep your place.
- Being put in a match (as it pops, as a ready-check replacement, or subbing in) takes you off.
  While the match is live, your voice moves don't count.
- When the match ends, cleanup moves players still in its voice back to the Waiting Room, and
  the list is then caught up with everyone there, so they all go on the back. That's what Bebot's
  "recently played" timer did. A no-fault void counts the same way.

The Waiting Room is the one set up for the match queue (/setup), so there's nothing extra to
configure. Waits show as Discord timestamps, which count up on their own, so the list is only
re-rendered when it changes.
"""

from __future__ import annotations

import logging
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db import transaction

from league.models import Community, MatchParticipant, Player, PrioEntry
from league.services.common import now, request_render

logger = logging.getLogger(__name__)

GRACE_SECONDS = 300
RENDER_KIND = "render_prio"


def tracked_communities() -> list[Community]:
    return list(Community.objects.filter(waiting_room_channel_id__isnull=False))


def _in_match(user_ids: Collection[int]) -> set[int]:
    """Which of these Discord users are in a live match."""
    rows = MatchParticipant.objects.filter(
        is_active=True, player__discord_user_id__in=list(user_ids)
    )
    return set(rows.values_list("player__discord_user_id", flat=True))


def render(community_id: int) -> None:
    """Re-render the list's message, if there is one. Pending renders coalesce."""
    community = Community.objects.get(pk=community_id)
    if community.prio_channel_id:
        request_render(community, RENDER_KIND)


def set_display(community_id: int, channel_id: int) -> None:
    """/priolist: post a fresh list in this channel. A list posted elsewhere stops updating."""
    Community.objects.filter(pk=community_id).update(
        prio_channel_id=channel_id, prio_message_id=None
    )
    render(community_id)


def save_display(community_id: int, channel_id: int, message_id: int) -> None:
    """The list was posted. Ignored if /priolist moved it to another channel meanwhile."""
    Community.objects.filter(pk=community_id, prio_channel_id=channel_id).update(
        prio_message_id=message_id
    )


# --- Changes --------------------------------------------------------------------------------


def _join(community_id: int, user_id: int, name: str, moment: datetime) -> None:
    """In the Waiting Room: keep their place if they have one, else go on the back."""
    entry, created = PrioEntry.objects.select_for_update().get_or_create(
        community_id=community_id,
        discord_user_id=user_id,
        defaults={"display_name": name[:100] or str(user_id), "queued_at": moment},
    )
    if created:
        return
    entry.grace_until = None
    if name:
        entry.display_name = name[:100]
    entry.save(update_fields=["grace_until", "display_name"])


def _start_grace(community_id: int, user_ids: Collection[int], moment: datetime) -> int:
    return PrioEntry.objects.filter(
        community_id=community_id, discord_user_id__in=list(user_ids), grace_until__isnull=True
    ).update(grace_until=moment + timedelta(seconds=GRACE_SECONDS))


@transaction.atomic
def on_voice_state(
    community_id: int,
    waiting_room_id: int,
    user_id: int,
    name: str,
    before_id: int | None,
    after_id: int | None,
) -> None:
    """Someone moved in voice. Only moves into or out of the Waiting Room matter."""
    if waiting_room_id not in (before_id, after_id) or before_id == after_id:
        return
    if _in_match([user_id]):
        # Matched players are off the list wherever they go, until the match ends.
        drop_players(community_id, [user_id])
        return
    moment = now()
    if after_id == waiting_room_id:
        _join(community_id, user_id, name, moment)
    else:
        _start_grace(community_id, [user_id], moment)
    render(community_id)


def drop_players(community_id: int, user_ids: Collection[int]) -> None:
    """They've been put in a match, so they're off the list. Runs inside the match change."""
    deleted, _ = PrioEntry.objects.filter(
        community_id=community_id, discord_user_id__in=list(user_ids)
    ).delete()
    if deleted:
        render(community_id)


@transaction.atomic
def remove(community_id: int, user_id: int) -> bool:
    """/removeprio. False if they weren't on the list."""
    deleted, _ = PrioEntry.objects.filter(
        community_id=community_id, discord_user_id=user_id
    ).delete()
    if deleted:
        render(community_id)
    return bool(deleted)


@transaction.atomic
def reconcile(community_id: int, waiting: Mapping[int, str]) -> None:
    """Match the list to who is in the Waiting Room now.

    Runs at startup, for moves made while the bot was down, and after a match's cleanup: anyone
    already sitting in the Waiting Room got no voice event to put them back on. `waiting` maps
    the user IDs there to display names; a blank name is looked up from their player record.
    """
    moment = now()
    busy = _in_match(waiting)
    unnamed = [user_id for user_id, name in waiting.items() if not name]
    known = dict(
        Player.objects.filter(discord_user_id__in=unnamed).values_list(
            "discord_user_id", "display_name"
        )
    )
    for user_id, name in waiting.items():
        if user_id not in busy:
            _join(community_id, user_id, name or known.get(user_id, ""), moment)
    away = PrioEntry.objects.filter(community_id=community_id).exclude(
        discord_user_id__in=list(waiting)
    )
    _start_grace(community_id, list(away.values_list("discord_user_id", flat=True)), moment)
    if busy:
        drop_players(community_id, busy)
    render(community_id)


# --- Timers ---------------------------------------------------------------------------------


def tick(moment: datetime) -> int:
    """Take off anyone whose grace period has run out."""
    expired = PrioEntry.objects.filter(grace_until__lte=moment)
    changed = set(expired.values_list("community_id", flat=True))
    expired.delete()
    for community_id in changed:
        render(community_id)
    return len(changed)


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
    """Longest wait first. Anyone in a live match is left off, in case a move was missed."""
    entries = list(PrioEntry.objects.filter(community_id=community_id).order_by("queued_at", "id"))
    busy = _in_match([entry.discord_user_id for entry in entries])
    return PrioView(
        [
            PrioLine(entry.discord_user_id, entry.display_name, entry.queued_at, entry.grace_until)
            for entry in entries
            if entry.discord_user_id not in busy
        ]
    )
