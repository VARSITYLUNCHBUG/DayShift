"""Permission bits and Discord's overwrite algorithm."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

CREATE_INSTANT_INVITE = 1 << 0
ADMINISTRATOR = 1 << 3
ADD_REACTIONS = 1 << 6
STREAM = 1 << 9
VIEW_CHANNEL = 1 << 10
SEND_MESSAGES = 1 << 11
MANAGE_MESSAGES = 1 << 13
EMBED_LINKS = 1 << 14
ATTACH_FILES = 1 << 15
READ_MESSAGE_HISTORY = 1 << 16
MENTION_EVERYONE = 1 << 17
USE_EXTERNAL_EMOJIS = 1 << 18
CONNECT = 1 << 20
SPEAK = 1 << 21
MOVE_MEMBERS = 1 << 24
USE_VAD = 1 << 25
CHANGE_NICKNAME = 1 << 26
USE_APPLICATION_COMMANDS = 1 << 31

ALL = (1 << 51) - 1

# Roughly what a new server gives @everyone.
EVERYONE_DEFAULT = (
    CREATE_INSTANT_INVITE
    | ADD_REACTIONS
    | STREAM
    | VIEW_CHANNEL
    | SEND_MESSAGES
    | EMBED_LINKS
    | ATTACH_FILES
    | READ_MESSAGE_HISTORY
    | USE_EXTERNAL_EMOJIS
    | CONNECT
    | SPEAK
    | USE_VAD
    | CHANGE_NICKNAME
    | USE_APPLICATION_COMMANDS
)
STAFF_DEFAULT = MANAGE_MESSAGES | MENTION_EVERYONE | MOVE_MEMBERS

ROLE_OVERWRITE = 0
MEMBER_OVERWRITE = 1


@dataclass
class Overwrite:
    id: int
    type: int
    allow: int
    deny: int


def base_permissions(*, is_owner: bool, everyone: int, role_permissions: Iterable[int]) -> int:
    """Guild-level permissions: @everyone plus every role, and everything for owners and admins."""
    if is_owner:
        return ALL
    perms = everyone
    for value in role_permissions:
        perms |= value
    return ALL if perms & ADMINISTRATOR else perms


def channel_permissions(
    base: int,
    *,
    guild_id: int,
    member_id: int,
    member_roles: Iterable[int],
    overwrites: Iterable[Overwrite],
) -> int:
    """Apply overwrites in Discord's order: @everyone, then all roles together, then the member."""
    if base & ADMINISTRATOR or base == ALL:
        return ALL
    by_key = {(o.type, o.id): o for o in overwrites}
    perms = base
    everyone = by_key.get((ROLE_OVERWRITE, guild_id))
    if everyone:
        perms = (perms & ~everyone.deny) | everyone.allow
    allow = deny = 0
    for role_id in member_roles:
        role = by_key.get((ROLE_OVERWRITE, role_id))
        if role:
            allow |= role.allow
            deny |= role.deny
    perms = (perms & ~deny) | allow
    member = by_key.get((MEMBER_OVERWRITE, member_id))
    if member:
        perms = (perms & ~member.deny) | member.allow
    return perms
