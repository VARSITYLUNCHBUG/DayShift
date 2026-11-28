"""The database side of the outbox: fetching due work and recording what happened."""

from __future__ import annotations

import functools
import operator
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db.models import Q

from league.domain.engine import TIMED, Status
from league.models import (
    Community,
    Match,
    MatchParticipant,
    MatchResource,
    OutboxEffect,
)
from league.models.matches import MatchKind, ResourceKind
from league.models.outbox import EffectStatus
from league.services.common import (
    add_effect,
    now,
    render_board,
    render_queue,
)

MAX_ATTEMPTS = 8
MAX_BACKOFF_SECONDS = 300

# A board that moves just as a captain clicks could cost them a wrong ban, so chat only moves it
# once it's being pushed out of view, and then waits for a quiet moment. Non-stop chat can only hold
# that off for so long: 8 s, measured on live Discord against twelve players' worth of spam, keeps
# the board in view most of the time for about 6 requests a move in the hero draft (3 a move
# elsewhere), far inside Discord's 5 posts a second per channel. A message or two left below the
# board moves it much later, if nothing else has by then.
BOARD_MOVE_AFTER_MESSAGES = 3
BOARD_MOVE_QUIET_SECONDS = 5
BOARD_MOVE_MAX_WAIT_SECONDS = 8
BOARD_MOVE_IDLE_SECONDS = 3600


Lane = int | str
VOICE_SETUP_KINDS = frozenset({"create_team_voice", "team_move_player", "swap_team_voice"})
VOICE_KINDS = VOICE_SETUP_KINDS | {"restart_voice", "cleanup_voice"}
# deadlock-api calls: a slow or rate-limited answer (60 s reads, waits of minutes) must not hold
# up the match's board and notices, so they run in a lane of their own.
API_KINDS = frozenset({"create_api_lobby", "fetch_api_match_id", "check_match_api"})
# Replaced board and grid messages: deleted one at a time, which keeps them inside Discord's delete
# bucket, in a lane of their own so the board never waits on them.
DELETE_KINDS = frozenset({"delete_message"})


def cancel_voice_setup(match_id: int) -> None:
    """Cleanup must not sit behind a day-long setup retry or move players back afterwards."""
    OutboxEffect.objects.filter(
        match_id=match_id, kind__in=VOICE_SETUP_KINDS, status=EffectStatus.PENDING
    ).update(status=EffectStatus.SKIPPED, done_at=now())


def queue_voice_cleanup(match: Match) -> None:
    """The match's voice is finished: drop its pending setup, then queue the one cleanup."""
    cancel_voice_setup(match.pk)
    add_effect(
        match.community, "cleanup_voice", match=match, dedupe_key=f"cleanup_voice:{match.pk}"
    )


def lane_key(match_id: int | None, lane: str, kind: str, community_id: int) -> Lane:
    """Which effects must run in order with this one.

    A match's voice setup, moves and cleanup have a separate ordered lane, and so do its
    deadlock-api calls and the deletes of its replaced messages; its other effects share the
    main match lane, scrims included. Work
    outside a match runs in the lane it names (a server's staff alerts, say), or else one lane
    per kind and server, so a queue panel that keeps failing in one server never holds up
    another server or another kind of work.
    """
    if match_id is not None:
        if kind in VOICE_KINDS:
            return f"voice:{match_id}"
        if kind in API_KINDS:
            return f"api:{match_id}"
        if kind in DELETE_KINDS:
            return f"deletes:{match_id}"
        return match_id
    return lane or f"{kind}:{community_id}"


def lane_of(effect: OutboxEffect) -> Lane:
    return lane_key(effect.match_id, effect.lane, effect.kind, effect.community_id)


def _lane_filter(match_id: int | None, lane: str, kind: str, community_id: int) -> Q:
    """The effects in the same lane as this one, as a query (the database form of `lane_key`)."""
    if match_id is not None:
        for kinds in (VOICE_KINDS, API_KINDS, DELETE_KINDS):
            if kind in kinds:
                return Q(match_id=match_id, kind__in=kinds)
        return Q(match_id=match_id) & ~Q(kind__in=VOICE_KINDS | API_KINDS | DELETE_KINDS)
    if lane:
        return Q(match_id__isnull=True, lane=lane)
    return Q(match_id__isnull=True, lane="", kind=kind, community_id=community_id)


