"""Freezing a match's timers, and firing them on demand.

The league has no pause of its own: the sub hold (`held_seconds`) also blocks every action, so it
is never used here. A frozen match keeps its status and accepts every action; its deadlines are
pushed ten years out, so neither the bot's deadline loop nor `extend_past_due` fires them, and the
time each had left is saved in `FrozenTimer`. An action that sets a fresh deadline is caught by
`sweep`, which every control API request runs, and parked again with its full time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db import models, transaction

from devtools.errors import Conflict
from devtools.models import DevFlag, FrozenMatch, FrozenTimer
from league.domain.engine import TIMED
from league.models import EarlyLeave, Match, PlayerSwap, SubOffer, SubRequest
from league.models.matches import EarlyLeaveStatus
from league.models.subs import UNRESOLVED, OfferStatus
from league.models.swaps import SwapStatus
from league.services import deadlines, early_leave, subs, swaps
from league.services.common import lock_match, now, render_board

FROZEN_FOR = timedelta(days=3650)
# A deadline this far out was computed from one of ours (a sub hold started while frozen).
PUSHED = FROZEN_FOR / 2
PAUSE_ALL = "pause_all"

MODELS: dict[str, type[models.Model]] = {
    "match": Match,
    "subrequest": SubRequest,
    "suboffer": SubOffer,
    "earlyleave": EarlyLeave,
    "playerswap": PlayerSwap,
}


@dataclass(frozen=True, slots=True)
class Timer:
    model: str
    object_id: int
    field: str
    value: datetime | None


def _timers(match: Match) -> list[Timer]:
    """Every live deadline that belongs to the match."""
    rows = [Timer("match", match.pk, "deadline_at", match.deadline_at)]
    for request in SubRequest.objects.filter(match=match, status__in=UNRESOLVED):
        rows.append(Timer("subrequest", request.pk, "deadline_at", request.deadline_at))
        rows.append(Timer("subrequest", request.pk, "name_until", request.name_until))
    for offer in SubOffer.objects.filter(request__match=match, status=OfferStatus.PENDING):
        rows.append(Timer("suboffer", offer.pk, "deadline_at", offer.deadline_at))
    for leave in EarlyLeave.objects.filter(match=match, status=EarlyLeaveStatus.PENDING):
        rows.append(Timer("earlyleave", leave.pk, "deadline_at", leave.deadline_at))
    for swap in PlayerSwap.objects.filter(match=match, status=SwapStatus.PENDING):
        rows.append(Timer("playerswap", swap.pk, "deadline_at", swap.deadline_at))
    return rows


def _write(timer: Timer, value: datetime) -> None:
    MODELS[timer.model]._default_manager.filter(pk=timer.object_id).update(**{timer.field: value})


def paused_all() -> bool:
    return DevFlag.objects.filter(key=PAUSE_ALL).exists()


def is_frozen(match_id: int) -> bool:
    return FrozenMatch.objects.filter(match_id=match_id).exists()


def frozen_seconds_left(match_id: int) -> float | None:
    timer = FrozenTimer.objects.filter(
        model="match", object_id=match_id, field="deadline_at"
    ).first()
    return timer.remaining_seconds if timer else None


def _park(frozen: FrozenMatch, match: Match) -> None:
    """Push out every deadline not yet parked, saving the time it had left."""
    moment = now()
    saved = {(t.model, t.object_id, t.field): t for t in frozen.timers.all()}
    for timer in _timers(match):
        if timer.value is None:
            continue
        old = saved.get((timer.model, timer.object_id, timer.field))
        if old is not None and timer.value == old.pushed_to:
            continue
        if old is not None and timer.value - moment > PUSHED:
            remaining = old.remaining_seconds  # Derived from our own push: keep the real time.
        else:
            remaining = max(0.0, (timer.value - moment).total_seconds())
        pushed_to = moment + FROZEN_FOR
        FrozenTimer.objects.update_or_create(
            model=timer.model,
            object_id=timer.object_id,
            field=timer.field,
            defaults={"frozen": frozen, "remaining_seconds": remaining, "pushed_to": pushed_to},
        )
        _write(timer, pushed_to)
    # A sub hold that started while frozen measured its time left from the pushed-out deadline.
    # Put back what the hold would have saved without the freeze.
    if match.held_seconds is not None and match.held_seconds > PUSHED.total_seconds():
        left = saved.get(("match", match.pk, "deadline_at"))
        held = int(left.remaining_seconds) if left else subs.RESUME_MIN_SECONDS
        Match.objects.filter(pk=match.pk).update(held_seconds=held)


def _freeze_locked(match: Match) -> FrozenMatch:
    frozen, _ = FrozenMatch.objects.get_or_create(match=match, defaults={"frozen_at": now()})
    _park(frozen, match)
    return frozen


@transaction.atomic
def freeze(match_id: int) -> None:
    match = lock_match(match_id)
    if match.status not in TIMED:
        raise Conflict(f"Match #{match_id} is {match.status}: it has no timers to pause.")
    _freeze_locked(match)
    render_board(match)


def _thaw_locked(match: Match) -> None:
    frozen = FrozenMatch.objects.filter(match=match).first()
    if frozen is None:
        return
    _park(frozen, match)  # Catch anything set since the last sweep first.
    moment = now()
    current = {(t.model, t.object_id, t.field): t.value for t in _timers(match)}
    for timer in frozen.timers.all():
        key = (timer.model, timer.object_id, timer.field)
        if current.get(key) == timer.pushed_to:
            restored = moment + timedelta(seconds=timer.remaining_seconds)
            _write(Timer(*key, value=None), restored)
    frozen.delete()


@transaction.atomic
def resume(match_id: int) -> None:
    match = lock_match(match_id)
    if paused_all():
        raise Conflict("Every timer is paused. Resume them all instead (timers/resume).")
    _thaw_locked(match)
    render_board(match)


def refreeze(match_id: int) -> None:
    """Park any deadline an action just set on a frozen match."""
    with transaction.atomic():
        frozen = FrozenMatch.objects.filter(match_id=match_id).first()
        if frozen is None:
            return
        match = lock_match(match_id)
        if match.status not in TIMED:
            frozen.delete()
            return
        _park(frozen, match)


def sweep() -> None:
    """Keep frozen matches frozen, and freeze new ones while every timer is paused."""
    for match_id in list(FrozenMatch.objects.values_list("match_id", flat=True)):
        refreeze(match_id)
    if paused_all():
        frozen = FrozenMatch.objects.values_list("match_id", flat=True)
        unfrozen = Match.objects.filter(status__in=TIMED).exclude(pk__in=frozen)
        for match_id in list(unfrozen.values_list("pk", flat=True)):
            freeze(match_id)


@transaction.atomic
def pause_all() -> list[int]:
    DevFlag.objects.update_or_create(key=PAUSE_ALL, defaults={"value": {"at": now().isoformat()}})
    for match_id in Match.objects.filter(status__in=TIMED).values_list("pk", flat=True):
        freeze(match_id)
    return frozen_ids()


@transaction.atomic
def resume_all() -> list[int]:
    DevFlag.objects.filter(key=PAUSE_ALL).delete()
    for match_id in list(FrozenMatch.objects.values_list("match_id", flat=True)):
        resume(match_id)
    return frozen_ids()


def frozen_ids() -> list[int]:
    return sorted(FrozenMatch.objects.values_list("match_id", flat=True))


def _seconds_left(timer: Timer, saved: dict[tuple[str, int, str], FrozenTimer]) -> float:
    assert timer.value is not None
    old = saved.get((timer.model, timer.object_id, timer.field))
    if old is not None and timer.value == old.pushed_to:
        return old.remaining_seconds
    return (timer.value - now()).total_seconds()


@transaction.atomic
def fire(match_id: int) -> bool:
    """Run out the match's soonest timer now, as the deadline loop would. Returns whether
    anything happened. On a frozen match the deadlines it sets are frozen again."""
    match = lock_match(match_id)
    if match.status not in TIMED:
        raise Conflict(f"Match #{match_id} is {match.status}: it has no timer to fire.")
    frozen = FrozenMatch.objects.filter(match=match).first()
    saved = {(t.model, t.object_id, t.field): t for t in frozen.timers.all()} if frozen else {}
    live = [timer for timer in _timers(match) if timer.value is not None]
    if not live:
        raise Conflict(f"Match #{match_id} has no running timer.")
    soonest = min(live, key=lambda timer: _seconds_left(timer, saved))
    moment = now()
    _write(soonest, moment)
    if soonest.model == "match":
        fired = deadlines.fire_match_deadline(match_id)
    elif soonest.model == "earlyleave":
        fired = early_leave.tick(moment) > 0
    elif soonest.model == "playerswap":
        fired = swaps.tick(moment) > 0
    else:
        fired = subs.tick(moment) > 0
    if frozen is not None:
        refreeze(match_id)
    return fired
