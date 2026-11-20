"""The FIFO queue. Every change takes the community row lock, so pops can never race joins.

Someone who joins and walks away would otherwise sit in the queue until it pops, miss the ready
check and get its cooldown. So a place lasts `queue_idle_minutes` (a runtime setting) from
joining. `queue_warn_minutes` before that, a "Still queueing?" DM asks them to press Keep me in,
which starts the clock again without moving them. Nobody answers: they're taken out, with no
penalty, and their place is held for 3 minutes like any leave. With the DM on, nobody is taken
out until it has been out for the full warning time, even after the bot was down.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import Count

from league.domain import copy
from league.domain.engine import LIVE
from league.domain.errors import InvalidAction
from league.domain.mode_schema import parse_mode
from league.models import Community, Match, MatchParticipant, Player, QueueEntry
from league.models.matches import MatchKind
from league.services import lobby, penalties, prio, runtime
from league.services.common import add_effect, lock_community, now, render_queue

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class QueueStatus:
    size: int
    position: int | None
    match_id: int | None


def _position(community: Community, player: Player) -> int | None:
    players = list(
        QueueEntry.objects.filter(community=community).values_list("player_id", flat=True)
    )
    return players.index(player.pk) + 1 if player.pk in players else None


@transaction.atomic
def join(community_id: int, player: Player) -> QueueStatus:
    community = lock_community(community_id)
    live = MatchParticipant.objects.filter(player=player, is_active=True).first()
    if live is not None:
        raise InvalidAction(f"You're already in match #{live.match_id}.")
    penalty = penalties.active_penalty(community, player)
    if penalty is not None:
        raise InvalidAction(penalties.refusal_text(community, player, penalty))
    if QueueEntry.objects.filter(community=community, player=player).exists():
        raise InvalidAction(copy.ALREADY_QUEUED)
    # A place held from leaving in the last few minutes puts them back where they were.
    joined_at = prio.joined_queue(community.pk, player)
    QueueEntry.objects.create(
        community=community, player=player, joined_at=joined_at, active_at=now()
    )
    render_queue(community)
    match = try_pop(community)
    if match is not None and match.participants.filter(player=player).exists():
        return QueueStatus(size=0, position=None, match_id=match.pk)
    return status(community, player)


@transaction.atomic
def leave(community_id: int, player: Player) -> None:
    community = lock_community(community_id)
    deleted, _ = QueueEntry.objects.filter(community=community, player=player).delete()
    if not deleted:
        raise InvalidAction(copy.NOT_QUEUED)
    prio.left_queue(community.pk, [player.discord_user_id])
    render_queue(community)


@transaction.atomic
def kick(community_id: int, player: Player) -> bool:
    community = lock_community(community_id)
    deleted, _ = QueueEntry.objects.filter(community=community, player=player).delete()
    if deleted:
        prio.drop_players(community.pk, [player.discord_user_id])
        render_queue(community)
    return bool(deleted)


@transaction.atomic
def clear(community_id: int) -> int:
    community = lock_community(community_id)
    deleted, _ = QueueEntry.objects.filter(community=community).delete()
    prio.drop_all(community.pk)
    render_queue(community)
    return deleted


def status(community: Community, player: Player) -> QueueStatus:
    live = MatchParticipant.objects.filter(player=player, is_active=True).first()
    return QueueStatus(
        size=QueueEntry.objects.filter(community=community).count(),
        position=_position(community, player),
        match_id=live.match_id if live else None,
    )


def try_pop(community: Community) -> Match | None:
    """Start a lobby if the queue is full and capacity allows. Requires the community lock."""
    mode = parse_mode(community.active_mode.body)
    # Only matches that still hold players: one whose result is reported waits on its captains,
    # but its game is over and its players are free.
    live = (
        Match.objects.filter(
            community=community,
            kind=MatchKind.RANKED,
            status__in=LIVE,
            participants__is_active=True,
        )
        .distinct()
        .count()
    )
    if live >= runtime.of(community).max_concurrent_matches:
        return None
    entries = list(
        QueueEntry.objects.filter(community=community).select_related("player")[: mode.lobby_size]
    )
    if len(entries) < mode.lobby_size:
        return None
    return lobby.create_match(community, entries)


def full_queues() -> list[int]:
    """The communities whose queue holds a full lobby, by a count taken without any lock.

    The deadline loop pops only these, so an empty or short queue costs it no lock and no
    count of live matches. `pop_if_ready` checks everything again under the lock, so a count
    that is already stale costs one pass at most: a queue that fills is seen on the next, and a
    full one stays here every pass until a match slot frees up for it.
    """
    counts = dict(
        QueueEntry.objects.order_by()
        .values("community")
        .annotate(entries=Count("pk"))
        .values_list("community", "entries")
    )
    if not counts:
        return []
    full = []
    bodies = Community.objects.filter(pk__in=counts).values_list("pk", "active_mode__body")
    for community_id, body in bodies:
        try:
            lobby_size = parse_mode(body).lobby_size
        except Exception:
            full.append(community_id)  # pop_if_ready reports the broken mode, as it always has.
            continue
        if counts[community_id] >= lobby_size:
            full.append(community_id)
    return sorted(full)


@transaction.atomic
def pop_if_ready(community_id: int) -> Match | None:
    return try_pop(lock_community(community_id))


# --- Idle timeout ----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IdleTimeout:
    idle: timedelta  # From joining or the last Keep me in to being taken out.
    warn: timedelta  # How long the check-in DM is out before that. Zero: no DM.

    def remove_at(self, entry: QueueEntry) -> datetime:
        """When this entry goes, if nobody presses Keep me in."""
        due = entry.active_at + self.idle
        if self.warn and entry.warned_at is not None:
            due = max(due, entry.warned_at + self.warn)
        return due


def idle_timeout(community_id: int) -> IdleTimeout | None:
    """This server's idle timeout, or None when it's turned off."""
    settings = runtime.of(community_id)
    if settings.queue_idle_minutes <= 0:
        return None
    idle = timedelta(minutes=settings.queue_idle_minutes)
    warn = timedelta(minutes=settings.queue_warn_minutes)
    return IdleTimeout(idle=idle, warn=warn if warn < idle else timedelta())


@transaction.atomic
def stay(community_id: int, player: Player) -> datetime | None:
    """Keep me in, on the check-in DM: the idle clock starts again, and their place doesn't
    move. Returns when they'd next be taken out, or None with the timeout off."""
    community = lock_community(community_id)
    entry = QueueEntry.objects.filter(community=community, player=player).first()
    if entry is None:
        raise InvalidAction(copy.NO_LONGER_QUEUED)
    entry.active_at = now()
    entry.warned_at = None
    entry.save(update_fields=["active_at", "warned_at"])
    timeout = idle_timeout(community.pk)
    return timeout.remove_at(entry) if timeout else None