def due_by_match(limit: int = 200) -> list[list[OutboxEffect]]:
    """Due effects grouped by lane (see `lane_key`), so each lane runs its effects in order.

    An effect that has begun and isn't finished holds its lane: it is running, waiting on a
    retry, or waiting out a rate limit. Later effects of that lane wait for it, and are left out
    before the limit is applied, so a lane stuck behind a long wait can't fill the batch and keep
    every other lane's due work from being fetched.
    """
    moment = now()
    holding: dict[Lane, tuple[int, Q]] = {}
    held = OutboxEffect.objects.filter(
        Q(attempts__gt=0) | Q(started_at__isnull=False), status=EffectStatus.PENDING
    ).order_by("id")
    for match_id, lane, kind, community_id, effect_id in held.values_list(
        "match_id", "lane", "kind", "community_id", "id"
    ):
        key = lane_key(match_id, lane, kind, community_id)
        if key not in holding:
            holding[key] = (effect_id, _lane_filter(match_id, lane, kind, community_id))

    due = OutboxEffect.objects.filter(status=EffectStatus.PENDING, run_after__lte=moment)
    if holding:
        due = due.exclude(
            functools.reduce(
                operator.or_, (Q(id__gt=first) & same for first, same in holding.values())
            )
        )
    groups: dict[Lane, list[OutboxEffect]] = defaultdict(list)
    for effect in due.select_related("community", "match").order_by("id")[:limit]:
        key = lane_of(effect)
        first = holding.get(key)
        if first is not None and effect.pk > first[0]:
            continue  # Already left out above; a second check costs nothing.
        groups[key].append(effect)
    return list(groups.values())


def next_due_at(after: datetime) -> datetime | None:
    """The earliest pending effect due after `after`: a delayed render or a retry. The worker
    sleeps until then instead of polling for it (the pending index covers this).

    `after` is the moment taken before the worker's last look at what is due, not the time now:
    an effect that fell due between that look and this query was seen by neither, and is
    returned here, already due, so the worker looks again at once. One due by `after` was in
    that look, or waits on a busy lane or a retry, which wake the worker themselves."""
    return (
        OutboxEffect.objects.filter(status=EffectStatus.PENDING, run_after__gt=after)
        .order_by("run_after")
        .values_list("run_after", flat=True)
        .first()
    )


def mark_started(effect_id: int) -> bool:
    """Claim an effect before running it. False if it's no longer pending, so it shouldn't run.

    A render that has started has already read its state, so requests from now on stop
    coalescing into it (see `request_render`).
    """
    claimed = OutboxEffect.objects.filter(pk=effect_id, status=EffectStatus.PENDING).update(
        started_at=now()
    )
    return claimed > 0


def mark_done(effect_id: int, status: str = EffectStatus.DONE) -> None:
    OutboxEffect.objects.filter(pk=effect_id).update(status=status, done_at=now(), last_error="")


def mark_later(effect_id: int, seconds: float, why: str) -> None:
    """Run it again in `seconds`, as if it hadn't started: nothing failed, so no attempt is used
    and the rest of its lane carries on. For work waiting out someone else's rate limit."""
    OutboxEffect.objects.filter(pk=effect_id, status=EffectStatus.PENDING).update(
        run_after=now() + timedelta(seconds=max(seconds, 1)),
        started_at=None,
        last_error=why[:2000],
    )


def mark_rate_limited(effect_id: int, seconds: float, why: str) -> None:
    """Discord asked for a wait longer than the client sleeps through: run it again after that,
    with no attempt used, since a rate limit isn't a failure and a long-window bucket (a daily
    channel cap, say) can ask more than once. Unlike `mark_later` it keeps `started_at`, so its
    lane keeps waiting for it and the lane's effects stay in order (see `due_by_match`)."""
    OutboxEffect.objects.filter(pk=effect_id, status=EffectStatus.PENDING).update(
        run_after=now() + timedelta(seconds=max(seconds, 1)), last_error=why[:2000]
    )


def mark_retry(effect_id: int, error: str, wait_at_least: float = 0) -> str:
    """Back off and retry, or fail for good once attempts run out. Returns the new status.
    `wait_at_least` is how long Discord asked us to wait, for a rate limit."""
    effect = OutboxEffect.objects.get(pk=effect_id)
    effect.attempts += 1
    effect.last_error = error[:2000]
    if effect.attempts >= MAX_ATTEMPTS:
        effect.status = EffectStatus.FAILED
        effect.done_at = now()
    else:
        delay = max(min(2**effect.attempts, MAX_BACKOFF_SECONDS), wait_at_least)
        effect.run_after = now() + timedelta(seconds=delay)
    effect.save(update_fields=["attempts", "last_error", "status", "done_at", "run_after"])
    return effect.status


