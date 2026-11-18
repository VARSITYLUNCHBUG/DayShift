"""The /_sim control API: inspect the world, add fake users, and act as them.

JSON in and out. Errors are `{"error": "...", ...details}` with a fitting status. Every user,
channel and role reference takes an ID, and most also take a name.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from aiohttp import web

from discord_sim import __version__, components, errors, payloads, permissions, snowflake
from discord_sim.context import Sim, sim_of
from discord_sim.deadlock_api import MODES, DeadlockApi
from discord_sim.errors import ControlError
from discord_sim.http import cors_headers, json_response
from discord_sim.interactions import Interaction, upload_from_spec
from discord_sim.message_body import MessageBody
from discord_sim.state import GUILD_TEXT, Channel, Message, Role, SimState, User

routes = web.RouteTableDef()

DEFAULT_TIMEOUT = 5.0
MAX_TIMEOUT = 30.0
SSE_PING_SECONDS = 15.0


# --- Summaries --------------------------------------------------------------------------------


def member_summary(state: SimState, user: User) -> dict[str, Any]:
    member = state.guild.members.get(user.id)
    voice = state.guild.voice_states.get(user.id)
    dm = state.dm_channel_of(user.id)
    return {
        "id": str(user.id),
        "name": user.display_name,
        "username": user.username,
        "is_bot": user.bot,
        "is_owner": user.id == state.guild.owner_id,
        "dm_open": user.dm_open,
        "voice_channel_id": str(voice.channel_id) if voice else None,
        "roles": [str(r) for r in member.roles] if member else [],
        "nick": member.nick if member else None,
        "dm_channel_id": str(dm.id) if dm else None,
    }


def channel_summary(state: SimState, channel: Channel) -> dict[str, Any]:
    return {
        "id": str(channel.id),
        "name": channel.name,
        "type": channel.type,
        "parent_id": str(channel.parent_id) if channel.parent_id else None,
        "position": channel.position,
        "overwrites": [payloads.overwrite(o) for o in channel.overwrites],
        "status": channel.status,
        "voice_members": [
            str(v.user_id) for v in state.guild.voice_states.values() if v.channel_id == channel.id
        ],
        "message_count": len(state.messages.get(channel.id, {})),
    }


def message_summary(state: SimState, message: Message, base: str) -> dict[str, Any]:
    """A message for people and scripts: text, flat components, plus the raw Discord payload."""
    author = state.users.get(message.author_id)
    raw = payloads.message(state, message, base)
    metadata = message.interaction_metadata
    return {
        "id": str(message.id),
        "channel_id": str(message.channel_id),
        "author_id": str(message.author_id),
        "author_name": author.display_name if author else None,
        "content": message.content,
        "text": components.text_of(message.components),
        "flags": message.flags,
        "ephemeral": message.ephemeral,
        "ephemeral_for": str(message.ephemeral_for) if message.ephemeral_for else None,
        "loading": bool(message.flags & components.LOADING),
        "created_at": payloads.iso(message.created_at),
        "edited_at": payloads.iso(message.edited_at),
        "components": components.interactive(raw["components"]),
        "attachments": raw["attachments"],
        "mentions": [str(u) for u in message.mentions],
        "mention_roles": [str(r) for r in message.mention_roles],
        "interaction": (
            {
                "id": metadata["id"],
                "type": metadata["type"],
                "user_id": metadata["user"]["id"],
                "name": metadata.get("name"),
            }
            if metadata
            else None
        ),
        "raw": raw,
    }


def attachment_summary(sim: Sim, request: web.Request, attachment_id: int) -> dict[str, Any]:
    attachment = sim.state.attachments[attachment_id]
    return payloads.attachment(sim.base_url(request), attachment) | {
        "sim_url": f"/_sim/attachments/{attachment.id}"
    }


def interaction_result(sim: Sim, request: web.Request, interaction: Interaction) -> dict[str, Any]:
    base = sim.base_url(request)

    def summary(message_id: int | None) -> dict[str, Any] | None:
        if message_id is None:
            return None
        try:
            return message_summary(sim.state, sim.state.find_message(message_id), base)
        except errors.DiscordError:
            return None  # Deleted since.

    followups = [summary(m) for m in interaction.followup_ids]
    return {
        "interaction_id": str(interaction.id),
        "type": interaction.type,
        "response": interaction.response,
        "settled": interaction.settled.is_set(),
        "message": summary(interaction.result_message_id),
        "followups": [f for f in followups if f is not None],
        "modal": interaction.modal,
        "choices": interaction.choices,
    }


# --- Helpers ----------------------------------------------------------------------------------


async def _body(request: web.Request) -> dict[str, Any]:
    raw = await request.read()
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        raise ControlError(400, "The body isn't valid JSON.") from None
    if not isinstance(data, dict):
        raise ControlError(400, "The body must be a JSON object.")
    return data


def _user(state: SimState, ref: Any) -> User:
    if ref is None:
        raise ControlError(400, "user_id is required.")
    try:
        return state.find_user(ref)
    except errors.DiscordError:
        raise ControlError(404, f"No user {ref!r}.") from None


def _channel(state: SimState, ref: Any) -> Channel:
    if ref is None:
        raise ControlError(400, "channel_id is required.")
    try:
        if isinstance(ref, int) or str(ref).isdigit():
            return state.channel(int(ref))
    except errors.DiscordError:
        raise ControlError(404, f"No channel {ref!r}.") from None
    found = state.find_channel_by_name(str(ref))
    if found is None:
        raise ControlError(404, f"No channel named {ref!r}.")
    return found


def _default_text_channel(state: SimState) -> Channel:
    general = state.guild.channels.get(snowflake.GENERAL_TEXT_ID)
    if general is not None:
        return general
    for channel in state.guild.channels.values():
        if channel.type == GUILD_TEXT:
            return channel
    raise ControlError(404, "The guild has no text channel.")


def _seconds(body: dict[str, Any], key: str, default: float, low: float) -> float:
    try:
        value = float(body.get(key, default))
    except (TypeError, ValueError):
        raise ControlError(400, f"{key} must be a number of seconds.") from None
    return min(max(value, low), MAX_TIMEOUT)


async def _run(
    sim: Sim, request: web.Request, interaction: Interaction, body: dict[str, Any]
) -> web.Response:
    """Wait for the answer. `followup_wait` also waits that long for a followup after it, which
    is where the bot puts "not your turn" and other refusals after a deferred update."""
    await sim.interactions.wait(
        interaction,
        _seconds(body, "timeout", DEFAULT_TIMEOUT, 0.1),
        followup_wait=_seconds(body, "followup_wait", 0.0, 0.0),
    )
    return json_response(interaction_result(sim, request, interaction))


# --- Health, state, reset ---------------------------------------------------------------------


@routes.get("/_sim/health")
async def health(request: web.Request) -> web.Response:
    sim = sim_of(request)
    return json_response(
        {
            "ok": True,
            "version": __version__,
            "bot_connected": sim.gateway.bot_connected,
            "sessions": len(sim.gateway.sessions),
        }
    )


@routes.get("/_sim/state")
async def get_state(request: web.Request) -> web.Response:
    return json_response(state_summary(sim_of(request)))


def state_summary(sim: Sim) -> dict[str, Any]:
    state = sim.state
    guild = state.guild
    return {
        "guild": {"id": str(guild.id), "name": guild.name, "owner_id": str(guild.owner_id)},
        "bot": {
            "user_id": str(state.bot_user.id),
            "application_id": str(state.application_id),
            "connected": sim.gateway.bot_connected,
        },
        "seed": {
            "owner_user_id": str(snowflake.OWNER_USER_ID),
            "guild_id": str(snowflake.GUILD_ID),
            "everyone_role_id": str(snowflake.GUILD_ID),
            "bot_role_id": str(snowflake.BOT_ROLE_ID),
            "staff_role_id": str(snowflake.STAFF_ROLE_ID),
            "text_category_id": str(snowflake.TEXT_CATEGORY_ID),
            "general_text_id": str(snowflake.GENERAL_TEXT_ID),
            "voice_category_id": str(snowflake.VOICE_CATEGORY_ID),
            "general_voice_id": str(snowflake.GENERAL_VOICE_ID),
        },
        "roles": [payloads.role(r) for r in guild.roles.values()],
        "channels": [channel_summary(state, c) for c in guild.channels.values()],
        "members": [member_summary(state, state.users[uid]) for uid in guild.members],
        "commands": sorted({c.name for c in state.commands.values()}),
    }


@routes.post("/_sim/reset")
async def reset(request: web.Request) -> web.Response:
    """Back to the seed. Connected clients are asked to reconnect and get a fresh READY."""
    sim = sim_of(request)
    sim.state.reset()
    sim.interactions.reset()
    sim.faults.clear()
    sim.deadlock_api.reset()
    await sim.gateway.reconnect_all()
    return json_response(state_summary(sim))


# --- Users, roles, voice ----------------------------------------------------------------------


@routes.get("/_sim/users")
async def list_users(request: web.Request) -> web.Response:
    state = sim_of(request).state
    return json_response({"users": [member_summary(state, u) for u in state.users.values()]})


@routes.post("/_sim/users")
async def create_users(request: web.Request) -> web.Response:
    """`{count?, names?, name_prefix?, dm_open?, roles?, voice_channel_id?}` -> the new users."""
    sim = sim_of(request)
    state = sim.state
    body = await _body(request)
    names = body.get("names")
    if names is not None and not isinstance(names, list):
        raise ControlError(400, "names must be a list.")
    count = len(names) if names else int(body.get("count", 1))
    if not 1 <= count <= 500:
        raise ControlError(400, "count must be between 1 and 500.")
    try:
        roles = [state.find_role(r).id for r in body.get("roles") or []]
    except errors.DiscordError as exc:
        raise ControlError(404, exc.message) from None
    voice = body.get("voice_channel_id")
    voice_channel = _channel(state, voice) if voice is not None else None
    created = []
    for index in range(count):
        user = state.add_user(
            name=str(names[index]) if names else None,
            name_prefix=str(body.get("name_prefix") or "player"),
            dm_open=bool(body.get("dm_open", True)),
            roles=roles,
        )
        sim.gateway.member_event("GUILD_MEMBER_ADD", user.id)
        if voice_channel is not None:
            sim.gateway.voice_state_update(state.set_voice(user.id, voice_channel.id))
        created.append(member_summary(state, user))
    await sim.gateway.drain()
    return json_response({"users": created}, 201)


@routes.patch("/_sim/users/{user}")
async def edit_user(request: web.Request) -> web.Response:
    """`{dm_open?, name?, nick?, roles?}`."""
    sim = sim_of(request)
    state = sim.state
    user = _user(state, request.match_info["user"])
    body = await _body(request)
    if "dm_open" in body:
        user.dm_open = bool(body["dm_open"])
    if "name" in body:
        user.global_name = str(body["name"])
    member = state.guild.members.get(user.id)
    if member is not None and body.keys() & {"roles", "nick"}:
        if "roles" in body:
            try:
                member.roles = [state.find_role(r).id for r in body["roles"] or []]
            except errors.DiscordError as exc:
                raise ControlError(404, exc.message) from None
        if "nick" in body:
            member.nick = body["nick"] or None
        sim.gateway.member_event("GUILD_MEMBER_UPDATE", user.id)
        await sim.gateway.drain()
    return json_response(member_summary(state, user))


@routes.delete("/_sim/users/{user}")
async def delete_user(request: web.Request) -> web.Response:
    sim = sim_of(request)
    user = _user(sim.state, request.match_info["user"])
    try:
        change = sim.state.remove_user(user.id)
    except errors.DiscordError as exc:
        raise ControlError(400, exc.message) from None
    if change is not None:
        sim.gateway.voice_state_update(change)
    sim.gateway.member_remove(user)
    await sim.gateway.drain()
    return json_response({"deleted": str(user.id)})


@routes.post("/_sim/roles")
async def create_role(request: web.Request) -> web.Response:
    """`{name, permissions?, mentionable?, color?}`."""
    sim = sim_of(request)
    guild = sim.state.guild
    body = await _body(request)
    name = body.get("name")
    if not isinstance(name, str) or not name:
        raise ControlError(400, "name is required.")
    role = Role(
        id=sim.state.ids.next(),
        name=name,
        permissions=int(body.get("permissions", 0)),
        position=max(r.position for r in guild.roles.values()) + 1,
        mentionable=bool(body.get("mentionable", False)),
        color=int(body.get("color", 0)),
    )
    guild.roles[role.id] = role
    sim.gateway.role_create(role.id)
    await sim.gateway.drain()
    return json_response(payloads.role(role), 201)


@routes.post("/_sim/channels")
async def create_channel(request: web.Request) -> web.Response:
    """A channel made outside the bot, as a server admin would: Discord's channel JSON
    (`{name, type?, parent_id?, permission_overwrites?, topic?}`). `parent_id` may be a name."""
    sim = sim_of(request)
    body = await _body(request)
    parent = body.get("parent_id")
    if parent is not None and not str(parent).isdigit():
        body["parent_id"] = str(_channel(sim.state, parent).id)
    try:
        channel = sim.state.create_channel(body)
    except errors.DiscordError as exc:
        raise ControlError(exc.status, exc.message, code=exc.code) from None
    sim.gateway.channel_event("CHANNEL_CREATE", channel)
    await sim.gateway.drain()
    return json_response(channel_summary(sim.state, channel), 201)


@routes.post("/_sim/voice")
async def set_voice(request: web.Request) -> web.Response:
    """`{user_id, channel_id | null}`: join, move or leave voice as that user."""
    sim = sim_of(request)
    body = await _body(request)
    user = _user(sim.state, body.get("user_id"))
    target = body.get("channel_id")
    channel = _channel(sim.state, target) if target is not None else None
    try:
        change = sim.state.set_voice(user.id, channel.id if channel else None)
    except errors.DiscordError as exc:
        raise ControlError(400, exc.message) from None
    sim.gateway.voice_state_update(change)
    await sim.gateway.drain()
    return json_response(
        {
            "user_id": str(user.id),
            "before": str(change.before) if change.before else None,
            "channel_id": str(channel.id) if channel else None,
        }
    )


# --- Messages ---------------------------------------------------------------------------------


@routes.get("/_sim/channels/{channel}/messages")
async def channel_messages(request: web.Request) -> web.Response:
    """Newest first. Ephemeral messages are included and marked, unless include_ephemeral=false."""
    sim = sim_of(request)
    channel = _channel(sim.state, request.match_info["channel"])
    limit = min(int(request.query.get("limit", "50")), 500)
    include = request.query.get("include_ephemeral", "true").lower() != "false"
    messages = sorted(
        (m for m in sim.state.messages.get(channel.id, {}).values() if include or not m.ephemeral),
        key=lambda m: m.id,
        reverse=True,
    )[:limit]
    base = sim.base_url(request)
    return json_response(
        {
            "channel": channel_summary(sim.state, channel),
            "messages": [message_summary(sim.state, m, base) for m in messages],
        }
    )


@routes.get("/_sim/users/{user}/dms")
async def user_dms(request: web.Request) -> web.Response:
    sim = sim_of(request)
    user = _user(sim.state, request.match_info["user"])
    channel = sim.state.dm_channel_of(user.id)
    limit = min(int(request.query.get("limit", "50")), 500)
    messages = sim.state.history(channel.id, limit=limit) if channel else []
    base = sim.base_url(request)
    return json_response(
        {
            "channel_id": str(channel.id) if channel else None,
            "messages": [message_summary(sim.state, m, base) for m in messages],
        }
    )


@routes.post("/_sim/messages")
async def post_message(request: web.Request) -> web.Response:
    """`{user_id, channel_id | dm: true, content, attachments?, force?}`: a fake user chats."""
    sim = sim_of(request)
    state = sim.state
    body = await _body(request)
    user = _user(state, body.get("user_id"))
    if body.get("dm"):
        channel = state.open_dm(user.id)
    else:
        channel = _channel(state, body.get("channel_id"))
        perms = state.channel_permissions(user.id, channel)
        needed = permissions.VIEW_CHANNEL | permissions.SEND_MESSAGES
        if not body.get("force") and perms & needed != needed:
            raise ControlError(403, "That user can't send messages in the channel.")
    files = [
        upload_from_spec(state, spec, index)
        for index, spec in enumerate(body.get("attachments") or [])
    ]
    content = str(body.get("content") or "")
    try:
        message = state.post_message(
            channel.id, user.id, MessageBody.parse({"content": content}, files)
        )
    except errors.DiscordError as exc:
        raise ControlError(exc.status, exc.message, code=exc.code) from None
    sim.gateway.message_create(message)
    await sim.gateway.drain()
    return json_response(message_summary(state, message, sim.base_url(request)), 201)


# --- Interactions -----------------------------------------------------------------------------


@routes.post("/_sim/interactions/component")
async def component(request: web.Request) -> web.Response:
    """`{user_id, message_id, custom_id, values?, force?, timeout?}`."""
    sim = sim_of(request)
    body = await _body(request)
    user = _user(sim.state, body.get("user_id"))
    try:
        message = sim.state.find_message(int(body["message_id"]))
    except (KeyError, ValueError, errors.DiscordError):
        raise ControlError(404, "No message with that message_id.") from None
    custom_id = body.get("custom_id")
    if not isinstance(custom_id, str):
        raise ControlError(400, "custom_id is required.")
    interaction = sim.interactions.click(
        user.id, message, custom_id, body.get("values"), force=bool(body.get("force"))
    )
    return await _run(sim, request, interaction, body)


@routes.post("/_sim/interactions/click")
async def click(request: web.Request) -> web.Response:
    """`{user_id, channel_id | dm_user_id, label, values?, force?, timeout?}`.

    Clicks the newest message there that has an enabled button (or a select, by placeholder)
    whose label matches, ignoring case and emoji.
    """
    sim = sim_of(request)
    state = sim.state
    body = await _body(request)
    user = _user(state, body.get("user_id"))
    label = components.normalize_label(body.get("label"))
    if not label:
        raise ControlError(400, "label is required.")
    if body.get("dm_user_id") is not None:
        dm_user = _user(state, body["dm_user_id"])
        found = state.dm_channel_of(dm_user.id)
        if found is None:
            raise ControlError(404, "The bot never opened a DM with that user.")
        channel = found
    else:
        channel = _channel(state, body.get("channel_id"))
    available = []
    for message in state.history(channel.id, limit=100, viewer_id=user.id):
        labels = []
        for item in components.interactive(message.components):
            if item["disabled"] or item["custom_id"] is None:
                continue
            labels.append(item["label"])
            if components.normalize_label(item["label"]) == label:
                interaction = sim.interactions.click(
                    user.id,
                    message,
                    item["custom_id"],
                    body.get("values"),
                    force=bool(body.get("force")),
                )
                return await _run(sim, request, interaction, body)
        if labels:
            available.append({"message_id": str(message.id), "labels": labels})
    raise ControlError(
        404, f"No enabled component labelled {body.get('label')!r}.", available=available[:20]
    )


@routes.post("/_sim/interactions/command")
async def command(request: web.Request) -> web.Response:
    """`{user_id, name, options?, channel_id?, force?, timeout?}`. `name` may hold subcommands."""
    sim = sim_of(request)
    body = await _body(request)
    user = _user(sim.state, body.get("user_id"))
    channel = (
        _channel(sim.state, body["channel_id"])
        if body.get("channel_id") is not None
        else _default_text_channel(sim.state)
    )
    options = body.get("options") or {}
    if not isinstance(options, dict):
        raise ControlError(400, "options must be an object of name: value.")
    interaction = sim.interactions.command(
        user.id, str(body.get("name") or ""), options, channel.id, force=bool(body.get("force"))
    )
    return await _run(sim, request, interaction, body)


@routes.post("/_sim/interactions/autocomplete")
async def autocomplete(request: web.Request) -> web.Response:
    """`{user_id, name, options, focused, channel_id?}` -> the bot's choices."""
    sim = sim_of(request)
    body = await _body(request)
    user = _user(sim.state, body.get("user_id"))
    focused = body.get("focused")
    options = body.get("options") or {}
    if not isinstance(focused, str) or focused not in options:
        raise ControlError(400, "focused must name one of the options.")
    channel = (
        _channel(sim.state, body["channel_id"])
        if body.get("channel_id") is not None
        else _default_text_channel(sim.state)
    )
    interaction = sim.interactions.command(
        user.id, str(body.get("name") or ""), options, channel.id, focused=focused, force=True
    )
    return await _run(sim, request, interaction, body)


