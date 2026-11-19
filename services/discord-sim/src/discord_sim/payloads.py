"""Discord JSON shapes for the state objects, as discord.py 2.7.1 parses them.

Snowflakes go out as strings and permission bitfields as decimal strings, like Discord.
`base` is the URL the receiver uses to reach the sim, for attachment URLs.
"""

from __future__ import annotations

import copy
from datetime import datetime
from typing import Any

from discord_sim import components, permissions, snowflake
from discord_sim.state import (
    DM,
    GUILD_CATEGORY,
    Attachment,
    Channel,
    Command,
    Invite,
    Member,
    Message,
    Role,
    SimState,
    User,
    VoiceState,
)

Payload = dict[str, Any]

# Gateway intents the payloads depend on.
GUILD_MEMBERS = 1 << 1
GUILD_VOICE_STATES = 1 << 7
MESSAGE_CONTENT = 1 << 15

ATTACHMENT_SIZE_LIMIT = 25 * 1024 * 1024


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def user(u: User) -> Payload:
    data: Payload = {
        "id": str(u.id),
        "username": u.username,
        "discriminator": "0",
        "global_name": u.global_name,
        "avatar": None,
        "public_flags": 0,
        "flags": 0,
    }
    if u.bot:
        data["bot"] = True
    return data


def member(
    state: SimState, m: Member, *, with_user: bool = True, perms: int | None = None
) -> Payload:
    data: Payload = {
        "roles": [str(r) for r in m.roles],
        "nick": m.nick,
        "avatar": None,
        "joined_at": iso(m.joined_at),
        "premium_since": None,
        "deaf": False,
        "mute": False,
        "flags": 0,
        "pending": False,
        "communication_disabled_until": None,
    }
    if with_user:
        data["user"] = user(state.users[m.user_id])
    if perms is not None:
        data["permissions"] = str(perms)
    return data


def role(r: Role) -> Payload:
    data: Payload = {
        "id": str(r.id),
        "name": r.name,
        "permissions": str(r.permissions),
        "position": r.position,
        "color": r.color,
        "colors": {"primary_color": r.color, "secondary_color": None, "tertiary_color": None},
        "hoist": r.hoist,
        "managed": r.managed,
        "mentionable": r.mentionable,
        "icon": None,
        "unicode_emoji": None,
        "flags": 0,
    }
    if r.bot_id is not None:
        data["tags"] = {"bot_id": str(r.bot_id)}
    return data


def overwrite(o: permissions.Overwrite) -> Payload:
    return {"id": str(o.id), "type": o.type, "allow": str(o.allow), "deny": str(o.deny)}


def channel(state: SimState, c: Channel, *, perms: int | None = None) -> Payload:
    if c.type == DM:
        recipient = state.users.get(c.recipient_id or 0)
        data: Payload = {
            "id": str(c.id),
            "type": DM,
            "last_message_id": _str_or_none(c.last_message_id),
            "recipients": [user(recipient)] if recipient else [],
            "flags": 0,
        }
    else:
        data = {
            "id": str(c.id),
            "type": c.type,
            "guild_id": str(c.guild_id),
            "name": c.name,
            "position": c.position,
            "parent_id": _str_or_none(c.parent_id),
            "permission_overwrites": [overwrite(o) for o in c.overwrites],
            "flags": 0,
        }
        if c.type != GUILD_CATEGORY:
            data |= {
                "nsfw": c.nsfw,
                "rate_limit_per_user": c.rate_limit_per_user,
                "last_message_id": _str_or_none(c.last_message_id),
            }
        if c.is_voice:
            data |= {
                "bitrate": c.bitrate,
                "user_limit": c.user_limit,
                "rtc_region": None,
                "status": c.status,
            }
        elif c.type != GUILD_CATEGORY:
            data["topic"] = c.topic
    if perms is not None:
        data["permissions"] = str(perms)
    return data