def retry_failed(effect_ids: list[int]) -> int:
    """Staff fixed what made these fail (a permission, a deleted channel): run them again from
    the first attempt. Only failed effects are touched. Returns how many were queued."""
    return OutboxEffect.objects.filter(pk__in=effect_ids, status=EffectStatus.FAILED).update(
        status=EffectStatus.PENDING, attempts=0, run_after=now(), done_at=None
    )


def mark_failed(effect_id: int, error: str) -> None:
    OutboxEffect.objects.filter(pk=effect_id).update(
        status=EffectStatus.FAILED, last_error=error[:2000], done_at=now()
    )


def record_resource(match_id: int, kind: str, discord_id: int) -> None:
    MatchResource.objects.update_or_create(
        match_id=match_id, kind=kind, defaults={"discord_id": discord_id, "deleted_at": None}
    )


def resource_id(match_id: int, kind: str) -> int | None:
    return (
        MatchResource.objects.filter(match_id=match_id, kind=kind, deleted_at__isnull=True)
        .values_list("discord_id", flat=True)
        .first()
    )


def resources(match_id: int) -> dict[str, int]:
    rows = MatchResource.objects.filter(match_id=match_id, deleted_at__isnull=True).exclude(
        kind=ResourceKind.NOTICE
    )
    return dict(rows.values_list("kind", "discord_id"))


def mark_resource_deleted(match_id: int, kind: str) -> None:
    MatchResource.objects.filter(match_id=match_id, kind=kind).update(deleted_at=now())


def record_notice(match_id: int, message_id: int) -> None:
    """A notice of ours is up, below the board. It counts towards moving the board as a chat
    message does, but until then the board stays put: a ping or two below it leaves it in view
    (see `notices_below_board`), and moving it would cost a post and a delete each time."""
    MatchResource.objects.create(match_id=match_id, kind=ResourceKind.NOTICE, discord_id=message_id)
    match = Match.objects.select_related("community").get(pk=match_id)
    _debounce_move(match.community, "move_board", BOARD_MOVE, match=match, notice=True)


# How many of our own notices may sit below the board before it moves back below them.
NOTICES_BELOW_BOARD = 2


def notices_below_board(match_id: int, after_id: int) -> frozenset[int]:
    """Our live notices below the board's flow, whose last message is `after_id`, when nobody
    has chatted since the board last moved: if the channel's last message is one of these, the
    board is still in view. Empty once anyone has chatted, or once there are more than
    NOTICES_BELOW_BOARD of them. (Discord's message IDs grow with time.)"""
    pending = OutboxEffect.objects.filter(
        match_id=match_id, kind="move_board", status=EffectStatus.PENDING, attempts=0
    ).first()
    if pending is not None and int(pending.payload.get("messages", 0)) != int(
        pending.payload.get("notices", 0)
    ):
        return frozenset()  # Someone chatted since the board last moved.
    below = [message_id for message_id in live_notices(match_id) if message_id > after_id]
    if not 0 < len(below) <= NOTICES_BELOW_BOARD:
        return frozenset()
    return frozenset(below)


def record_ready_dm(match_id: int, discord_user_id: int, message_id: int) -> None:
    """The player's Ready Up DM, so readying anywhere can take its button off."""
    MatchParticipant.objects.filter(
        match_id=match_id, player__discord_user_id=discord_user_id, is_active=True
    ).update(ready_dm_message_id=message_id)


READY_PING_KIND = "refresh_ready_ping"


def request_ready_ping(match: Match) -> None:
    """The ready check changed shape (missed players were removed): delete the ping if nobody is
    left to call. Coalesces."""
    from league.services.common import request_render

    request_render(match.community, READY_PING_KIND, match)


def record_ready_ping(match_id: int, message_id: int) -> None:
    """The lobby's "press Ready" ping. It's also a notice, so the next status change clears it."""
    MatchResource.objects.update_or_create(
        match_id=match_id,
        kind=ResourceKind.READY_PING,
        defaults={"discord_id": message_id, "deleted_at": None},
    )


def ready_ping(match_id: int) -> tuple[int | None, int | None, list[int]]:
    """(channel, message, players still to press Ready) for the ready ping, while it's live."""
    match = Match.objects.get(pk=match_id)
    message_id = (
        MatchResource.objects.filter(match_id=match_id, kind=ResourceKind.READY_PING)
        .values_list("discord_id", flat=True)
        .first()
    )
    if match.status != Status.READY_CHECK or message_id is None:
        return None, None, []
    still_live = MatchResource.objects.filter(
        match_id=match_id, kind=ResourceKind.NOTICE, discord_id=message_id, deleted_at__isnull=True
    ).exists()
    if not still_live:
        return None, None, []
    unready = MatchParticipant.objects.filter(
        match_id=match_id, is_active=True, ready_at__isnull=True
    ).values_list("player__discord_user_id", flat=True)
    return resource_id(match_id, ResourceKind.TEXT), message_id, list(unready)