@routes.post("/_sim/interactions/modal")
async def modal(request: web.Request) -> web.Response:
    """`{user_id, custom_id?, values?, attachments?, components?, timeout?}`.

    `values` and `attachments` are keyed by each field's custom_id or its label. Without
    `custom_id`, it submits the modal the bot last opened for the user.
    """
    sim = sim_of(request)
    body = await _body(request)
    user = _user(sim.state, body.get("user_id"))
    values = body.get("values") or {}
    attachments = body.get("attachments") or {}
    if not isinstance(values, dict) or not isinstance(attachments, dict):
        raise ControlError(400, "values and attachments are objects keyed by field.")
    raw = body.get("components")
    interaction = sim.interactions.submit_modal(
        user.id,
        body.get("custom_id"),
        values,
        {k: v if isinstance(v, list) else [v] for k, v in attachments.items()},
        raw if isinstance(raw, list) else None,
    )
    return await _run(sim, request, interaction, body)


@routes.get(r"/_sim/interactions/{interaction_id:\d+}")
async def get_interaction(request: web.Request) -> web.Response:
    """An interaction started earlier, as it stands now: whether it settled, and the bot's
    followups since (where the refusal of a deferred click lands)."""
    sim = sim_of(request)
    found = sim.interactions.by_id.get(int(request.match_info["interaction_id"]))
    if found is None:
        raise ControlError(404, "No such interaction, or it has expired.")
    return json_response(interaction_result(sim, request, found))


