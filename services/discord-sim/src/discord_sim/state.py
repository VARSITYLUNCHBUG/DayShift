"""The in-memory world: one guild, its users, channels, messages, voice and synced commands.

Nothing here knows about HTTP or the gateway. Methods raise DiscordError for the cases Discord
answers with an error, and return what changed so callers can dispatch the matching events.
"""

from __future__ import annotations

import copy
import mimetypes
import re
import secrets
import struct
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from discord_sim import components, errors, permissions, snowflake
from discord_sim.config import Config
from discord_sim.message_body import MISSING, MessageBody
from discord_sim.permissions import Overwrite

GUILD_TEXT = 0
DM = 1
GUILD_VOICE = 2
GUILD_CATEGORY = 4
GUILD_ANNOUNCEMENT = 5
GUILD_STAGE_VOICE = 13
GUILD_FORUM = 15
GUILD_CHANNEL_TYPES = {
    GUILD_TEXT,
    GUILD_VOICE,
    GUILD_CATEGORY,
    GUILD_ANNOUNCEMENT,
    GUILD_STAGE_VOICE,
    GUILD_FORUM,
}
VOICE_TYPES = {GUILD_VOICE, GUILD_STAGE_VOICE}
TEXT_TYPES = {GUILD_TEXT, GUILD_ANNOUNCEMENT}

SUPPRESS_EMBEDS = 1 << 2

_USER_MENTION = re.compile(r"<@!?(\d+)>")
_ROLE_MENTION = re.compile(r"<@&(\d+)>")


def now() -> datetime:
    return datetime.now(UTC)


@dataclass
class User:
    id: int
    username: str
    global_name: str | None
    bot: bool = False
    dm_open: bool = True

    @property
    def display_name(self) -> str:
        return self.global_name or self.username


@dataclass
class Role:
    id: int
    name: str
    permissions: int
    position: int
    mentionable: bool = False
    hoist: bool = False
    color: int = 0
    managed: bool = False
    bot_id: int | None = None


@dataclass
class Member:
    user_id: int
    roles: list[int]
    joined_at: datetime
    nick: str | None = None


@dataclass
class Channel:
    id: int
    type: int
    name: str
    guild_id: int | None
    position: int = 0
    parent_id: int | None = None
    overwrites: list[Overwrite] = field(default_factory=list)
    topic: str | None = None
    nsfw: bool = False
    rate_limit_per_user: int = 0
    bitrate: int = 64_000
    user_limit: int = 0
    status: str | None = None
    recipient_id: int | None = None  # DM channels only.
    last_message_id: int | None = None

    @property
    def is_voice(self) -> bool:
        return self.type in VOICE_TYPES

    def find_overwrite(self, target_id: int) -> Overwrite | None:
        return next((o for o in self.overwrites if o.id == target_id), None)


@dataclass
class Attachment:
    id: int
    channel_id: int
    filename: str
    content_type: str
    data: bytes
    description: str | None = None
    width: int | None = None
    height: int | None = None

    @property
    def size(self) -> int:
        return len(self.data)


@dataclass
class Message:
    id: int
    channel_id: int
    author_id: int
    created_at: datetime
    content: str = ""
    components: list[dict[str, Any]] = field(default_factory=list)
    embeds: list[dict[str, Any]] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)
    flags: int = 0
    type: int = 0
    edited_at: datetime | None = None
    mentions: list[int] = field(default_factory=list)
    mention_roles: list[int] = field(default_factory=list)
    mention_everyone: bool = False
    tts: bool = False
    webhook_id: int | None = None
    interaction_metadata: dict[str, Any] | None = None
    ephemeral_for: int | None = None  # The only user who can see an ephemeral message.

    @property
    def ephemeral(self) -> bool:
        return self.ephemeral_for is not None


@dataclass
class VoiceState:
    user_id: int
    channel_id: int
    session_id: str
    mute: bool = False
    deaf: bool = False
    self_mute: bool = False
    self_deaf: bool = False


@dataclass
class Invite:
    code: str
    channel_id: int
    inviter_id: int
    max_age: int
    max_uses: int
    temporary: bool
    created_at: datetime


