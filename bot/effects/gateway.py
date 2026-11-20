"""Everything the effect handlers need from Discord. A protocol, so tests can run the whole flow
against a fake with no network."""

from __future__ import annotations

import contextlib
import io
import time
from collections.abc import Awaitable, Iterable
from typing import Any, Literal, Protocol

import discord
from django.conf import settings

from bot.voice_pacing import VoicePacer

# Discord errors that mean this person can't get a DM, so the caller mentions them in the match
# channel instead: DMs closed (50007), or no such recipient, such as a deleted account (50033).
UNREACHABLE_BY_DM = frozenset({50007, 50033})
UNKNOWN_CHANNEL = 10003


class ChannelGone(Exception):
    """The target channel or message no longer exists: treat deletion and edits as done."""


class EditCapped(Exception):
    """Discord refused an edit because the message is over an hour old and has been edited too
    often since (error 30046). Post a fresh message instead, where that makes sense."""


# Discord's code for that cap. Its HTTP status isn't documented, so match on the code alone.
EDIT_CAPPED_CODE = 30046


def _raise_if_capped(exc: discord.HTTPException, message_id: int) -> None:
    if exc.code == EDIT_CAPPED_CODE:
        raise EditCapped(str(message_id)) from exc


class Gateway(Protocol):
    async def create_text_channel(
        self,
        guild_id: int,
        category_id: int | None,
        name: str,
        member_ids: Iterable[int],
        staff_role_ids: Iterable[int],
        *,
        viewer_role_ids: Iterable[int] = (),
    ) -> int: ...

    async def create_voice_channel(
        self,
        guild_id: int,
        category_id: int | None,
        name: str,
        member_ids: Iterable[int],
        staff_role_ids: Iterable[int],
        *,
        open_to_everyone: bool = False,
        viewer_role_ids: Iterable[int] = (),
    ) -> int: ...

    def voice_member_ids(self, guild_id: int, channel_id: int | None) -> set[int]: ...

    def voice_members(self, guild_id: int, channel_id: int | None) -> dict[int, str] | None:
        """Who is in this voice channel, bots left out: user ID to display name, blank where it
        isn't cached. None if Discord hasn't sent the channel (the server is still loading,
        say), which is different from an empty room."""
        ...

    async def move_member(
        self, guild_id: int, user_id: int, channel_id: int, *, paced: bool = True
    ) -> bool:
        """False if the member isn't in voice (Discord error 40032). Not a failure.

        `paced` spaces it with the server's other voice work. Callers outside a voice lane pass
        False, so a match board never waits behind another match's voice setup."""
        ...

    async def create_invite(self, guild_id: int, channel_id: int, max_age: int) -> str | None: ...

    async def send_dm(self, user_id: int, view: discord.ui.LayoutView) -> int | None:
        """The DM's message ID, or None if the user can't be messaged (DMs closed, or no such
        user). Not a failure."""
        ...

    async def edit_dm(self, user_id: int, message_id: int, view: discord.ui.LayoutView) -> None:
        """Rewrite a DM the bot sent. ChannelGone if it's been deleted."""
        ...

    async def send_view(
        self,
        channel_id: int,
        view: discord.ui.LayoutView,
        *,
        file: tuple[str, bytes] | None = None,
        ping_role_ids: Iterable[int] = (),
        ping_user_ids: Iterable[int] = (),
        reply_to: int | None = None,
    ) -> int:
        """Post a view, as a reply to message `reply_to` if given. Its mentions never ping,
        except the roles and members named here."""
        ...

    async def edit_view(
        self, channel_id: int, message_id: int, view: Any, *, file: tuple[str, bytes] | None = None
    ) -> None:
        """Rewrite a view. With `file`, the message's attachment is replaced by it."""
        ...

    async def send_text(
        self,
        channel_id: int,
        text: str,
        *,
        user_ids: Iterable[int] = (),
        role_ids: Iterable[int] = (),
    ) -> int: ...

    async def edit_text(
        self, channel_id: int, message_id: int, text: str, *, user_ids: Iterable[int] = ()
    ) -> None: ...

    async def latest_message_id(self, channel_id: int) -> int | None: ...

    async def delete_message(self, channel_id: int, message_id: int) -> None: ...

    async def delete_channel(self, channel_id: int) -> None: ...

    async def grant_member(self, channel_id: int, user_id: int) -> None: ...

    async def revoke_member(self, channel_id: int, user_id: int) -> None: ...

    async def set_voice_status(self, channel_id: int, text: str, *, paced: bool = True) -> None: ...

    async def reset_voice_channel(
        self, guild_id: int, channel_id: int, user_ids: Iterable[int] = ()
    ) -> None:
        """Ready a pooled voice channel for its next match: every member's overwrite comes off
        (the bot's own stays) and the voice status is cleared. `user_ids` are revoked too, in
        case the cache missed an overwrite. ChannelGone if the channel no longer exists."""
        ...

    async def set_voice_open(
        self,
        guild_id: int,
        channel_id: int,
        open_to_everyone: bool,
        *,
        viewer_role_ids: Iterable[int] = (),
    ) -> None:
        """Set a voice channel's @everyone overwrite as `create_voice_channel` would have."""
        ...

    async def fetch_attachment(
        self, channel_id: int, message_id: int, attachment_id: int
    ) -> tuple[str, bytes] | None: ...