def voice_state(
    state: SimState, vs: VoiceState | None, *, user_id: int, session_id: str, full: bool
) -> Payload:
    """A voice state. `full` adds guild_id and member, which VOICE_STATE_UPDATE needs."""
    data: Payload = {
        "channel_id": str(vs.channel_id) if vs else None,
        "user_id": str(user_id),
        "session_id": session_id,
        "deaf": vs.deaf if vs else False,
        "mute": vs.mute if vs else False,
        "self_deaf": vs.self_deaf if vs else False,
        "self_mute": vs.self_mute if vs else False,
        "self_video": False,
        "self_stream": False,
        "suppress": False,
        "request_to_speak_timestamp": None,
    }
    if full:
        data["guild_id"] = str(state.guild.id)
        guild_member = state.guild.members.get(user_id)
        if guild_member is not None:
            data["member"] = member(state, guild_member)
    return data


def attachment_url(base: str, a: Attachment) -> str:
    return f"{base}/attachments/{a.channel_id}/{a.id}/{a.filename}"


def attachment(base: str, a: Attachment) -> Payload:
    url = attachment_url(base, a)
    data: Payload = {
        "id": str(a.id),
        "filename": a.filename,
        "size": a.size,
        "url": url,
        "proxy_url": url,
        "content_type": a.content_type,
    }
    if a.description is not None:
        data["description"] = a.description
    if a.width is not None:
        data["width"] = a.width
        data["height"] = a.height
    return data


def message(state: SimState, m: Message, base: str, *, hide_content: bool = False) -> Payload:
    """A full message. `hide_content` blanks what the Message Content intent would gate."""
    author = state.users.get(m.author_id)
    rendered = render_components(m, base)
    data: Payload = {
        "id": str(m.id),
        "channel_id": str(m.channel_id),
        "type": m.type,
        "content": "" if hide_content else m.content,
        "author": user(author) if author else _deleted_user(m.author_id),
        "timestamp": iso(m.created_at),
        "edited_timestamp": iso(m.edited_at),
        "tts": m.tts,
        "mention_everyone": m.mention_everyone,
        "mentions": [user(state.users[u]) for u in m.mentions if u in state.users],
        "mention_roles": [str(r) for r in m.mention_roles],
        "attachments": [] if hide_content else [attachment(base, a) for a in m.attachments],
        "embeds": [] if hide_content else copy.deepcopy(m.embeds),
        "components": [] if hide_content else rendered,
        "flags": m.flags,
        "pinned": False,
        "nonce": None,
    }
    if m.channel_id in state.guild.channels:
        data["guild_id"] = str(state.guild.id)
        guild_member = state.guild.members.get(m.author_id)
        if guild_member is not None and m.webhook_id is None:
            data["member"] = member(state, guild_member, with_user=False)
    if m.webhook_id is not None:
        data["webhook_id"] = str(m.webhook_id)
        data["application_id"] = str(m.webhook_id)
    if m.interaction_metadata is not None:
        data["interaction_metadata"] = copy.deepcopy(m.interaction_metadata)
    return data


def render_components(m: Message, base: str) -> list[components.Component]:
    """The stored components, `attachment://` media swapped for the hosted file like Discord."""
    by_name = {a.filename: a for a in m.attachments}
    rendered = copy.deepcopy(m.components)

    def resolve(name: str) -> components.Component | None:
        found = by_name.get(name)
        if found is None:
            return None
        media: components.Component = {
            "url": attachment_url(base, found),
            "proxy_url": attachment_url(base, found),
            "content_type": found.content_type,
            "attachment_id": str(found.id),
            "loading_state": 2,
            "placeholder_version": 1,
        }
        if found.width is not None:
            media["width"] = found.width
            media["height"] = found.height
        return media

    components.map_media_urls(rendered, resolve)
    return rendered


def invite(state: SimState, i: Invite) -> Payload:
    target = state.guild.channels.get(i.channel_id)
    inviter = state.users.get(i.inviter_id)
    return {
        "code": i.code,
        "type": 0,
        "channel": {
            "id": str(i.channel_id),
            "name": target.name if target else "",
            "type": target.type if target else 0,
        },
        "guild": {"id": str(state.guild.id), "name": state.guild.name, "features": []},
        "inviter": user(inviter) if inviter else None,
        "max_age": i.max_age,
        "max_uses": i.max_uses,
        "temporary": i.temporary,
        "uses": 0,
        "created_at": iso(i.created_at),
        "expires_at": None,
    }


def command(state: SimState, c: Command) -> Payload:
    data = copy.deepcopy(c.data)
    data |= {
        "id": str(c.id),
        "application_id": str(state.application_id),
        "version": str(c.version),
        "type": c.type,
        "description": data.get("description", ""),
        "options": data.get("options") or [],
        "default_member_permissions": data.get("default_member_permissions"),
        "nsfw": bool(data.get("nsfw", False)),
    }
    if c.guild_id is not None:
        data["guild_id"] = str(c.guild_id)
    return data