def awaiting_check_in(entry_id: int) -> bool:
    """Whether a check-in DM is still worth sending: they're queued and haven't answered."""
    return QueueEntry.objects.filter(pk=entry_id, warned_at__isnull=False).exists()


def tick(moment: datetime) -> int:
    """Send the check-ins that are due and take out whoever let one run out. A failure in one
    server is logged and can't hold up another."""
    done = 0
    servers = QueueEntry.objects.order_by().values_list("community_id", flat=True).distinct()
    for community_id in list(servers):
        try:
            done += _expire_idle(community_id, moment)
        except Exception:
            logger.exception("Queue idle check failed", extra={"community": community_id})
    return done


@transaction.atomic
def _expire_idle(community_id: int, moment: datetime) -> int:
    timeout = idle_timeout(community_id)
    if timeout is None:
        return 0
    waiting = QueueEntry.objects.filter(community_id=community_id)
    out = waiting.filter(active_at__lte=moment - timeout.idle)
    warn = waiting.none()
    if timeout.warn:
        # Out only once the check-in has had its full time, so it always gets a fair chance.
        out = out.filter(warned_at__lte=moment - timeout.warn)
        warn = waiting.filter(
            active_at__lte=moment - timeout.idle + timeout.warn, warned_at__isnull=True
        )
    if not out.exists() and not warn.exists():
        return 0  # The common case, without taking the lock.

    community = lock_community(community_id)
    removed = list(out.select_related("player"))
    if removed:
        QueueEntry.objects.filter(pk__in=[entry.pk for entry in removed]).delete()
        user_ids = [entry.player.discord_user_id for entry in removed]
        prio.left_queue(community.pk, user_ids)  # Holds their place, like any leave.
        for entry in removed:
            logger.info(
                "Taken out of the queue: idle",
                extra={"community": community.pk, "player": entry.player_id},
            )
            add_effect(
                community,
                "queue_idle_removed",
                {
                    "discord_user_id": entry.player.discord_user_id,
                    "warned": entry.warned_at is not None,
                    "idle_minutes": int(timeout.idle.total_seconds() // 60),
                },
            )
        render_queue(community)

    warned = list(warn.select_related("player"))
    for entry in warned:
        entry.warned_at = moment
        add_effect(
            community,
            "queue_check_in",
            {
                "entry_id": entry.pk,
                "discord_user_id": entry.player.discord_user_id,
                "remove_at": timeout.remove_at(entry).isoformat(),
            },
        )
    QueueEntry.objects.filter(pk__in=[entry.pk for entry in warned]).update(warned_at=moment)
    return len(removed) + len(warned)