TEXT_MEMBER = discord.PermissionOverwrite(
    view_channel=True,
    send_messages=True,
    read_message_history=True,
    attach_files=True,
    embed_links=True,
)
VOICE_MEMBER = discord.PermissionOverwrite(
    view_channel=True,
    connect=True,
    speak=True,
    use_voice_activation=True,
)
HIDDEN = discord.PermissionOverwrite(view_channel=False, connect=False)
# The PUGs role is welcome in every match's text channel: it reads and talks there like the
# players. In team voice it only sees who's in, unless Open match voice is on, and member and
# staff overwrites outrank that deny.
TEXT_PUGS = TEXT_MEMBER
VOICE_VIEWER = discord.PermissionOverwrite(view_channel=True, connect=False)
# The API's overwrite type for a member (0 is a role).
MEMBER_OVERWRITE: Literal[1] = 1
# From 16 November 2026, a bot without VIEW_CHANNEL has channels obfuscated or left out of
# listings, so every channel the bot creates must grant the bot its own access.
# Don't add manage_permissions here: Discord refuses (50013) an overwrite granting it unless the
# bot is an Administrator. The server-wide Manage Roles permission already lets it edit overwrites.
SELF_TEXT = discord.PermissionOverwrite(
    view_channel=True,
    send_messages=True,
    read_message_history=True,
    attach_files=True,
    embed_links=True,
    manage_channels=True,
)
SELF_VOICE = discord.PermissionOverwrite(
    view_channel=True,
    connect=True,
    speak=True,
    use_voice_activation=True,
    move_members=True,
    manage_channels=True,
)


def _member(user_id: int) -> discord.Object:
    return discord.Object(id=user_id, type=discord.Member)


# A closed DM doesn't become reachable on the next effect. Retry after a short cooldown,
# rather than spend another refused request on every notice during the same match burst.
DM_UNAVAILABLE_SECONDS = 60.0
DM_UNAVAILABLE_CACHE_SIZE = 1000