def live_notices(match_id: int) -> list[int]:
    rows = MatchResource.objects.filter(
        match_id=match_id, kind=ResourceKind.NOTICE, deleted_at__isnull=True
    )
    return list(rows.order_by("id").values_list("discord_id", flat=True))


def mark_notice_deleted(match_id: int, message_id: int) -> None:
    MatchResource.objects.filter(
        match_id=match_id, kind=ResourceKind.NOTICE, discord_id=message_id
    ).update(deleted_at=now())


@dataclass(frozen=True, slots=True)
class MoveTiming:
    after_messages: int
    quiet_seconds: int
    max_wait_seconds: int
    idle_seconds: int


BOARD_MOVE = MoveTiming(
    BOARD_MOVE_AFTER_MESSAGES,
    BOARD_MOVE_QUIET_SECONDS,
    BOARD_MOVE_MAX_WAIT_SECONDS,
    BOARD_MOVE_IDLE_SECONDS,
)
# A scrim runs in an ordinary channel, which is busier than a match's own, and each move reposts
# three messages, so it waits for more chat before following it.
SCRIM_MOVE = MoveTiming(after_messages=5, quiet_seconds=5, max_wait_seconds=30, idle_seconds=600)


def board_channel(match_id: int) -> int | None:
    """Where a match's board is: its own text channel, or the public channel a scrim runs in."""
    text_id = resource_id(match_id, ResourceKind.TEXT)
    if text_id is not None:
        return text_id
    return (
        Match.objects.filter(pk=match_id, kind=MatchKind.SCRIM)
        .values_list("host_channel_id", flat=True)
        .first()
    )


@dataclass(frozen=True, slots=True)
class WatchedChannels:
    """The channels whose events the bot acts on. Everything else in the server is ignored
    without a trip to the database."""

    text: frozenset[int]  # Live match text channels and the channels scrims run in.
    voice: frozenset[int]  # Every Waiting Room, and live team voices.


def watched_channels() -> WatchedChannels:
    from league.domain.engine import SCRIM_LIVE

    live = MatchResource.objects.filter(deleted_at__isnull=True)
    text = set(live.filter(kind=ResourceKind.TEXT).values_list("discord_id", flat=True))
    hosts = Match.objects.filter(kind=MatchKind.SCRIM, status__in=SCRIM_LIVE).values_list(
        "host_channel_id", flat=True
    )
    text |= {channel_id for channel_id in hosts if channel_id is not None}
    voice = set(
        live.filter(kind__in=(ResourceKind.TEAM_A_VOICE, ResourceKind.TEAM_B_VOICE)).values_list(
            "discord_id", flat=True
        )
    )
    rooms = Community.objects.values_list("waiting_room_channel_id", flat=True)
    voice |= {channel_id for channel_id in rooms if channel_id is not None}
    return WatchedChannels(frozenset(text), frozenset(voice))


def note_chat(channel_id: int) -> None:
    """Count a chat message towards moving a match board, or a scrim's, back below it."""
    resource = (
        MatchResource.objects.filter(
            kind=ResourceKind.TEXT, discord_id=channel_id, deleted_at__isnull=True
        )
        .select_related("match__community")
        .first()
    )
    if resource is not None:
        match = resource.match
        _debounce_move(match.community, "move_board", BOARD_MOVE, match=match)
        return
    scrim = (
        Match.objects.filter(
            kind=MatchKind.SCRIM, host_channel_id=channel_id, status=Status.CHAMPION_DRAFT
        )
        .select_related("community")
        .first()
    )
    if scrim is not None and resource_id(scrim.pk, ResourceKind.BOARD_MESSAGE) is not None:
        _debounce_move(scrim.community, "move_board", SCRIM_MOVE, match=scrim)
    # Any other channel in the server: nothing to keep in view.


