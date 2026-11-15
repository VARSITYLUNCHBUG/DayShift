"""The database side of the outbox: fetching due work and recording what happened."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

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
# that off for so long. A message or two left below the board moves it much later, if nothing else
# has by then.
BOARD_MOVE_AFTER_MESSAGES = 3
BOARD_MOVE_QUIET_SECONDS = 5
BOARD_MOVE_MAX_WAIT_SECONDS = 20
BOARD_MOVE_IDLE_SECONDS = 3600


Lane = int | str


def lane_key(match_id: int | None, lane: str, kind: str, community_id: int) -> Lane:
    """Which effects must run in order with this one.

    A match's effects share its lane, scrims included. Work outside a match runs in the lane it
    names (a server's staff alerts, say), or else one lane per kind and server, so a queue panel
    that keeps failing in one server never holds up another server or another kind of work.
    """
    if match_id is not None:
        return match_id
    return lane or f"{kind}:{community_id}"


def lane_of(effect: OutboxEffect) -> Lane:
    return lane_key(effect.match_id, effect.lane, effect.kind, effect.community_id)


def due_by_match(limit: int = 200) -> list[list[OutboxEffect]]:
    """Due effects grouped by lane (see `lane_key`), so each lane runs its effects in order.

    If an earlier effect of a lane is waiting on a retry, later ones of that lane wait too.
    """
    moment = now()
    retrying: dict[Lane, int] = {}
    waiting = OutboxEffect.objects.filter(status=EffectStatus.PENDING, attempts__gt=0).order_by(
        "id"
    )
    for match_id, lane, kind, community_id, effect_id in waiting.values_list(
        "match_id", "lane", "kind", "community_id", "id"
    ):
        retrying.setdefault(lane_key(match_id, lane, kind, community_id), effect_id)

    groups: dict[Lane, list[OutboxEffect]] = defaultdict(list)
    due = (
        OutboxEffect.objects.filter(status=EffectStatus.PENDING, run_after__lte=moment)
        .select_related("community", "match")
        .order_by("id")[:limit]
    )
    for effect in due:
        key = lane_of(effect)
        blocker = retrying.get(key)
        if blocker is not None and effect.pk > blocker:
            continue
        groups[key].append(effect)
    return list(groups.values())


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


def mark_retry(effect_id: int, error: str) -> str:
    """Back off and retry, or fail for good once attempts run out. Returns the new status."""
    effect = OutboxEffect.objects.get(pk=effect_id)
    effect.attempts += 1
    effect.last_error = error[:2000]
    if effect.attempts >= MAX_ATTEMPTS:
        effect.status = EffectStatus.FAILED
        effect.done_at = now()
    else:
        delay = min(2**effect.attempts, MAX_BACKOFF_SECONDS)
        effect.run_after = now() + timedelta(seconds=delay)
    effect.save(update_fields=["attempts", "last_error", "status", "done_at", "run_after"])
    return effect.status


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
    MatchResource.objects.create(match_id=match_id, kind=ResourceKind.NOTICE, discord_id=message_id)


READY_PING_KIND = "refresh_ready_ping"


def request_ready_ping(match: Match) -> None:
    """Someone readied or left the ready check: refresh who the ping mentions. Coalesces."""
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
) -> None:
    """Move once chat is pushing the message out of view, after a quiet moment. Non-stop chat
    can only hold that off for so long; a message or two left below moves it much later."""
    moment = now()
    pending = OutboxEffect.objects.filter(
        match=match, lane=lane or "", kind=kind, status=EffectStatus.PENDING, attempts=0
    ).first()
    if pending is None:
        add_effect(
            community,
            kind,
            {**(payload or {}), "messages": 1},
            match=match,
            lane=lane,
            run_after=moment + timedelta(seconds=timing.idle_seconds),
        )
        return
    messages = int(pending.payload.get("messages", 0)) + 1
    pending.payload["messages"] = messages
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

    - Joining your match's lobby or team voice records that you've arrived.
    - The Waiting Room sends you on to your match's voice only until you've arrived. After that,
      coming back to the Waiting Room (to requeue, say) leaves you there.
    - The lobby voice always sends you on to your team's voice once teams have their own.

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
    lobby_channel = channels.get(ResourceKind.LOBBY_VOICE)
    match_voice = {channel for channel in (team_channel, lobby_channel) if channel is not None}
    arrived = participant.voice_joined_at is not None
    if joined_channel_id in match_voice and not arrived:
        # Moved in by the bot or joined through the invite: either way, they've arrived.
        MatchParticipant.objects.filter(pk=participant.pk, voice_joined_at__isnull=True).update(
            voice_joined_at=now()
        )
        arrived = True
    target = team_channel or lobby_channel
    if target is None or target == joined_channel_id:
        return None
    if joined_channel_id == lobby_channel:
        return match.community.discord_guild_id, target  # The lobby voice is on its way out.
    if joined_channel_id != match.community.waiting_room_channel_id or arrived:
        return None
    return match.community.discord_guild_id, target


def stale_resources() -> list[tuple[int, str, int]]:
    """Channels of finished matches whose delete effect has failed for good."""
    finished = Match.objects.filter(
        kind=MatchKind.RANKED, status__in=("completed", "voided"), ended_at__isnull=False
    )
    failed = OutboxEffect.objects.filter(
        match__in=finished,
        kind__in=("cleanup_voice", "delete_text_channel"),
        status=EffectStatus.FAILED,
    ).values_list("match_id", flat=True)
    rows = MatchResource.objects.filter(
        match_id__in=failed,
        deleted_at__isnull=True,
        kind__in=("text", "lobby_voice", "team_a_voice", "team_b_voice"),
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