@dataclass
class Command:
    id: int
    guild_id: int | None
    data: dict[str, Any]
    version: int

    @property
    def name(self) -> str:
        return str(self.data["name"])

    @property
    def type(self) -> int:
        return int(self.data.get("type", 1))


@dataclass
class Guild:
    id: int
    name: str
    owner_id: int
    roles: dict[int, Role] = field(default_factory=dict)
    channels: dict[int, Channel] = field(default_factory=dict)
    members: dict[int, Member] = field(default_factory=dict)
    voice_states: dict[int, VoiceState] = field(default_factory=dict)


@dataclass
class ChannelDeleted:
    """What deleting a channel changed: the channel, who left voice, children moved to no parent."""

    channel: Channel
    left_voice: list[VoiceChange]
    orphans: list[Channel]


@dataclass
class VoiceChange:
    """A voice move. `state` is None when the user left voice."""

    user_id: int
    before: int | None
    state: VoiceState | None
    session_id: str


class SimState:
    def __init__(self, config: Config, ids: snowflake.SnowflakeGenerator | None = None) -> None:
        self.config = config
        self.ids = ids or snowflake.SnowflakeGenerator()
        # Synced commands belong to the application, not the guild, so a reset keeps them: the
        # bot syncs once at start-up and its slash commands must keep working after a reset.
        self.commands: dict[int, Command] = {}
        self.reset()

    # --- Seed -------------------------------------------------------------------------------

    def reset(self) -> None:
        """Back to the seeded world. Synced commands stay, and IDs never repeat."""
        self.users: dict[int, User] = {}
        self.dm_channels: dict[int, Channel] = {}
        self.messages: dict[int, dict[int, Message]] = {}
        self.attachments: dict[int, Attachment] = {}
        self.invites: dict[str, Invite] = {}
        self.name_counter = 0
        self.guild = Guild(
            id=snowflake.GUILD_ID,
            name=self.config.guild_name,
            owner_id=snowflake.OWNER_USER_ID,
        )
        guild = self.guild
        guild.roles[guild.id] = Role(
            id=guild.id, name="@everyone", permissions=permissions.EVERYONE_DEFAULT, position=0
        )
        guild.roles[snowflake.STAFF_ROLE_ID] = Role(
            id=snowflake.STAFF_ROLE_ID,
            name="Staff",
            permissions=permissions.STAFF_DEFAULT,
            position=1,
            mentionable=True,
            hoist=True,
            color=0x3498DB,
        )
        guild.roles[snowflake.BOT_ROLE_ID] = Role(
            id=snowflake.BOT_ROLE_ID,
            name=self.config.bot_name,
            permissions=permissions.ADMINISTRATOR,
            position=2,
            managed=True,
            bot_id=snowflake.BOT_USER_ID,
        )
        self._add_user(snowflake.OWNER_USER_ID, "sim-owner", "Sim Owner")
        self._add_user(
            snowflake.BOT_USER_ID,
            self.config.bot_name.lower().replace(" ", "-"),
            self.config.bot_name,
            bot=True,
            roles=[snowflake.BOT_ROLE_ID],
        )
        seeded = [
            Channel(snowflake.TEXT_CATEGORY_ID, GUILD_CATEGORY, "Text Channels", guild.id, 0),
            Channel(
                snowflake.GENERAL_TEXT_ID,
                GUILD_TEXT,
                "general",
                guild.id,
                0,
                snowflake.TEXT_CATEGORY_ID,
            ),
            Channel(snowflake.VOICE_CATEGORY_ID, GUILD_CATEGORY, "Voice Channels", guild.id, 1),
            Channel(
                snowflake.GENERAL_VOICE_ID,
                GUILD_VOICE,
                "General",
                guild.id,
                0,
                snowflake.VOICE_CATEGORY_ID,
            ),
        ]
        for channel in seeded:
            guild.channels[channel.id] = channel
            self.messages[channel.id] = {}
        for index in range(self.config.seed_users):
            self.add_user(user_id=snowflake.SEED_USER_BASE + index)

    def _add_user(
        self,
        user_id: int,
        username: str,
        global_name: str | None,
        *,
        bot: bool = False,
        dm_open: bool = True,
        roles: list[int] | None = None,
    ) -> User:
        user = User(user_id, username, global_name, bot=bot, dm_open=dm_open)
        self.users[user_id] = user
        self.guild.members[user_id] = Member(user_id, roles or [], now())
        return user

    # --- Lookups ----------------------------------------------------------------------------

    @property
    def bot_user(self) -> User:
        return self.users[snowflake.BOT_USER_ID]

    @property
    def application_id(self) -> int:
        return snowflake.BOT_USER_ID

    def require_guild(self, guild_id: int) -> Guild:
        if guild_id != self.guild.id:
            raise errors.unknown_guild()
        return self.guild

    def user(self, user_id: int) -> User:
        try:
            return self.users[user_id]
        except KeyError:
            raise errors.unknown_user() from None

    def member(self, user_id: int) -> Member:
        try:
            return self.guild.members[user_id]
        except KeyError:
            raise errors.unknown_member() from None

    def channel(self, channel_id: int) -> Channel:
        channel = self.guild.channels.get(channel_id) or self.dm_channels.get(channel_id)
        if channel is None:
            raise errors.unknown_channel()
        return channel

    def guild_channel(self, channel_id: int) -> Channel:
        channel = self.guild.channels.get(channel_id)
        if channel is None:
            raise errors.unknown_channel()
        return channel

    def message(self, channel_id: int, message_id: int) -> Message:
        self.channel(channel_id)
        message = self.messages.get(channel_id, {}).get(message_id)
        if message is None:
            raise errors.unknown_message()
        return message

    def find_message(self, message_id: int) -> Message:
        for messages in self.messages.values():
            if message_id in messages:
                return messages[message_id]
        raise errors.unknown_message()

    def find_channel_by_name(self, name: str) -> Channel | None:
        """Exact name first, then any case (`general` is the text channel, `General` the voice)."""
        wanted = name.lstrip("#")
        channels = list(self.guild.channels.values())
        exact = next((c for c in channels if c.name == wanted), None)
        return exact or next((c for c in channels if c.name.casefold() == wanted.casefold()), None)

    def find_user(self, ref: int | str) -> User:
        """A user by ID, or by username or display name (handy in scripts)."""
        if isinstance(ref, int) or (isinstance(ref, str) and ref.isdigit()):
            return self.user(int(ref))
        wanted = ref.lstrip("@").casefold()
        for user in self.users.values():
            if wanted in {user.username.casefold(), user.display_name.casefold()}:
                return user
        raise errors.unknown_user()

    def find_role(self, ref: int | str) -> Role:
        if isinstance(ref, int) or (isinstance(ref, str) and ref.isdigit()):
            role = self.guild.roles.get(int(ref))
        else:
            wanted = ref.lstrip("@").casefold()
            role = next((r for r in self.guild.roles.values() if r.name.casefold() == wanted), None)
        if role is None:
            raise errors.DiscordError(404, 10011, "Unknown Role")
        return role

    # --- Permissions ------------------------------------------------------------------------

    def guild_permissions(self, user_id: int) -> int:
        member = self.guild.members.get(user_id)
        if member is None:
            return 0
        return permissions.base_permissions(
            is_owner=user_id == self.guild.owner_id,
            everyone=self.guild.roles[self.guild.id].permissions,
            role_permissions=(
                self.guild.roles[r].permissions for r in member.roles if r in self.guild.roles
            ),
        )

    def channel_permissions(self, user_id: int, channel: Channel) -> int:
        if channel.type == DM:
            return (
                permissions.VIEW_CHANNEL
                | permissions.SEND_MESSAGES
                | permissions.READ_MESSAGE_HISTORY
                | permissions.ATTACH_FILES
                | permissions.EMBED_LINKS
                | permissions.USE_APPLICATION_COMMANDS
            )
        member = self.guild.members.get(user_id)
        if member is None:
            return 0
        return permissions.channel_permissions(
            self.guild_permissions(user_id),
            guild_id=self.guild.id,
            member_id=user_id,
            member_roles=member.roles,
            overwrites=channel.overwrites,
        )

    def can_view(self, user_id: int, channel: Channel) -> bool:
        if channel.type == DM:
            return channel.recipient_id == user_id
        return bool(self.channel_permissions(user_id, channel) & permissions.VIEW_CHANNEL)

    # --- Users ------------------------------------------------------------------------------

    def add_user(
        self,
        *,
        name: str | None = None,
        name_prefix: str = "player",
        dm_open: bool = True,
        user_id: int | None = None,
        roles: list[int] | None = None,
    ) -> User:
        """A new member of the guild. Names count up: player1, player2, ..."""
        self.name_counter += 1
        display = name or f"{name_prefix}{self.name_counter}"
        username = re.sub(r"[^a-z0-9_.]", "", display.casefold().replace(" ", "_")) or "user"
        if any(u.username == username for u in self.users.values()):
            username = f"{username}_{self.name_counter}"
        for role_id in roles or []:
            self.find_role(role_id)
        return self._add_user(
            user_id if user_id is not None else self.ids.next(),
            username,
            display,
            dm_open=dm_open,
            roles=list(roles or []),
        )

    def remove_user(self, user_id: int) -> VoiceChange | None:
        """Remove a fake user from the guild. Returns the voice change if they were in voice."""
        if user_id in {snowflake.BOT_USER_ID, self.guild.owner_id}:
            raise errors.DiscordError(400, 50013, "The owner and the bot can't be removed.")
        self.user(user_id)
        change = self.set_voice(user_id, None) if user_id in self.guild.voice_states else None
        del self.users[user_id]
        self.guild.members.pop(user_id, None)
        return change

    # --- Channels ---------------------------------------------------------------------------

    def create_channel(self, data: dict[str, Any]) -> Channel:
        """POST /guilds/{g}/channels with Discord's checks and defaults."""
        name = data.get("name")
        kind = int(data.get("type") or GUILD_TEXT)
        problems: dict[str, tuple[str, str]] = {}
        if not isinstance(name, str) or not 1 <= len(name) <= 100:
            problems["name"] = ("BASE_TYPE_BAD_LENGTH", "Must be between 1 and 100 in length.")
        if kind not in GUILD_CHANNEL_TYPES:
            problems["type"] = ("BASE_TYPE_CHOICES", f"Value must be one of {GUILD_CHANNEL_TYPES}.")
        parent_id = _snowflake_or_none(data.get("parent_id"))
        if parent_id is not None:
            parent = self.guild.channels.get(parent_id)
            if parent is None or parent.type != GUILD_CATEGORY or kind == GUILD_CATEGORY:
                problems["parent_id"] = ("CHANNEL_PARENT_INVALID", "Not a valid category.")
        if problems:
            raise errors.invalid_form(problems)
        assert isinstance(name, str)
        if kind in TEXT_TYPES:
            name = _text_channel_name(name)
        position = data.get("position")
        if position is None:
            siblings = [
                c
                for c in self.guild.channels.values()
                if (c.type == GUILD_CATEGORY) == (kind == GUILD_CATEGORY)
                and c.parent_id == parent_id
            ]
            position = max((c.position for c in siblings), default=-1) + 1
        if "permission_overwrites" in data:
            overwrites = [_overwrite(o) for o in data["permission_overwrites"] or []]
        elif parent_id is not None:
            # Without overwrites of its own, a new channel copies (syncs with) its category.
            overwrites = copy.deepcopy(self.guild.channels[parent_id].overwrites)
        else:
            overwrites = []
        channel = Channel(
            id=self.ids.next(),
            type=kind,
            name=name,
            guild_id=self.guild.id,
            position=int(position),
            parent_id=parent_id,
            overwrites=overwrites,
            topic=data.get("topic"),
            nsfw=bool(data.get("nsfw", False)),
            rate_limit_per_user=int(data.get("rate_limit_per_user") or 0),
            bitrate=int(data.get("bitrate") or 64_000),
            user_limit=int(data.get("user_limit") or 0),
        )
        self.guild.channels[channel.id] = channel
        self.messages[channel.id] = {}
        return channel

    def edit_channel(self, channel_id: int, data: dict[str, Any]) -> Channel:
        channel = self.guild_channel(channel_id)
        if "name" in data:
            name = str(data["name"])
            channel.name = _text_channel_name(name) if channel.type in TEXT_TYPES else name
        if "parent_id" in data:
            channel.parent_id = _snowflake_or_none(data["parent_id"])
        if "permission_overwrites" in data:
            channel.overwrites = [_overwrite(o) for o in data["permission_overwrites"] or []]
        for key in ("topic", "nsfw", "position", "rate_limit_per_user", "bitrate", "user_limit"):
            if key in data and data[key] is not None:
                setattr(channel, key, data[key])
        return channel

    def delete_channel(self, channel_id: int) -> ChannelDeleted:
        channel = self.guild_channel(channel_id)
        left = [
            VoiceChange(vs.user_id, channel_id, None, vs.session_id)
            for vs in self.guild.voice_states.values()
            if vs.channel_id == channel_id
        ]
        for change in left:
            del self.guild.voice_states[change.user_id]
        orphans = [c for c in self.guild.channels.values() if c.parent_id == channel_id]
        for child in orphans:
            child.parent_id = None
        del self.guild.channels[channel_id]
        for message in self.messages.pop(channel_id, {}).values():
            for attachment in message.attachments:
                self.attachments.pop(attachment.id, None)
        self.invites = {k: v for k, v in self.invites.items() if v.channel_id != channel_id}
        return ChannelDeleted(channel, left, orphans)

    def set_overwrite(self, channel_id: int, target_id: int, data: dict[str, Any]) -> Channel:
        channel = self.guild_channel(channel_id)
        kind = int(data.get("type", permissions.ROLE_OVERWRITE))
        if kind == permissions.ROLE_OVERWRITE and target_id not in self.guild.roles:
            raise errors.DiscordError(404, 10011, "Unknown Role")
        if kind == permissions.MEMBER_OVERWRITE and target_id not in self.guild.members:
            raise errors.unknown_member()
        overwrite = _overwrite({**data, "id": target_id, "type": kind})
        channel.overwrites = [o for o in channel.overwrites if o.id != target_id] + [overwrite]
        return channel

    def remove_overwrite(self, channel_id: int, target_id: int) -> Channel:
        channel = self.guild_channel(channel_id)
        if channel.find_overwrite(target_id) is None:
            raise errors.unknown_overwrite()
        channel.overwrites = [o for o in channel.overwrites if o.id != target_id]
        return channel

    def open_dm(self, user_id: int) -> Channel:
        user = self.users.get(user_id)
        if user is None or user.bot:
            raise errors.invalid_recipient()
        for channel in self.dm_channels.values():
            if channel.recipient_id == user_id:
                return channel
        channel = Channel(id=self.ids.next(), type=DM, name="", guild_id=None, recipient_id=user_id)
        self.dm_channels[channel.id] = channel
        self.messages[channel.id] = {}
        return channel

    def dm_channel_of(self, user_id: int) -> Channel | None:
        return next((c for c in self.dm_channels.values() if c.recipient_id == user_id), None)

    def set_voice_status(self, channel_id: int, status: str | None) -> Channel:
        channel = self.guild_channel(channel_id)
        if not channel.is_voice:
            raise errors.DiscordError(400, 50024, "Cannot execute action on this channel type")
        if status is not None and len(status) > 500:
            raise errors.invalid_form({"status": ("BASE_TYPE_MAX_LENGTH", "Must be 500 or fewer.")})
        channel.status = status or None
        return channel

    # --- Voice ------------------------------------------------------------------------------

    def set_voice(self, user_id: int, channel_id: int | None) -> VoiceChange:
        """Join, move or leave voice (channel_id None)."""
        self.member(user_id)
        current = self.guild.voice_states.get(user_id)
        before = current.channel_id if current else None
        if channel_id is None:
            self.guild.voice_states.pop(user_id, None)
            session = current.session_id if current else secrets.token_hex(16)
            return VoiceChange(user_id, before, None, session)
        channel = self.guild_channel(channel_id)
        if not channel.is_voice:
            raise errors.invalid_form(
                {"channel_id": ("CHANNEL_TYPE_INVALID", "Channel is not a voice channel.")}
            )
        if current is None:
            current = VoiceState(user_id, channel_id, secrets.token_hex(16))
            self.guild.voice_states[user_id] = current
        current.channel_id = channel_id
        return VoiceChange(user_id, before, current, current.session_id)

    def move_member(self, user_id: int, channel_id: int | None) -> VoiceChange:
        """PATCH member `channel_id`: only someone in voice can be moved or disconnected."""
        self.member(user_id)
        if user_id not in self.guild.voice_states:
            raise errors.not_in_voice()
        return self.set_voice(user_id, channel_id)

    # --- Messages ---------------------------------------------------------------------------

    def post_message(
        self,
        channel_id: int,
        author_id: int,
        body: MessageBody,
        *,
        message_type: int = 0,
        webhook_id: int | None = None,
        interaction_metadata: dict[str, Any] | None = None,
        ephemeral_for: int | None = None,
        extra_flags: int = 0,
    ) -> Message:
        channel = self.channel(channel_id)
        flags = (body.flags if body.flags is not MISSING else 0) | extra_flags
        v2 = bool(flags & components.IS_COMPONENTS_V2)
        if self.config.strict:
            body.validate(v2=v2)
        if body.is_empty() and not flags & components.LOADING:
            raise errors.empty_message()
        if channel.type == DM and author_id == self.bot_user.id and webhook_id is None:
            recipient = self.users.get(channel.recipient_id or 0)
            if recipient is None or not recipient.dm_open:
                raise errors.cannot_dm()
        message = Message(
            id=self.ids.next(),
            channel_id=channel_id,
            author_id=author_id,
            created_at=now(),
            type=message_type,
            webhook_id=webhook_id,
            interaction_metadata=interaction_metadata,
            ephemeral_for=ephemeral_for,
            tts=body.tts,
        )
        if ephemeral_for is not None:
            flags |= components.EPHEMERAL
        message.flags = flags
        self._apply_body(message, body, creating=True)
        self.messages.setdefault(channel_id, {})[message.id] = message
        if ephemeral_for is None:
            channel.last_message_id = message.id
        return message

    def edit_message(
        self, message: Message, body: MessageBody, *, clear_loading: bool = False
    ) -> Message:
        """Apply a PATCH. Only SUPPRESS_EMBEDS and IS_COMPONENTS_V2 change; V2 can't be undone."""
        flags = message.flags
        if body.flags is not MISSING:
            editable = SUPPRESS_EMBEDS | components.IS_COMPONENTS_V2
            flags = (
                (message.flags & ~editable)
                | (int(body.flags) & editable)
                | (message.flags & components.IS_COMPONENTS_V2)
            )
        if clear_loading:
            flags &= ~components.LOADING
        v2 = bool(flags & components.IS_COMPONENTS_V2)
        if self.config.strict:
            body.validate(v2=v2)
            if v2 and body.content is MISSING and message.content:
                raise errors.invalid_form(
                    {
                        "flags": (
                            "MESSAGE_CANNOT_USE_LEGACY_FIELDS_WITH_COMPONENTS_V2",
                            "Clear the content before switching to IS_COMPONENTS_V2.",
                        )
                    }
                )
        message.flags = flags
        self._apply_body(message, body, creating=False)
        message.edited_at = now()
        return message

    def _apply_body(self, message: Message, body: MessageBody, *, creating: bool) -> None:
        if body.content is not MISSING:
            message.content = str(body.content)
        if body.embeds is not MISSING:
            message.embeds = copy.deepcopy(body.embeds)
        # Attachments: on an edit, `attachments` lists the ones to keep; new files are added.
        new_files = {f.index: f for f in body.files}
        described: dict[int, dict[str, Any]] = {}
        kept: list[Attachment] = [] if creating else list(message.attachments)
        if body.attachments is not MISSING:
            kept = []
            existing = {a.id: a for a in message.attachments}
            for entry in body.attachments:
                ref = _snowflake_or_none(entry.get("id"))
                if ref is not None and ref in existing:
                    kept.append(existing[ref])
                elif ref is not None:
                    described[ref] = entry
        added = []
        for index, upload in sorted(new_files.items()):
            entry = described.get(index, {})
            attachment = self.add_attachment(
                message.channel_id,
                entry.get("filename") or upload.filename,
                upload.data,
                content_type=upload.content_type,
                description=entry.get("description"),
            )
            added.append(attachment)
        message.attachments = kept + added
        if body.components is not MISSING:
            stored = components.assign_ids(body.components)
            if self.config.strict:
                names = {a.filename for a in message.attachments}
                missing = {
                    f"components.{path}.url": (
                        "UNFURLED_MEDIA_ITEM_ATTACHMENT_NOT_FOUND",
                        f"attachment://{name} is not an attachment of this message.",
                    )
                    for path, name in components.media_references(stored)
                    if name not in names
                }
                if missing:
                    raise errors.invalid_form(missing)
            message.components = stored
        self._apply_mentions(message, body)

    def _apply_mentions(self, message: Message, body: MessageBody) -> None:
        text = " ".join([message.content, *components.text_of(message.components)])
        allowed = body.allowed_mentions if isinstance(body.allowed_mentions, dict) else None
        parse = set(allowed.get("parse") or []) if allowed else {"users", "roles", "everyone"}
        users_ok = {int(u) for u in allowed.get("users") or []} if allowed else set()
        roles_ok = {int(r) for r in allowed.get("roles") or []} if allowed else set()
        user_ids = [int(m) for m in _USER_MENTION.findall(text)]
        role_ids = [int(m) for m in _ROLE_MENTION.findall(text)]
        message.mentions = list(
            dict.fromkeys(
                u for u in user_ids if u in self.users and ("users" in parse or u in users_ok)
            )
        )
        message.mention_roles = list(
            dict.fromkeys(
                r for r in role_ids if r in self.guild.roles and ("roles" in parse or r in roles_ok)
            )
        )
        message.mention_everyone = "everyone" in parse and ("@everyone" in text or "@here" in text)

    def delete_message(self, channel_id: int, message_id: int) -> Message:
        message = self.message(channel_id, message_id)
        del self.messages[channel_id][message_id]
        for attachment in message.attachments:
            self.attachments.pop(attachment.id, None)
        return message

    def history(
        self,
        channel_id: int,
        *,
        limit: int = 50,
        before: int | None = None,
        after: int | None = None,
        around: int | None = None,
        viewer_id: int | None = None,
    ) -> list[Message]:
        """Newest first, as Discord returns them. Ephemeral messages only for their viewer."""
        self.channel(channel_id)
        messages = [
            m
            for m in self.messages.get(channel_id, {}).values()
            if m.ephemeral_for is None or (viewer_id is not None and m.ephemeral_for == viewer_id)
        ]
        messages.sort(key=lambda m: m.id, reverse=True)
        if around is not None:
            older = [m for m in messages if m.id <= around][: (limit + 1) // 2]
            newer = [m for m in messages if m.id > around][-(limit // 2) :] if limit > 1 else []
            return newer + older
        if before is not None:
            messages = [m for m in messages if m.id < before]
        if after is not None:
            messages = [m for m in messages if m.id > after][-limit:]
        return messages[:limit]

    # --- Attachments ------------------------------------------------------------------------

    def add_attachment(
        self,
        channel_id: int,
        filename: str,
        data: bytes,
        *,
        content_type: str | None = None,
        description: str | None = None,
    ) -> Attachment:
        guessed = content_type
        if not guessed or guessed == "application/octet-stream":
            guessed = (
                _sniff(data) or mimetypes.guess_type(filename)[0] or "application/octet-stream"
            )
        width, height = _image_size(data)
        attachment = Attachment(
            id=self.ids.next(),
            channel_id=channel_id,
            filename=_safe_filename(filename),
            content_type=guessed,
            data=data,
            description=description,
            width=width,
            height=height,
        )
        self.attachments[attachment.id] = attachment
        return attachment

    # --- Invites ----------------------------------------------------------------------------

    def create_invite(self, channel_id: int, inviter_id: int, data: dict[str, Any]) -> Invite:
        channel = self.guild_channel(channel_id)
        if channel.type == GUILD_CATEGORY:
            raise errors.DiscordError(400, 50024, "Cannot execute action on this channel type")
        max_age = int(data.get("max_age", 86_400))
        max_uses = int(data.get("max_uses", 0))
        temporary = bool(data.get("temporary", False))
        if not data.get("unique", False):
            for invite in self.invites.values():
                if (invite.channel_id, invite.max_age, invite.max_uses, invite.temporary) == (
                    channel_id,
                    max_age,
                    max_uses,
                    temporary,
                ):
                    return invite
        code = secrets.token_urlsafe(6).replace("-", "a").replace("_", "b")[:8]
        invite = Invite(code, channel_id, inviter_id, max_age, max_uses, temporary, now())
        self.invites[code] = invite
        return invite

    # --- Application commands ---------------------------------------------------------------

    def put_commands(self, guild_id: int | None, commands: list[dict[str, Any]]) -> list[Command]:
        """Bulk overwrite. A command keeps its ID when its name and type stay the same."""
        if guild_id is not None:
            self.require_guild(guild_id)
        old = {(c.name, c.type): c for c in self.commands.values() if c.guild_id == guild_id}
        problems: dict[str, tuple[str, str]] = {}
        for index, data in enumerate(commands):
            name = data.get("name")
            if not isinstance(name, str) or not 1 <= len(name) <= 32:
                problems[f"{index}.name"] = ("BASE_TYPE_BAD_LENGTH", "Must be 1 to 32 long.")
        if problems:
            raise errors.invalid_form(problems)
        self.commands = {k: v for k, v in self.commands.items() if v.guild_id != guild_id}
        result = []
        for data in commands:
            key = (data["name"], int(data.get("type", 1)))
            previous = old.get(key)
            command = Command(
                id=previous.id if previous else self.ids.next(),
                guild_id=guild_id,
                data=copy.deepcopy(data),
                version=self.ids.next(),
            )
            self.commands[command.id] = command
            result.append(command)
        return result

    def commands_for(self, guild_id: int | None) -> list[Command]:
        return [c for c in self.commands.values() if c.guild_id == guild_id]

    def find_command(self, name: str, kind: int = 1) -> Command:
        """Guild commands win over global ones of the same name, as in the Discord client."""
        matches = [c for c in self.commands.values() if c.name == name and c.type == kind]
        matches.sort(key=lambda c: c.guild_id is None)
        if not matches:
            raise errors.DiscordError(404, 10063, "Unknown application command")
        return matches[0]


def _snowflake_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _overwrite(data: dict[str, Any]) -> Overwrite:
    return Overwrite(
        id=int(data["id"]),
        type=int(data.get("type", permissions.ROLE_OVERWRITE)),
        allow=int(data.get("allow") or 0),
        deny=int(data.get("deny") or 0),
    )


def _text_channel_name(name: str) -> str:
    """Discord lower-cases text channel names and turns spaces into dashes."""
    return re.sub(r"-{2,}", "-", re.sub(r"\s+", "-", name.strip().casefold()))


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^\w.\-]", "_", name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1])
    return cleaned or "file"


def _sniff(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    return None


def _image_size(data: bytes) -> tuple[int | None, int | None]:
    """Width and height of a PNG or GIF, which is all the sim needs to look right."""
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        width, height = struct.unpack(">II", data[16:24])
        return int(width), int(height)
    if data.startswith((b"GIF87a", b"GIF89a")) and len(data) >= 10:
        width, height = struct.unpack("<HH", data[6:10])
        return int(width), int(height)
    return None, None
