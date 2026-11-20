"""What every service shares: the clock, writing outbox effects, and the side effects of a
transition. A match's own rules (its lock, mode, captains, transitions) live on the model."""

from __future__ import annotations

from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

from league.models import (
    Community,
    Match,
    OutboxEffect,
    Player,
    SubOffer,
)
from league.models.matches import MatchKind
from league.models.outbox import EffectStatus
from league.models.subs import UNRESOLVED, OfferStatus, SubStatus


def now() -> datetime:
    """The only clock services use, so tests can move time."""
    return timezone.now()


def seconds_from_now(seconds: float) -> datetime:
    return now() + timedelta(seconds=seconds)


def lock_community(community_id: int) -> Community:
    return Community.objects.select_for_update().get(pk=community_id)


def transition(
    match: Match,
    target: str,
    *,
    source: str,
    actor: Player | None = None,
    deadline_at: datetime | None = None,
) -> None:
    """Move a locked match to a new status (Match.record_transition), and clear its notices.

    Save it with `match.save_transition(...)`, alongside whatever else changed."""
    match.record_transition(target, source=source, actor=actor, deadline_at=deadline_at, at=now())
    clear_notices(match)


def add_effect(
    community: Community,
    kind: str,
    payload: dict[str, object] | None = None,
    *,
    match: Match | None = None,
    dedupe_key: str | None = None,
    run_after: datetime | None = None,
    lane: str | None = None,
) -> None:
    """Queue a Discord side effect. `lane` names the ordering lane for work outside a match."""
    if match is not None and kind in {"cleanup_voice", "restart_voice"}:
        from league.services.effects import cancel_voice_setup

        old_id = int(str((payload or {})["old_id"])) if kind == "restart_voice" else match.pk
        cancel_voice_setup(old_id)
    created_at = now()
    fields = {
        "community": community,
        "match": match,
        "kind": kind,
        "lane": lane or "",
        "payload": payload or {},
        "run_after": run_after or created_at,
        "created_at": created_at,
    }
    if dedupe_key is not None:
        OutboxEffect.objects.get_or_create(dedupe_key=dedupe_key, defaults=fields)
        return
    OutboxEffect.objects.create(**fields)


def request_render(
    community: Community,
    kind: str,
    match: Match | None = None,
    *,
    lane: str | None = None,
    payload: dict[str, object] | None = None,
    delay_seconds: float = 0,
) -> None:
    """Ask for a re-render. Renders read the latest state, so ones not yet started coalesce.
    `delay_seconds` holds a new render back a moment, so a burst of changes is one edit.

    One the worker has started may have read the state before this change, so it doesn't count.
    The row lock makes the worker's claim wait for this transaction, so either the claim comes
    first and a new render is added, or the render starts after this change has committed.
    A row another request holds is skipped rather than waited on: an extra render is harmless,
    and requests never queue behind each other's locks.

    Renders of something other than a match coalesce by `lane`, which names the thing rendered.
    """
    with transaction.atomic():
        unstarted = (
            OutboxEffect.objects.select_for_update(skip_locked=True)
            .filter(
                community=community,
                kind=kind,
                match=match,
                lane=lane or "",
                status=EffectStatus.PENDING,
                attempts=0,
                started_at__isnull=True,
            )
            .first()
        )
        if unstarted is None:
            run_after = seconds_from_now(delay_seconds) if delay_seconds else None
            add_effect(community, kind, payload, match=match, lane=lane, run_after=run_after)


def clear_notices(match: Match) -> None:
    """Remove the notices posted so far. Effects run in order, so later ones are unaffected."""
    if match.kind != MatchKind.SCRIM:  # A scrim posts no notices: its channel is public.
        add_effect(match.community, "clear_notices", match=match)


# Twelve Ready presses land within seconds, and each would edit the board. During the ready
# check a short wait folds them into a few edits; every other step renders at once.
READY_BOARD_DELAY_SECONDS = 1.0


def render_board(match: Match) -> None:
    from league.domain.engine import Status

    delay = READY_BOARD_DELAY_SECONDS if match.status == Status.READY_CHECK else 0
    request_render(match.community, "render_board", match, delay_seconds=delay)


# Joins and leaves come in bursts as a match pops or finishes, and Discord allows a channel about
# five edits every five seconds. A one-second window folds a burst into one edit and keeps a
# sustained rush at that limit, rather than leaning on 429s, which count toward Cloudflare's ban.
QUEUE_RENDER_DELAY_SECONDS = 1.0


def render_queue(community: Community) -> None:
    request_render(community, "render_queue", delay_seconds=QUEUE_RENDER_DELAY_SECONDS)


def close_subs(match: Match) -> None:
    """End every unfinished sub request, for a match that is ending or has its result in.

    Leaves the timer to the caller, which is about to replace it with a transition.
    """
    moment = now()
    pending = SubOffer.objects.filter(request__match=match, status=OfferStatus.PENDING)
    for offer_id in pending.values_list("pk", flat=True):
        add_effect(match.community, "close_sub_offer", {"offer_id": offer_id}, match=match)
    pending.update(status=OfferStatus.WITHDRAWN, resolved_at=moment)
    match.sub_requests.filter(status__in=UNRESOLVED).update(
        status=SubStatus.CANCELLED, resolved_at=moment
    )
    if match.held_seconds is not None:
        match.held_seconds = None
        match.save(update_fields=["held_seconds"])