def application(state: SimState) -> Payload:
    bot = state.bot_user
    owner = state.users[state.guild.owner_id]
    flags = (1 << 19) if not state.config.message_content_intent else (1 << 18)
    return {
        "id": str(state.application_id),
        "name": bot.display_name,
        "icon": None,
        "description": "DayShift running against discord-sim",
        "summary": "",
        "type": None,
        "bot_public": False,
        "bot_require_code_grant": False,
        "verify_key": "0" * 64,
        "owner": user(owner),
        "team": None,
        "flags": flags,
        "bot": user(bot),
        "install_params": {"scopes": ["bot", "applications.commands"], "permissions": "8"},
        "integration_types_config": {"0": {}},
        "tags": [],
        "redirect_uris": [],
        "interactions_endpoint_url": None,
        "approximate_guild_count": 1,
    }


def guild_rest(state: SimState) -> Payload:
    """GET /guilds/{id}: the guild without channels, members or voice."""
    g = state.guild
    return {
        "id": str(g.id),
        "name": g.name,
        "icon": None,
        "splash": None,
        "discovery_splash": None,
        "owner_id": str(g.owner_id),
        "afk_channel_id": None,
        "afk_timeout": 300,
        "verification_level": 0,
        "default_message_notifications": 1,
        "explicit_content_filter": 0,
        "roles": [role(r) for r in g.roles.values()],
        "emojis": [],
        "stickers": [],
        "features": [],
        "mfa_level": 0,
        "system_channel_id": str(snowflake.GENERAL_TEXT_ID)
        if snowflake.GENERAL_TEXT_ID in g.channels
        else None,
        "system_channel_flags": 0,
        "rules_channel_id": None,
        "vanity_url_code": None,
        "description": None,
        "banner": None,
        "premium_tier": 0,
        "premium_subscription_count": 0,
        "preferred_locale": "en-US",
        "public_updates_channel_id": None,
        "nsfw_level": 0,
        "premium_progress_bar_enabled": False,
    }


def guild_create(state: SimState, intents: int) -> Payload:
    """GUILD_CREATE. Without the members intent only the bot and people in voice are listed."""
    g = state.guild
    voice_ids = set(g.voice_states)
    listed = [
        m
        for uid, m in g.members.items()
        if intents & GUILD_MEMBERS or uid == state.bot_user.id or uid in voice_ids
    ]
    data = guild_rest(state) | {
        "joined_at": iso(g.members[state.bot_user.id].joined_at),
        "large": len(g.members) >= 250,
        "unavailable": False,
        "member_count": len(g.members),
        "channels": [channel(state, c) for c in g.channels.values()],
        "members": [member(state, m) for m in listed],
        "threads": [],
        "presences": [],
        "stage_instances": [],
        "guild_scheduled_events": [],
        "soundboard_sounds": [],
    }
    data["voice_states"] = (
        [
            voice_state(state, vs, user_id=vs.user_id, session_id=vs.session_id, full=False)
            for vs in g.voice_states.values()
        ]
        if intents & GUILD_VOICE_STATES
        else []
    )
    return data


def ready(state: SimState, session_id: str, resume_url: str) -> Payload:
    return {
        "v": 10,
        "user": user(state.bot_user) | {"verified": True, "mfa_enabled": False},
        "guilds": [{"id": str(state.guild.id), "unavailable": True}],
        "session_id": session_id,
        "session_type": "normal",
        "resume_gateway_url": resume_url,
        "application": {"id": str(state.application_id), "flags": application(state)["flags"]},
        "private_channels": [],
        "relationships": [],
        "presences": [],
        "guild_join_requests": [],
        "geo_ordered_rtc_regions": ["sim"],
        "user_settings": {},
        "shard": [0, 1],
        "_trace": ["discord-sim"],
    }


def _deleted_user(user_id: int) -> Payload:
    return {
        "id": str(user_id),
        "username": "Deleted User",
        "discriminator": "0",
        "global_name": None,
        "avatar": None,
    }


def _str_or_none(value: int | None) -> str | None:
    return None if value is None else str(value)