@routes.get("/_sim/commands")
async def list_commands(request: web.Request) -> web.Response:
    state = sim_of(request).state
    return json_response(
        {"commands": [payloads.command(state, c) for c in state.commands.values()]}
    )


# --- deadlock-api -----------------------------------------------------------------------------


@routes.get("/_sim/deadlock-api")
async def get_deadlock_api(request: web.Request) -> web.Response:
    """The deadlock-api stand-in: whether lobbies are made or refused, and those made."""
    return json_response(sim_of(request).deadlock_api.describe())


@routes.put("/_sim/deadlock-api")
async def set_deadlock_api(request: web.Request) -> web.Response:
    """`{lobby?: "create" | "fail", heroes?: [...], steam_names?: {...}}`: whether the next
    lobbies are made or refused, the hero roster (replaced), and Steam names (merged; null makes
    an account unknown). Each key is optional; a bad one changes nothing."""
    api = sim_of(request).deadlock_api
    body = await _body(request)
    unknown = set(body) - {"lobby", "heroes", "steam_names"}
    if unknown:
        raise ControlError(400, f"Unknown keys: {', '.join(sorted(unknown))}.")
    if "lobby" in body and body["lobby"] not in MODES:
        raise ControlError(400, f"lobby is one of {', '.join(MODES)}.")
    staged = DeadlockApi(heroes=list(api.heroes), steam_names=dict(api.steam_names))
    if "heroes" in body:
        staged.set_heroes(body["heroes"])
    if "steam_names" in body:
        staged.set_steam_names(body["steam_names"])
    if "lobby" in body:
        api.set_mode(body["lobby"])
    api.heroes, api.steam_names = staged.heroes, staged.steam_names
    return json_response(api.describe())


