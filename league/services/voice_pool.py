"""Each server's pool of team voice channels: the database side.

A match borrows two channels when its teams are set and hands them back when its voice is
finished, so a day of matches doesn't run into Discord's limit on creating channels. A slot is
busy while a live team voice `MatchResource` holds its channel; releasing it is marking that
resource deleted, as for a channel that really was deleted.

The bot side (granting the team, clearing overwrites, creating a channel when the pool is short)
is in `bot.effects.handlers`.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import IntegrityError, transaction

from league.models import Community, Match, MatchResource, VoiceChannelSlot
from league.models.matches import ResourceKind
from league.services import effects, runtime
from league.services.common import add_effect, lock_community, now

TEAM_VOICE_KINDS = (ResourceKind.TEAM_A_VOICE, ResourceKind.TEAM_B_VOICE)
# Channels made ahead of the first matches, so even a server's opening day creates none mid-match.
INITIAL_SIZE = 8
FILL_KIND = "fill_voice_pool"
# Two teams a match.
CHANNELS_PER_MATCH = 2


def target_size(community_id: int) -> int:
    """As many channels as the server can have matches running at once."""
    return CHANNELS_PER_MATCH * runtime.of(community_id).max_concurrent_matches


def _busy_ids() -> set[int]:
    return set(
        MatchResource.objects.filter(
            kind__in=TEAM_VOICE_KINDS, deleted_at__isnull=True
        ).values_list("discord_id", flat=True)
    )


def free_channels(community_id: int) -> list[int]:
    """The server's pooled channels no match is using, lowest number first."""
    slots = VoiceChannelSlot.objects.filter(community_id=community_id).order_by("number")
    busy = _busy_ids()
    return [
        channel_id
        for channel_id in slots.values_list("discord_id", flat=True)
        if channel_id not in busy
    ]


@dataclass(frozen=True, slots=True)
class Claim:
    """What `claim` found. `needed` is False if the match ended first: take nothing then."""

    needed: bool
    channel_id: int | None = None
    # How the channel's @everyone overwrite is set now, and how the server wants it.
    was_open: bool = False
    open_to_everyone: bool = False


def _voice_needed(match_id: int) -> bool:
    return Match.objects.filter(pk=match_id, participants__is_active=True).exists()


@transaction.atomic
def claim(match_id: int, kind: str, skip: frozenset[int] = frozenset()) -> Claim:
    """Give the match a free pooled channel as its `kind` team voice, if there is one.

    `skip` is channels to pass over: someone is still sitting in them, say. Claims in a server
    take turns on its row lock, so two matches can't take the same channel."""
    match = Match.objects.lock(match_id)
    wanted = runtime.of(match.community_id).open_match_voice
    if not _voice_needed(match_id):
        return Claim(needed=False)
    held = effects.resource_id(match_id, kind)
    if held is not None:
        return Claim(True, held, wanted, wanted)  # A retry: it's already this match's.
    lock_community(match.community_id)
    busy = _busy_ids() | skip
    slot = (
        VoiceChannelSlot.objects.filter(community_id=match.community_id)
        .exclude(discord_id__in=busy)
        .order_by("number")
        .first()
    )
    if slot is None:
        return Claim(needed=True)
    effects.record_resource(match_id, kind, slot.discord_id)
    return Claim(True, slot.discord_id, slot.open_to_everyone, wanted)


def note_open(channel_id: int, open_to_everyone: bool) -> None:
    """The channel's @everyone overwrite now follows the Open match voice setting."""
    VoiceChannelSlot.objects.filter(discord_id=channel_id).update(open_to_everyone=open_to_everyone)


def next_number(community_id: int, up_to: int | None = None) -> int | None:
    """The number for a new pooled channel, or None if the pool already has `up_to` channels
    (by default, all it can grow to): the caller makes a one-off channel instead, deleted after
    its match."""
    numbers = set(
        VoiceChannelSlot.objects.filter(community_id=community_id).values_list("number", flat=True)
    )
    size = target_size(community_id)
    if len(numbers) >= (size if up_to is None else min(up_to, size)):
        return None
    return next(n for n in range(1, len(numbers) + 2) if n not in numbers)


@transaction.atomic
def record_created(
    match_id: int, kind: str, channel_id: int, number: int | None, open_to_everyone: bool
) -> bool:
    """A channel was just made for this match: record it, and pool it under `number` if given.
    False if the match ended while Discord made it; its cleanup is queued.

    Recorded before cleanup is queued, so even a restart can't lose track of a late response.
    Another match that took the same number first leaves this one a one-off channel."""
    match = Match.objects.lock(match_id)
    effects.record_resource(match_id, kind, channel_id)
    if number is not None:
        lock_community(match.community_id)
        try:
            with transaction.atomic():
                VoiceChannelSlot.objects.create(
                    community_id=match.community_id,
                    number=number,
                    discord_id=channel_id,
                    open_to_everyone=open_to_everyone,
                )
        except IntegrityError:
            pass
    if not _voice_needed(match_id):
        effects.queue_voice_cleanup(match)
        return False
    return True


def is_pooled(channel_id: int) -> bool:
    return VoiceChannelSlot.objects.filter(discord_id=channel_id).exists()


def keep(community_id: int, channel_id: int) -> bool:
    """Whether a channel coming back from a match goes back in the pool. A one-off isn't pooled,
    and a pool bigger than the server needs now (Max concurrent matches was lowered) shrinks."""
    slot = VoiceChannelSlot.objects.filter(discord_id=channel_id).first()
    if slot is None:
        return False
    numbers = VoiceChannelSlot.objects.filter(community_id=community_id).values_list(
        "number", flat=True
    )
    size = target_size(community_id)
    # The highest numbers go first, so the pool stays Team Voice 1 to N.
    return sorted(numbers).index(slot.number) < size


def forget(channel_id: int) -> None:
    """The channel is gone (deleted by hand, or retired): take it out of the pool."""
    VoiceChannelSlot.objects.filter(discord_id=channel_id).delete()


@transaction.atomic
def drop_claim(match_id: int, kind: str, channel_id: int) -> None:
    """A claimed channel turned out to be gone from Discord: out of the pool, and off the match,
    so the caller can claim another."""
    forget(channel_id)
    MatchResource.objects.filter(
        match_id=match_id, kind=kind, discord_id=channel_id, deleted_at__isnull=True
    ).update(deleted_at=now())


@transaction.atomic
def add_free(community_id: int, number: int, channel_id: int, open_to_everyone: bool) -> None:
    """A channel made ahead of need joins the pool, free. If a match's new channel took the
    number meanwhile, this one gets the next free number; only its name is out of step."""
    lock_community(community_id)
    taken = set(
        VoiceChannelSlot.objects.filter(community_id=community_id).values_list("number", flat=True)
    )
    if number in taken:
        number = next(n for n in range(1, len(taken) + 2) if n not in taken)
    VoiceChannelSlot.objects.create(
        community_id=community_id,
        number=number,
        discord_id=channel_id,
        open_to_everyone=open_to_everyone,
    )


def request_fill(community: Community, size: int = INITIAL_SIZE) -> None:
    """Make channels until the pool has `size` (or all it can grow to, if that's fewer)."""
    add_effect(community, FILL_KIND, {"size": size}, lane=f"{FILL_KIND}:{community.pk}")
