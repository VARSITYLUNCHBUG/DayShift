"""Bebot's named channel pings: /pingchannel sets one up, /ping sends it, with a cooldown."""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db import transaction

from league.domain.errors import InvalidAction, NotAllowed
from league.models import ChannelPing
from league.services.common import now

MAX_TARGETS = 10
_TOKEN = re.compile(r"<@&(?P<role>\d+)>|<@!?(?P<user>\d+)>")


@dataclass(frozen=True, slots=True)
class Targets:
    role_ids: list[int]
    user_ids: list[int]


def parse_targets(mention: str) -> Targets:
    """Role and user mentions only, separated by spaces. Anything else is refused, so a ping
    can't carry @everyone, @here or text that only looks like a mention."""
    roles: list[int] = []
    users: list[int] = []
    rest = _TOKEN.sub(" ", mention)
    if rest.strip():
        raise InvalidAction(
            "Mention roles or members only, like @PUGS. Pick them from the mention list as you "
            "type; @everyone, @here and plain text aren't allowed."
        )
    for found in _TOKEN.finditer(mention):
        if found["role"]:
            roles.append(int(found["role"]))
        else:
            users.append(int(found["user"]))
    roles, users = list(dict.fromkeys(roles)), list(dict.fromkeys(users))
    if not roles and not users:
        raise InvalidAction("Mention at least one role or member.")
    if len(roles) + len(users) > MAX_TARGETS:
        raise InvalidAction(f"A ping can mention at most {MAX_TARGETS} roles and members.")
    return Targets(roles, users)


def _clean_name(name: str) -> str:
    cleaned = " ".join(name.split()).lower()
    if not cleaned:
        raise InvalidAction("The name can't be empty.")
    if len(cleaned) > 50:
        raise InvalidAction("Keep the name to 50 characters.")
    return cleaned


def add(
    community_id: int,
    channel_id: int,
    name: str,
    targets: Targets,
    timer_minutes: int,
    required_role_id: int | None,
) -> ChannelPing:
    """Add a ping, or replace the one with the same name in this channel."""
    if not 1 <= timer_minutes <= 7 * 24 * 60:
        raise InvalidAction("The cooldown must be between 1 minute and 7 days.")
    ping, _created = ChannelPing.objects.update_or_create(
        channel_id=channel_id,
        name=_clean_name(name),
        defaults={
            "community_id": community_id,
            "role_ids": targets.role_ids,
            "user_ids": targets.user_ids,
            "timer_minutes": timer_minutes,
            "required_role_id": required_role_id,
            "last_ping_at": None,
        },
    )
    return ping


def remove(community_id: int, channel_id: int, name: str) -> bool:
    deleted, _ = ChannelPing.objects.filter(
        community_id=community_id, channel_id=channel_id, name=_clean_name(name)
    ).delete()
    return bool(deleted)


def in_channel(channel_id: int) -> list[ChannelPing]:
    return list(ChannelPing.objects.filter(channel_id=channel_id).order_by("name"))


def ready_at(ping: ChannelPing) -> datetime | None:
    """When the ping can next be sent, or None if it can be now."""
    if ping.last_ping_at is None:
        return None
    moment = ping.last_ping_at + timedelta(minutes=ping.timer_minutes)
    return moment if moment > now() else None


def _options(rows: list[ChannelPing]) -> str:
    return ", ".join(f"`{row.name}`" for row in rows)


@dataclass(frozen=True, slots=True)
class Claim:
    """A ping cleared to send. `previous` is the cooldown it replaced, to undo a failed send."""

    ping: ChannelPing
    claimed_at: datetime
    previous: datetime | None


@transaction.atomic
def claim(channel_id: int, name: str | None, role_ids: Collection[int]) -> Claim:
    """Check a /ping and start its cooldown, under a lock so two at once can't both go out."""
    rows = list(ChannelPing.objects.select_for_update().filter(channel_id=channel_id))
    if not rows:
        raise InvalidAction("This channel has no pings. Staff can add one with /pingchannel.")
    if name is None:
        if len(rows) > 1:
            raise InvalidAction(f"Pick which ping to send: {_options(rows)}")
        ping = rows[0]
    else:
        wanted = " ".join(name.split()).lower()
        found = next((row for row in rows if row.name == wanted), None)
        if found is None:
            raise InvalidAction(f"No ping called `{wanted}` here. Options: {_options(rows)}")
        ping = found
    if ping.required_role_id and ping.required_role_id not in role_ids:
        raise NotAllowed(f"You need the <@&{ping.required_role_id}> role to send this ping.")
    ready = ready_at(ping)
    if ready is not None:
        raise InvalidAction(f"`{ping.name}` is on cooldown: ready <t:{int(ready.timestamp())}:R>.")
    previous = ping.last_ping_at
    ping.last_ping_at = now()
    ping.save(update_fields=["last_ping_at"])
    return Claim(ping, ping.last_ping_at, previous)


def release(claim_: Claim) -> None:
    """The send failed: undo the cooldown, unless someone has sent the ping since."""
    ChannelPing.objects.filter(pk=claim_.ping.pk, last_ping_at=claim_.claimed_at).update(
        last_ping_at=claim_.previous
    )
