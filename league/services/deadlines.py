"""Timeouts go through the same transitions as clicks, recorded with `source = timeout`."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta

from django.db import transaction

from league import log_context
from league.domain.engine import TIMED, Status
from league.domain.errors import DomainError
from league.models import Match
from league.models.matches import MatchKind
from league.services import (
    draft,
    early_leave,
    lobby,
    prio,
    queue,
    results,
    scrims,
    subs,
    swaps,
)
from league.services.common import now

logger = logging.getLogger(__name__)

STARTUP_GRACE_SECONDS = 60

_HANDLERS = {
    Status.READY_CHECK: lobby.on_ready_timeout,
    Status.CAPTAIN_PHASE: lobby.on_captain_timeout,
    Status.CAPTAIN_CHECKIN: lobby.on_checkin_timeout,
    Status.PLAYER_DRAFT: draft.on_player_draft_timeout,
    Status.COINFLIP: draft.on_coinflip_timeout,
    Status.TEAM_CONFIRM: draft.on_team_confirm_timeout,
    Status.CHAMPION_DRAFT: draft.on_champion_draft_timeout,
    Status.LOBBY_CODE: draft.on_lobby_code_timeout,
    Status.IN_PROGRESS: results.on_in_progress_timeout,
    Status.AWAITING_CONFIRMATION: results.on_confirm_timeout,
    Status.DISPUTED: results.on_disputed_timeout,
}


def fire_match_deadline(match_id: int) -> bool:
    """Apply one match's timeout if it is still due. Returns whether anything happened."""
    with transaction.atomic():
        match = Match.objects.lock(match_id)
        # Re-check under the lock: a click may have got here first.
        if match.deadline_at is None or match.deadline_at > now() or match.status not in TIMED:
            return False
        if match.kind == MatchKind.SCRIM:
            scrims.on_timeout(match)
        else:
            _HANDLERS[match.status](match)
        return True


def tick() -> int:
    """One poller pass. A failure in one match is logged and cannot block the others."""
    moment = now()
    fired = 0
    due = Match.objects.filter(status__in=TIMED, deadline_at__lte=moment)
    for match_id, guild_id in due.values_list("pk", "community__discord_guild_id"):
        with log_context.bind(guild=guild_id, match=match_id):
            try:
                fired += 1 if fire_match_deadline(match_id) else 0
            except DomainError as exc:
                logger.info("Match deadline skipped", extra={"match": match_id, "why": exc.message})
            except Exception:
                logger.exception("Match deadline failed", extra={"match": match_id})

    fired += subs.tick(moment)
    fired += early_leave.tick(moment)
    fired += swaps.tick(moment)
    # Each of these can fail without stopping the others, or the queue pops below.
    fired += _side_tick("scrims", lambda _moment: scrims.tick(), moment)
    fired += _side_tick("priority list", prio.tick, moment)
    fired += _side_tick("queue idle timeout", queue.tick, moment)

    # Only full queues: each pop locks its community and counts its live matches again.
    for community_id in queue.full_queues():
        try:
            # A pop queues the lobby's effects, so it counts: the bot wakes its worker for it.
            fired += 1 if queue.pop_if_ready(community_id) is not None else 0
        except Exception:
            logger.exception("Queue pop failed", extra={"community": community_id})
    return fired


def extend_past_due(grace_seconds: int = STARTUP_GRACE_SECONDS) -> int:
    """After downtime, give everyone time to react rather than firing a burst of auto-picks."""
    moment = now()
    new_deadline = moment + timedelta(seconds=grace_seconds)
    count = Match.objects.filter(status__in=TIMED, deadline_at__lt=new_deadline).update(
        deadline_at=new_deadline
    )
    count += subs.extend_past_due(new_deadline)
    return count


def _side_tick(name: str, tick_fn: Callable[[datetime], int], moment: datetime) -> int:
    try:
        return tick_fn(moment)
    except Exception:
        logger.exception("Deadline pass failed", extra={"part": name})
        return 0