# --- Attachments ------------------------------------------------------------------------------


@routes.post("/_sim/attachments")
async def upload(request: web.Request) -> web.Response:
    """A file a fake user uploads ahead of a command or modal. JSON with base64, or multipart."""
    sim = sim_of(request)
    state = sim.state
    channel_id = _default_text_channel(state).id
    if request.content_type == "multipart/form-data":
        form = await request.post()
        field = form.get("file")
        if not isinstance(field, web.FileField):
            raise ControlError(400, "Send the file in a multipart field named 'file'.")
        attachment = state.add_attachment(
            channel_id, field.filename, field.file.read(), content_type=field.content_type
        )
    else:
        body = await _body(request)
        if body.get("channel_id") is not None:
            channel_id = _channel(state, body["channel_id"]).id
        upload_spec = upload_from_spec(state, body)
        attachment = state.add_attachment(
            channel_id,
            upload_spec.filename,
            upload_spec.data,
            content_type=upload_spec.content_type,
        )
    return json_response(attachment_summary(sim, request, attachment.id), 201)


@routes.get(r"/_sim/attachments/{attachment_id:\d+}")
async def download(request: web.Request) -> web.Response:
    attachment = sim_of(request).state.attachments.get(int(request.match_info["attachment_id"]))
    if attachment is None:
        raise ControlError(404, "No such attachment.")
    return web.Response(body=attachment.data, content_type=attachment.content_type)