def _debounce_move(
    community: Community,
    kind: str,
    timing: MoveTiming,
    *,
    match: Match | None = None,
    lane: str | None = None,
    payload: dict[str, object] | None = None,
    notice: bool = False,
) -> None:
    """Move once chat is pushing the message out of view, after a quiet moment. Non-stop chat
    can only hold that off for so long; a message or two left below moves it much later.
    `notice`: the message is one of our own notices, counted apart as well."""
    moment = now()
    pending = OutboxEffect.objects.filter(
        match=match, lane=lane or "", kind=kind, status=EffectStatus.PENDING, attempts=0
    ).first()
    if pending is None:
        add_effect(
            community,
            kind,
            {**(payload or {}), "messages": 1, "notices": int(notice)},
            match=match,
            lane=lane,
            run_after=moment + timedelta(seconds=timing.idle_seconds),
        )
        return
    messages = int(pending.payload.get("messages", 0)) + 1
    pending.payload["messages"] = messages
    if notice:
        pending.payload["notices"] = int(pending.payload.get("notices", 0)) + 1
    if messages >= timing.after_messages:
        latest = moment + timedelta(seconds=timing.max_wait_seconds)
        move_by = datetime.fromisoformat(pending.payload.setdefault("move_by", latest.isoformat()))
        pending.run_after = min(moment + timedelta(seconds=timing.quiet_seconds), move_by)
    pending.save(update_fields=["payload", "run_after"])


def cancel_moves(kind: str, *, match_id: int | None = None, lane: str | None = None) -> None:
    """The message has just moved to the bottom, so chat before now no longer counts."""
    pending = OutboxEffect.objects.filter(
        lane=lane or "", kind=kind, status=EffectStatus.PENDING, attempts=0
    )
    if match_id is None:
        pending = pending.filter(match__isnull=True)
    else:
        pending = pending.filter(match_id=match_id)
    pending.update(status=EffectStatus.SKIPPED, done_at=now())


def cancel_board_moves(match_id: int) -> None:
    cancel_moves("move_board", match_id=match_id)


def on_voice_join(discord_user_id: int, joined_channel_id: int) -> tuple[int, int] | None:
    """A member joined a voice channel. Returns where to send them: (guild ID, channel ID), or None.

    - The Waiting Room is the lobby, so before teams are picked nobody is moved.
    - Joining your team's voice records that you've arrived.
    - Once teams have their own voice, the Waiting Room sends you on to yours only until you've
      arrived. After that, coming back to the Waiting Room (to requeue, say) leaves you there.

    Anyone else is left alone, wherever they are.
    """
    participant = (
        MatchParticipant.objects.filter(player__discord_user_id=discord_user_id, is_active=True)
        .select_related("match__community")
        .first()
    )
    if participant is None:
        return None
    match = participant.match
    channels = resources(match.pk)
    team_kind = {"A": ResourceKind.TEAM_A_VOICE, "B": ResourceKind.TEAM_B_VOICE}.get(
        participant.team
    )
    team_channel = channels.get(team_kind) if team_kind else None
    arrived = participant.voice_joined_at is not None
    if joined_channel_id == team_channel and not arrived:
        # Moved in by the bot or joined through the invite: either way, they've arrived.
        MatchParticipant.objects.filter(pk=participant.pk, voice_joined_at__isnull=True).update(
            voice_joined_at=now()
        )
        arrived = True
    target = team_channel
    if target is None or target == joined_channel_id:
        return None
    if joined_channel_id != match.community.waiting_room_channel_id or arrived:
        return None
    return match.community.discord_guild_id, target


def stale_resources() -> list[tuple[int, str, int]]:
    """Channels of finished matches whose delete effect has failed for good."""
    finished = Match.objects.filter(
        kind=MatchKind.RANKED, status__in=(Status.COMPLETED, Status.VOIDED), ended_at__isnull=False
    )
    failed = OutboxEffect.objects.filter(
        match__in=finished,
        kind__in=("cleanup_voice", "delete_text_channel"),
        status=EffectStatus.FAILED,
    ).values_list("match_id", flat=True)
    rows = MatchResource.objects.filter(
        match_id__in=failed,
        deleted_at__isnull=True,
        kind__in=("text", "team_a_voice", "team_b_voice"),
    )
    return list(rows.values_list("match_id", "kind", "discord_id"))


def request_reconcile() -> int:
    """After a restart: re-render everything live, in case Discord missed an update."""
    count = 0
    for community in Community.objects.all():
        render_queue(community)
        count += 1
    live = Match.objects.filter(status__in=TIMED).select_related("community")
    for match in live:
        render_board(match)
        count += 1
    return count


def prune_finished(older_than_days: int = 30) -> int:
    """Done effects are operational data, not history, so they don't need keeping for ever."""
    cutoff = now() - timedelta(days=older_than_days)
    deleted, _ = OutboxEffect.objects.filter(
        status__in=(EffectStatus.DONE, EffectStatus.SKIPPED), done_at__lt=cutoff
    ).delete()
    return deleted