class DiscordGateway:
    def __init__(self, client: discord.Client) -> None:
        self.client = client
        # Each watched channel's newest message, from the gateway's message events and our own
        # sends. Message IDs grow with time, so the largest seen is the last. Without an entry
        # (a restart, a reconnect, a deleted last message) the channel's history is read once.
        self._last_message: dict[int, int] = {}
        # (channel, max_age) to an invite URL and when it stops being worth handing out.
        self._invites: dict[tuple[int, int], tuple[str, float]] = {}
        self._dm_unavailable_until: dict[int, float] = {}
        self._voice_pacer = VoicePacer(
            settings.VOICE_CREATE_INTERVAL_SECONDS, settings.VOICE_ACTION_INTERVAL_SECONDS
        )

    def note_last_message(self, channel_id: int, message_id: int) -> None:
        if message_id > self._last_message.get(channel_id, 0):
            self._last_message[channel_id] = message_id

    def forget_last_message(self, channel_id: int, message_id: int) -> None:
        if self._last_message.get(channel_id) == message_id:
            del self._last_message[channel_id]

    def forget_last_messages(self) -> None:
        self._last_message.clear()

    def _guild(self, guild_id: int) -> discord.Guild:
        guild = self.client.get_guild(guild_id)
        if guild is None:
            raise ChannelGone(f"Guild {guild_id} isn't available.")
        return guild

    def _overwrites(
        self,
        guild: discord.Guild,
        member_ids: Iterable[int],
        staff_role_ids: Iterable[int],
        member_perms: discord.PermissionOverwrite,
        self_perms: discord.PermissionOverwrite,
        viewer_role_ids: Iterable[int] = (),
        viewer_perms: discord.PermissionOverwrite | None = None,
    ) -> dict[Any, discord.PermissionOverwrite]:
        overwrites: dict[Any, discord.PermissionOverwrite] = {
            guild.default_role: HIDDEN,
            _member(self.client.user.id): self_perms,  # type: ignore[union-attr]
        }
        if viewer_perms is not None:
            for role_id in viewer_role_ids:
                # The @everyone role's ID is the guild's, so a server with no PUGs role opens
                # to all.
                target = (
                    guild.default_role
                    if role_id == guild.id
                    else discord.Object(role_id, type=discord.Role)
                )
                overwrites[target] = viewer_perms
        for role_id in staff_role_ids:
            overwrites[discord.Object(id=role_id, type=discord.Role)] = member_perms
        for user_id in member_ids:
            overwrites[_member(user_id)] = member_perms
        return overwrites

    def _category(self, guild: discord.Guild, category_id: int | None) -> Any:
        return guild.get_channel(category_id) if category_id else None

    async def create_text_channel(
        self,
        guild_id: int,
        category_id: int | None,
        name: str,
        member_ids: Iterable[int],
        staff_role_ids: Iterable[int],
        *,
        viewer_role_ids: Iterable[int] = (),
    ) -> int:
        """A match text channel: its players, staff and `viewer_role_ids` (the PUGs role) talk."""
        guild = self._guild(guild_id)
        overwrites = self._overwrites(
            guild, member_ids, staff_role_ids, TEXT_MEMBER, SELF_TEXT, viewer_role_ids, TEXT_PUGS
        )
        channel = await guild.create_text_channel(
            name, category=self._category(guild, category_id), overwrites=overwrites
        )
        return channel.id

    async def create_voice_channel(
        self,
        guild_id: int,
        category_id: int | None,
        name: str,
        member_ids: Iterable[int],
        staff_role_ids: Iterable[int],
        *,
        open_to_everyone: bool = False,
        viewer_role_ids: Iterable[int] = (),
    ) -> int:
        """A match voice channel for its players and staff, which `viewer_role_ids` can see but
        not join. With `open_to_everyone` (the server's Open match voice setting) anyone in the
        server can see and join it too."""
        guild = self._guild(guild_id)
        overwrites = self._overwrites(
            guild,
            member_ids,
            staff_role_ids,
            VOICE_MEMBER,
            SELF_VOICE,
            viewer_role_ids,
            VOICE_VIEWER,
        )
        if open_to_everyone:
            overwrites[guild.default_role] = VOICE_MEMBER
        channel = await self._voice_pacer.run(
            guild_id,
            lambda: guild.create_voice_channel(
                name, category=self._category(guild, category_id), overwrites=overwrites
            ),
            create=True,
        )
        return channel.id

    def voice_member_ids(self, guild_id: int, channel_id: int | None) -> set[int]:
        if channel_id is None:
            return set()
        channel = self._guild(guild_id).get_channel(channel_id)
        if not isinstance(channel, discord.VoiceChannel | discord.StageChannel):
            return set()
        # A low-level mapping that works without the privileged Members intent.
        return set(channel.voice_states)

    def voice_members(self, guild_id: int, channel_id: int | None) -> dict[int, str] | None:
        guild = self.client.get_guild(guild_id)
        if guild is None or guild.unavailable or channel_id is None:
            return None
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.VoiceChannel | discord.StageChannel):
            return None
        found = {}
        for user_id in channel.voice_states:
            member = guild.get_member(user_id)
            if member is not None and member.bot:
                continue
            found[user_id] = member.display_name if member is not None else ""
        return found

    async def move_member(
        self, guild_id: int, user_id: int, channel_id: int, *, paced: bool = True
    ) -> bool:
        def move() -> Awaitable[Any]:
            # A plain PATCH: no member cache needed, one request per move.
            return self.client.http.edit_member(guild_id, user_id, channel_id=channel_id)

        try:
            await (self._voice_pacer.run(guild_id, move) if paced else move())
        except discord.HTTPException as exc:
            if exc.code == 40032:
                return False
            raise
        return True

    async def create_invite(self, guild_id: int, channel_id: int, max_age: int) -> str | None:
        channel = self._guild(guild_id).get_channel(channel_id)
        if not isinstance(channel, discord.VoiceChannel):
            return None
        # One invite per channel, not one per player: a pop gathers twelve at once. Reused
        # while it has at least half its life left, so a DM never carries one about to lapse.
        key = (channel_id, max_age)
        cached = self._invites.get(key)
        if cached is not None and cached[1] > time.monotonic():
            return cached[0]
        invite = await channel.create_invite(max_age=max_age, max_uses=0, unique=False)
        reuse_until = time.monotonic() + max_age / 2 if max_age else float("inf")
        self._invites[key] = (invite.url, reuse_until)
        return invite.url

    async def send_dm(self, user_id: int, view: discord.ui.LayoutView) -> int | None:
        moment = time.monotonic()
        unavailable_until = self._dm_unavailable_until.get(user_id)
        if unavailable_until is not None:
            if unavailable_until > moment:
                return None
            del self._dm_unavailable_until[user_id]
        try:
            channel = await self.client.create_dm(discord.Object(id=user_id))
            message = await channel.send(view=view)
        except (discord.Forbidden, discord.NotFound):
            self._remember_unavailable_dm(user_id)
            return None
        except discord.HTTPException as exc:
            if exc.code in UNREACHABLE_BY_DM:
                self._remember_unavailable_dm(user_id)
                return None
            raise
        return int(message.id)

    def _remember_unavailable_dm(self, user_id: int) -> None:
        if len(self._dm_unavailable_until) >= DM_UNAVAILABLE_CACHE_SIZE:
            del self._dm_unavailable_until[next(iter(self._dm_unavailable_until))]
        self._dm_unavailable_until[user_id] = time.monotonic() + DM_UNAVAILABLE_SECONDS

    async def edit_dm(self, user_id: int, message_id: int, view: discord.ui.LayoutView) -> None:
        try:
            channel = await self.client.create_dm(discord.Object(id=user_id))
            await channel.get_partial_message(message_id).edit(view=view)
        except (discord.Forbidden, discord.NotFound) as exc:
            raise ChannelGone(str(message_id)) from exc
        except discord.HTTPException as exc:
            _raise_if_capped(exc, message_id)
            raise

    async def _messageable(self, channel_id: int) -> Any:
        channel = self.client.get_channel(channel_id)
        if channel is not None:
            return channel
        try:
            return await self.client.fetch_channel(channel_id)
        except discord.NotFound as exc:
            raise ChannelGone(str(channel_id)) from exc

    async def send_view(
        self,
        channel_id: int,
        view: discord.ui.LayoutView,
        *,
        file: tuple[str, bytes] | None = None,
        ping_role_ids: Iterable[int] = (),
        ping_user_ids: Iterable[int] = (),
        reply_to: int | None = None,
    ) -> int:
        channel = await self._messageable(channel_id)
        roles = [discord.Object(id=role_id) for role_id in ping_role_ids]
        users = [discord.Object(id=user_id) for user_id in ping_user_ids]
        allowed = (
            discord.AllowedMentions(everyone=False, users=users or False, roles=roles or False)
            if roles or users
            else discord.AllowedMentions.none()
        )
        kwargs: dict[str, Any] = {"view": view, "allowed_mentions": allowed}
        if file is not None:
            kwargs["file"] = discord.File(io.BytesIO(file[1]), filename=file[0])
        if reply_to is not None:
            # A reply to a deleted message posts on its own rather than failing.
            kwargs["reference"] = discord.MessageReference(
                message_id=reply_to, channel_id=channel_id, fail_if_not_exists=False
            )
        try:
            message = await channel.send(**kwargs)
        except discord.NotFound as exc:
            raise ChannelGone(str(channel_id)) from exc
        self.note_last_message(channel_id, message.id)
        return message.id

    async def edit_view(
        self, channel_id: int, message_id: int, view: Any, *, file: tuple[str, bytes] | None = None
    ) -> None:
        channel = await self._messageable(channel_id)
        kwargs: dict[str, Any] = {"view": view, "allowed_mentions": discord.AllowedMentions.none()}
        if file is not None:
            kwargs["attachments"] = [discord.File(io.BytesIO(file[1]), filename=file[0])]
        try:
            await channel.get_partial_message(message_id).edit(**kwargs)
        except discord.NotFound as exc:
            raise ChannelGone(str(message_id)) from exc
        except discord.HTTPException as exc:
            _raise_if_capped(exc, message_id)
            raise

    async def send_text(
        self,
        channel_id: int,
        text: str,
        *,
        user_ids: Iterable[int] = (),
        role_ids: Iterable[int] = (),
    ) -> int:
        channel = await self._messageable(channel_id)
        ids, roles = list(user_ids), list(role_ids)
        prefix = " ".join([*(f"<@{uid}>" for uid in ids), *(f"<@&{rid}>" for rid in roles)])
        allowed = discord.AllowedMentions(
            users=[discord.Object(id=uid) for uid in ids],
            roles=[discord.Object(id=rid) for rid in roles] or False,
            everyone=False,
        )
        content = f"{prefix} {text}".strip()[:2000]
        try:
            message = await channel.send(content, allowed_mentions=allowed)
        except discord.NotFound as exc:
            raise ChannelGone(str(channel_id)) from exc
        self.note_last_message(channel_id, message.id)
        return message.id

    async def edit_text(
        self, channel_id: int, message_id: int, text: str, *, user_ids: Iterable[int] = ()
    ) -> None:
        """Rewrite a text message. An edit never notifies anyone, whoever it mentions."""
        channel = await self._messageable(channel_id)
        prefix = " ".join(f"<@{uid}>" for uid in user_ids)
        try:
            await channel.get_partial_message(message_id).edit(
                content=f"{prefix} {text}".strip()[:2000],
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.NotFound as exc:
            raise ChannelGone(str(message_id)) from exc
        except discord.HTTPException as exc:
            _raise_if_capped(exc, message_id)
            raise

    async def latest_message_id(self, channel_id: int) -> int | None:
        known = self._last_message.get(channel_id)
        if known is not None:
            return known
        channel = await self._messageable(channel_id)
        try:
            async for message in channel.history(limit=1):
                self.note_last_message(channel_id, message.id)
                return message.id
        except discord.NotFound as exc:
            raise ChannelGone(str(channel_id)) from exc
        return None

    async def delete_message(self, channel_id: int, message_id: int) -> None:
        # A bot can always delete its own messages, so this needs no Manage Messages permission.
        channel = await self._messageable(channel_id)
        with contextlib.suppress(discord.NotFound):  # Already gone counts as deleted.
            await channel.get_partial_message(message_id).delete()
        self.forget_last_message(channel_id, message_id)

    async def delete_channel(self, channel_id: int) -> None:
        try:
            channel = await self._messageable(channel_id)
            if isinstance(channel, discord.VoiceChannel | discord.StageChannel):
                await self._voice_pacer.run(channel.guild.id, channel.delete)
            else:
                await channel.delete()
        except (discord.NotFound, ChannelGone):
            return  # Already gone counts as deleted.

    async def grant_member(self, channel_id: int, user_id: int) -> None:
        """Let one member into a match channel. By ID through the API: `set_permissions` only
        takes a cached Member, and the bot doesn't keep the member list."""
        channel = await self._messageable(channel_id)
        perms = VOICE_MEMBER if isinstance(channel, discord.VoiceChannel) else TEXT_MEMBER
        allow, deny = perms.pair()
        try:
            await self.client.http.edit_channel_permissions(
                channel_id, user_id, str(allow.value), str(deny.value), MEMBER_OVERWRITE
            )
        except discord.NotFound as exc:
            if exc.code == UNKNOWN_CHANNEL:
                raise ChannelGone(str(channel_id)) from exc
            # Anything else not found is the person (10009, 10013): they left the server or
            # the account is gone, so there's nobody to let in.

    async def revoke_member(self, channel_id: int, user_id: int) -> None:
        await self._messageable(channel_id)  # A channel that's gone raises ChannelGone first.
        with contextlib.suppress(discord.NotFound):  # They had no overwrite there.
            await self.client.http.delete_channel_permissions(channel_id, user_id)

    async def set_voice_status(self, channel_id: int, text: str, *, paced: bool = True) -> None:
        channel = await self._messageable(channel_id)
        if isinstance(channel, discord.VoiceChannel):
            voice = channel

            def edit() -> Awaitable[Any]:
                # None takes the status off.
                return voice.edit(status=text[:500] or None)

            await (self._voice_pacer.run(voice.guild.id, edit) if paced else edit())

    async def _voice_channel(self, channel_id: int) -> discord.VoiceChannel:
        channel = await self._messageable(channel_id)
        if not isinstance(channel, discord.VoiceChannel):
            raise ChannelGone(f"{channel_id} isn't a voice channel.")
        return channel

    async def reset_voice_channel(
        self, guild_id: int, channel_id: int, user_ids: Iterable[int] = ()
    ) -> None:
        channel = await self._voice_channel(channel_id)
        bot_id = self.client.user.id  # type: ignore[union-attr]
        members = {
            target.id
            for target in channel.overwrites
            if not isinstance(target, discord.Role)
            and not (isinstance(target, discord.Object) and target.type is discord.Role)
        }
        for user_id in (members | set(user_ids)) - {bot_id}:
            await self.revoke_member(channel_id, user_id)
        # discord.py doesn't cache the status, so it's cleared whether or not one is set.
        await self.set_voice_status(channel_id, "")

    async def set_voice_open(
        self,
        guild_id: int,
        channel_id: int,
        open_to_everyone: bool,
        *,
        viewer_role_ids: Iterable[int] = (),
    ) -> None:
        await self._voice_channel(channel_id)
        # Closed, @everyone is hidden, unless it's the viewer role (a server with no PUGs role).
        closed = VOICE_VIEWER if guild_id in set(viewer_role_ids) else HIDDEN
        allow, deny = (VOICE_MEMBER if open_to_everyone else closed).pair()
        try:
            await self.client.http.edit_channel_permissions(
                channel_id, guild_id, str(allow.value), str(deny.value), 0
            )
        except discord.NotFound as exc:
            raise ChannelGone(str(channel_id)) from exc

    async def fetch_attachment(
        self, channel_id: int, message_id: int, attachment_id: int
    ) -> tuple[str, bytes] | None:
        channel = await self._messageable(channel_id)
        try:
            message = await channel.fetch_message(message_id)
        except discord.NotFound:
            return None
        for attachment in message.attachments:
            if attachment.id == attachment_id:
                return attachment.filename, await attachment.read()
        return None