# --- Log, events, faults ----------------------------------------------------------------------


@routes.get("/_sim/log")
async def get_log(request: web.Request) -> web.Response:
    """`?since=<seq>&limit=&kind=rest|gateway|control`."""
    sim = sim_of(request)
    since = int(request.query.get("since", "0"))
    limit = min(int(request.query.get("limit", "500")), 5_000)
    kind = request.query.get("kind")
    entries = [e for e in sim.log.since(since, limit=5_000) if kind in (None, e["kind"])]
    return json_response({"entries": entries[:limit], "last_seq": sim.log.last_seq})


@routes.get("/_sim/events")
async def events(request: web.Request) -> web.StreamResponse:
    """Server-Sent Events of the log. Resumes from Last-Event-ID or `?since=`."""
    sim = sim_of(request)
    response = web.StreamResponse(
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            **cors_headers(request),
        }
    )
    await response.prepare(request)
    start = request.headers.get("Last-Event-ID") or request.query.get("since")
    queue = sim.log.subscribe()
    try:
        seq = int(start) if start and start.isdigit() else sim.log.last_seq
        for past in sim.log.since(seq, limit=5_000):
            await _send_event(response, past)
        while True:
            try:
                entry = await asyncio.wait_for(queue.get(), SSE_PING_SECONDS)
            except TimeoutError:
                await response.write(b": ping\n\n")
                continue
            if entry is None:
                break  # The sim is shutting down, or this reader fell behind.
            if entry["seq"] > seq:
                await _send_event(response, entry)
    except ConnectionResetError:
        pass
    finally:
        sim.log.unsubscribe(queue)
    return response


async def _send_event(response: web.StreamResponse, entry: dict[str, Any]) -> None:
    data = json.dumps(entry, separators=(",", ":"), default=str)
    await response.write(f"id: {entry['seq']}\nevent: {entry['kind']}\ndata: {data}\n\n".encode())


@routes.get("/_sim/faults")
async def list_faults(request: web.Request) -> web.Response:
    return json_response({"faults": [f.describe() for f in sim_of(request).faults.all()]})


@routes.post("/_sim/faults")
async def add_fault(request: web.Request) -> web.Response:
    """`{path, status, method?, code?, message?, retry_after?, times?}`."""
    fault = sim_of(request).faults.add(await _body(request))
    return json_response(fault.describe(), 201)


@routes.delete("/_sim/faults")
async def clear_faults(request: web.Request) -> web.Response:
    sim_of(request).faults.clear()
    return json_response({"faults": []})


def setup(app: web.Application) -> None:
    app.router.add_routes(routes)
