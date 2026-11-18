"""Interactions: building INTERACTION_CREATE for fake users, and the bot's callbacks and followups.

The control API starts an interaction (a click, a slash command, a modal submit) and waits for the
bot's answer. The REST routes under /interactions and /webhooks land here too.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import copy
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from discord_sim import components, errors, payloads
from discord_sim.config import Config
from discord_sim.errors import ControlError
from discord_sim.eventlog import EventLog
from discord_sim.gateway import Gateway
from discord_sim.message_body import MISSING, MessageBody, UploadedFile
from discord_sim.state import DM, VOICE_TYPES, Attachment, Channel, Message, SimState

APPLICATION_COMMAND = 2
MESSAGE_COMPONENT = 3
AUTOCOMPLETE = 4
MODAL_SUBMIT = 5

CHANNEL_MESSAGE = 4
DEFERRED_CHANNEL_MESSAGE = 5
DEFERRED_UPDATE_MESSAGE = 6
UPDATE_MESSAGE = 7
AUTOCOMPLETE_RESULT = 8
MODAL = 9

ALLOWED_CALLBACKS = {
    APPLICATION_COMMAND: {CHANNEL_MESSAGE, DEFERRED_CHANNEL_MESSAGE, MODAL},
    MESSAGE_COMPONENT: {
        CHANNEL_MESSAGE,
        DEFERRED_CHANNEL_MESSAGE,
        DEFERRED_UPDATE_MESSAGE,
        UPDATE_MESSAGE,
        MODAL,
    },
    AUTOCOMPLETE: {AUTOCOMPLETE_RESULT},
    MODAL_SUBMIT: {
        CHANNEL_MESSAGE,
        DEFERRED_CHANNEL_MESSAGE,
        DEFERRED_UPDATE_MESSAGE,
        UPDATE_MESSAGE,
    },
}

SUB_COMMAND = 1
SUB_COMMAND_GROUP = 2
STRING = 3
INTEGER = 4
BOOLEAN = 5
USER = 6
CHANNEL = 7
ROLE = 8
MENTIONABLE = 9
NUMBER = 10
ATTACHMENT = 11

# A 1x1 transparent PNG, for attachments a script asks for without giving bytes.
PLACEHOLDER_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


@dataclass
class Interaction:
    id: int
    token: str
    type: int
    user_id: int
    channel_id: int
    message_id: int | None
    created: float
    build: Callable[[str], payloads.Payload]
    name: str | None = None
    response: payloads.Payload | None = None
    original_message_id: int | None = None
    loading: bool = False  # Deferred with type 5 and the first followup hasn't replaced it yet.
    result_message_id: int | None = None
    modal: payloads.Payload | None = None
    choices: list[Any] | None = None
    responded: asyncio.Event = field(default_factory=asyncio.Event)
    settled: asyncio.Event = field(default_factory=asyncio.Event)
    followup_ids: list[int] = field(default_factory=list)
    followed: asyncio.Event = field(default_factory=asyncio.Event)

    def settle(self, message_id: int | None) -> None:
        if not self.settled.is_set():
            self.result_message_id = message_id
            self.settled.set()


@dataclass
class OpenModal:
    interaction_id: int
    channel_id: int
    message_id: int | None
    data: payloads.Payload


@dataclass
class Resolved:
    users: set[int] = field(default_factory=set)
    members: set[int] = field(default_factory=set)
    roles: set[int] = field(default_factory=set)
    channels: set[int] = field(default_factory=set)
    attachments: list[Attachment] = field(default_factory=list)

    def render(self, state: SimState, base: str, viewer_id: int) -> payloads.Payload:
        data: payloads.Payload = {}
        if self.users:
            data["users"] = {str(u): payloads.user(state.users[u]) for u in self.users}
        if self.members:
            data["members"] = {
                str(u): payloads.member(
                    state,
                    state.guild.members[u],
                    with_user=False,
                    perms=state.guild_permissions(u),
                )
                for u in self.members
                if u in state.guild.members
            }
        if self.roles:
            data["roles"] = {str(r): payloads.role(state.guild.roles[r]) for r in self.roles}
        if self.channels:
            data["channels"] = {
                str(c): _resolved_channel(state, state.channel(c), viewer_id) for c in self.channels
            }
        if self.attachments:
            data["attachments"] = {
                str(a.id): payloads.attachment(base, a) | {"ephemeral": True}
                for a in self.attachments
            }
        return data


class Interactions:
    def __init__(self, config: Config, state: SimState, gateway: Gateway, log: EventLog) -> None:
        self.config = config
        self.state = state
        self.gateway = gateway
        self.log = log
        self.reset()

    def reset(self) -> None:
        self.by_id: dict[int, Interaction] = {}
        self.by_token: dict[str, Interaction] = {}
        self.open_modals: dict[int, OpenModal] = {}

    # --- Starting interactions (control API) ------------------------------------------------

    def click(
        self,
        user_id: int,
        message: Message,
        custom_id: str,
        values: list[Any] | None = None,
        *,
        force: bool = False,
    ) -> Interaction:
        """A fake user presses a button or picks from a select on a stored message."""
        channel = self._visible_channel(user_id, message.channel_id, force=force)
        if message.ephemeral_for not in (None, user_id):
            raise ControlError(403, "That ephemeral message belongs to someone else.")
        component = components.find_custom_id(message.components, custom_id)
        if component is None or component.get("type") not in components.INTERACTIVE:
            raise ControlError(
                404,
                "No button or select with that custom_id on the message.",
                available=[c["custom_id"] for c in components.interactive(message.components)],
            )
        if component.get("disabled"):
            raise ControlError(409, "That component is disabled.", custom_id=custom_id)
        kind = component["type"]
        data: payloads.Payload = {"custom_id": custom_id, "component_type": kind}
        if isinstance(component.get("id"), int):
            data["id"] = component["id"]
        resolved = Resolved()
        if kind in components.SELECTS:
            data["values"] = self._select_values(component, values or [], resolved)
        elif values:
            raise ControlError(400, "Buttons don't take values.")
        elif component.get("style") == components.LINK_STYLE:
            raise ControlError(400, "Link buttons open a URL; there is nothing to click.")

        def build(base: str) -> payloads.Payload:
            payload = self._common(interaction, channel, base)
            body = dict(data)
            if resolved.users or resolved.roles or resolved.channels:
                body["resolved"] = resolved.render(self.state, base, user_id)
            payload["data"] = body
            payload["message"] = payloads.message(self.state, message, base)
            return payload

        interaction = self._new(MESSAGE_COMPONENT, user_id, channel.id, message.id, build)
        return self._start(interaction)

    def command(
        self,
        user_id: int,
        name: str,
        options: dict[str, Any],
        channel_id: int,
        *,
        focused: str | None = None,
        force: bool = False,
    ) -> Interaction:
        """A fake user runs a slash command (or types into an autocomplete option: `focused`)."""
        channel = self._visible_channel(user_id, channel_id, force=force)
        parts = name.strip().lstrip("/").split()
        if not parts:
            raise ControlError(400, "Give the command name, such as 'setup' or 'match status'.")
        try:
            command = self.state.find_command(parts[0])
        except errors.DiscordError:
            raise ControlError(
                404,
                f"No synced command /{parts[0]}.",
                available=sorted({c.name for c in self.state.commands.values()}),
            ) from None
        needed = command.data.get("default_member_permissions")
        if needed and not force and channel.type != DM:
            have = self.state.channel_permissions(user_id, channel)
            if int(needed) & ~have:
                raise ControlError(
                    403,
                    f"/{command.name} needs permissions {needed} that this user doesn't have.",
                )
        schema: list[payloads.Payload] = command.data.get("options") or []
        wrappers: list[tuple[int, str]] = []
        for part in parts[1:]:
            match = next(
                (
                    o
                    for o in schema
                    if o.get("name") == part and o.get("type") in (SUB_COMMAND, SUB_COMMAND_GROUP)
                ),
                None,
            )
            if match is None:
                raise ControlError(404, f"/{command.name} has no subcommand {part!r}.")
            wrappers.append((int(match["type"]), part))
            schema = match.get("options") or []
        if any(o.get("type") in (SUB_COMMAND, SUB_COMMAND_GROUP) for o in schema):
            names = [o["name"] for o in schema]
            raise ControlError(400, f"Pick a subcommand of /{name.strip()}: {names}.")
        resolved = Resolved()
        built = self._command_options(schema, options, resolved, channel.id, focused=focused)
        for kind, part in reversed(wrappers):
            built = [{"type": kind, "name": part, "options": built}]
        data: payloads.Payload = {
            "id": str(command.id),
            "name": command.name,
            "type": command.type,
            "options": built,
        }
        if command.guild_id is not None:
            data["guild_id"] = str(command.guild_id)

        def build(base: str) -> payloads.Payload:
            payload = self._common(interaction, channel, base)
            body = dict(data)
            rendered = resolved.render(self.state, base, user_id)
            if rendered:
                body["resolved"] = rendered
            payload["data"] = body
            return payload

        kind = AUTOCOMPLETE if focused else APPLICATION_COMMAND
        interaction = self._new(kind, user_id, channel.id, None, build)
        interaction.name = " ".join([command.name, *parts[1:]])
        return self._start(interaction)

    def submit_modal(
        self,
        user_id: int,
        custom_id: str | None,
        values: dict[str, Any],
        attachments: dict[str, list[Any]],
        raw_components: list[payloads.Payload] | None = None,
    ) -> Interaction:
        """A fake user fills in and submits the modal the bot last opened for them."""
        opened = self.open_modals.get(user_id)
        if opened is None or (custom_id and opened.data.get("custom_id") != custom_id):
            raise ControlError(404, "The bot hasn't opened that modal for this user.")
        resolved = Resolved()
        if raw_components is not None:
            submitted = raw_components
        else:
            submitted = self._modal_components(opened, values, attachments, resolved)
        del self.open_modals[user_id]
        channel = self.state.channel(opened.channel_id)
        message = (
            self.state.messages.get(opened.channel_id, {}).get(opened.message_id)
            if opened.message_id
            else None
        )
        data = {"custom_id": opened.data["custom_id"], "components": submitted}

        def build(base: str) -> payloads.Payload:
            payload = self._common(interaction, channel, base)
            body: payloads.Payload = dict(data)
            if resolved.attachments:
                body["resolved"] = resolved.render(self.state, base, user_id)
            payload["data"] = body
            if message is not None:
                payload["message"] = payloads.message(self.state, message, base)
            return payload

        interaction = self._new(
            MODAL_SUBMIT, user_id, channel.id, message.id if message else None, build
        )
        return self._start(interaction)

    async def wait(
        self, interaction: Interaction, timeout: float, *, followup_wait: float = 0.0
    ) -> Interaction:
        """Wait for the bot's answer. A deferred reply settles when its first followup lands.
        With `followup_wait`, also give the bot that long to send a followup after settling."""
        try:
            await asyncio.wait_for(interaction.settled.wait(), timeout)
        except TimeoutError:
            if not interaction.responded.is_set():
                raise ControlError(
                    504,
                    "The bot didn't answer the interaction in time.",
                    interaction_id=str(interaction.id),
                ) from None
        if followup_wait and not interaction.followup_ids:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(interaction.followed.wait(), followup_wait)
        return interaction

    def make_attachment(self, channel_id: int, spec: Any) -> Attachment:
        """A fake user's upload: an existing attachment ID, or {filename, data_base64?}."""
        if isinstance(spec, (int, str)) and str(spec).isdigit():
            found = self.state.attachments.get(int(spec))
            if found is None:
                raise ControlError(404, f"No attachment {spec}.")
            return found
        upload = upload_from_spec(self.state, spec)
        return self.state.add_attachment(
            channel_id, upload.filename, upload.data, content_type=upload.content_type
        )

    def _new(
        self,
        kind: int,
        user_id: int,
        channel_id: int,
        message_id: int | None,
        build: Callable[[str], payloads.Payload],
    ) -> Interaction:
        self._prune()
        interaction = Interaction(
            id=self.state.ids.next(),
            token=secrets.token_urlsafe(48),
            type=kind,
            user_id=user_id,
            channel_id=channel_id,
            message_id=message_id,
            created=time.monotonic(),
            build=build,
        )
        return interaction

    def _start(self, interaction: Interaction) -> Interaction:
        self.by_id[interaction.id] = interaction
        self.by_token[interaction.token] = interaction
        if not self.gateway.interaction_create(interaction.build):
            del self.by_id[interaction.id]
            del self.by_token[interaction.token]
            # 503, not 409: nothing is wrong with the press, there is just nobody to answer it
            # (the bot is down, or reconnecting after a reset). Clients may wait and retry.
            raise ControlError(503, "No bot is connected to the gateway.", reason="no_bot")
        return interaction

    def _prune(self) -> None:
        cutoff = time.monotonic() - self.config.interaction_token_seconds
        for old in [i for i in self.by_id.values() if i.created < cutoff]:
            self.by_id.pop(old.id, None)
            self.by_token.pop(old.token, None)

    def _visible_channel(self, user_id: int, channel_id: int, *, force: bool) -> Channel:
        try:
            self.state.user(user_id)
            channel = self.state.channel(channel_id)
        except errors.DiscordError as exc:
            raise ControlError(404, exc.message) from None
        if channel.type != DM and user_id not in self.state.guild.members:
            raise ControlError(403, "That user isn't in the guild.")
        if not force and not self.state.can_view(user_id, channel):
            raise ControlError(
                403,
                "That user can't see the channel (pass force: true to click anyway).",
                channel_id=str(channel_id),
            )
        return channel

    def _common(self, interaction: Interaction, channel: Channel, base: str) -> payloads.Payload:
        state = self.state
        user = state.users[interaction.user_id]
        perms = state.channel_permissions(interaction.user_id, channel)
        payload: payloads.Payload = {
            "id": str(interaction.id),
            "application_id": str(state.application_id),
            "type": interaction.type,
            "token": interaction.token,
            "version": 1,
            "channel_id": str(channel.id),
            "channel": payloads.channel(state, channel, perms=perms),
            "app_permissions": str(state.channel_permissions(state.bot_user.id, channel)),
            "locale": "en-US",
            "entitlements": [],
            "authorizing_integration_owners": {"0": str(state.guild.id)},
            "attachment_size_limit": payloads.ATTACHMENT_SIZE_LIMIT,
        }
        if channel.type == DM:
            payload["user"] = payloads.user(user)
            payload["context"] = 1
        else:
            payload["guild_id"] = str(state.guild.id)
            payload["guild"] = {"id": str(state.guild.id), "locale": "en-US", "features": []}
            payload["guild_locale"] = "en-US"
            payload["member"] = payloads.member(
                state, state.guild.members[interaction.user_id], perms=perms
            )
            payload["context"] = 0
        return payload

    def _select_values(
        self, component: payloads.Payload, values: list[Any], resolved: Resolved
    ) -> list[str]:
        kind = component["type"]
        low = int(component.get("min_values", 1))
        high = int(component.get("max_values", 1))
        if not low <= len(values) <= high:
            raise ControlError(400, f"Pick between {low} and {high} values.")
        if kind == components.STRING_SELECT:
            options = component.get("options") or []
            by_value = {o["value"]: o["value"] for o in options}
            by_label = {components.normalize_label(o.get("label")): o["value"] for o in options}
            picked = []
            for value in values:
                match = by_value.get(str(value)) or by_label.get(components.normalize_label(value))
                if match is None:
                    raise ControlError(
                        400,
                        f"{value!r} isn't an option.",
                        options=[{"label": o.get("label"), "value": o["value"]} for o in options],
                    )
                picked.append(match)
            return picked
        picked_ids = []
        for value in values:
            picked_ids.append(self._resolve_entity(kind, value, resolved))
        return [str(v) for v in picked_ids]

    def _resolve_entity(self, kind: int, value: Any, resolved: Resolved) -> int:
        """A user, role, channel or mentionable for a select or option, by ID or name."""
        try:
            if kind in (components.USER_SELECT, USER) or (
                kind in (components.MENTIONABLE_SELECT, MENTIONABLE) and _is_user(self.state, value)
            ):
                user = self.state.find_user(value)
                resolved.users.add(user.id)
                if user.id in self.state.guild.members:
                    resolved.members.add(user.id)
                return user.id
            if kind in (components.ROLE_SELECT, ROLE, components.MENTIONABLE_SELECT, MENTIONABLE):
                role = self.state.find_role(value)
                resolved.roles.add(role.id)
                return role.id
            if kind in (components.CHANNEL_SELECT, CHANNEL):
                channel = (
                    self.state.channel(int(value))
                    if str(value).isdigit()
                    else self.state.find_channel_by_name(str(value))
                )
                if channel is None:
                    raise errors.unknown_channel()
                resolved.channels.add(channel.id)
                return channel.id
        except errors.DiscordError as exc:
            raise ControlError(404, f"{value!r}: {exc.message}") from None
        raise ControlError(400, f"Can't resolve a value for component type {kind}.")

    def _command_options(
        self,
        schema: list[payloads.Payload],
        given: dict[str, Any],
        resolved: Resolved,
        channel_id: int,
        *,
        focused: str | None,
    ) -> list[payloads.Payload]:
        known = {o["name"]: o for o in schema}
        unknown = set(given) - set(known)
        if unknown:
            raise ControlError(400, f"Unknown options {sorted(unknown)}.", available=sorted(known))
        missing = [
            name
            for name, o in known.items()
            if o.get("required") and name not in given and name != focused
        ]
        if missing and not focused:
            raise ControlError(400, f"Missing required options {missing}.")
        built = []
        for name, value in given.items():
            option = known[name]
            entry: payloads.Payload = {"name": name, "type": option["type"]}
            if name == focused:
                entry["value"] = str(value)
                entry["focused"] = True
            else:
                entry["value"] = self._option_value(option, value, resolved, channel_id)
            built.append(entry)
        return built

    def _option_value(
        self, option: payloads.Payload, value: Any, resolved: Resolved, channel_id: int
    ) -> Any:
        kind = option["type"]
        name = option["name"]
        try:
            if kind == STRING:
                result: Any = str(value)
            elif kind == INTEGER:
                result = int(value)
            elif kind == NUMBER:
                result = float(value)
            elif kind == BOOLEAN:
                result = value if isinstance(value, bool) else str(value).lower() == "true"
            elif kind == ATTACHMENT:
                attachment = self.make_attachment(channel_id, value)
                resolved.attachments.append(attachment)
                return str(attachment.id)
            elif kind in (USER, ROLE, CHANNEL, MENTIONABLE):
                entity = self._resolve_entity(kind, value, resolved)
                if kind == CHANNEL:
                    allowed = option.get("channel_types")
                    if allowed and self.state.channel(entity).type not in allowed:
                        raise ControlError(400, f"Option {name}: channel type not allowed.")
                return str(entity)
            else:
                raise ControlError(400, f"Option {name}: unsupported type {kind}.")
        except ValueError:
            raise ControlError(400, f"Option {name}: {value!r} isn't a valid value.") from None
        choices = option.get("choices")
        if choices:
            match = next(
                (c["value"] for c in choices if c["value"] == result or c["name"] == value),
                None,
            )
            if match is None:
                raise ControlError(
                    400, f"Option {name}: pick one of {[c['name'] for c in choices]}."
                )
            result = match
        measured = len(result) if kind == STRING else result
        low_key, high_key = (
            ("min_length", "max_length") if kind == STRING else ("min_value", "max_value")
        )
        low, high = option.get(low_key), option.get(high_key)
        if (low is not None and measured < low) or (high is not None and measured > high):
            raise ControlError(400, f"Option {name}: {value!r} is out of range.")
        return result

    def _modal_components(
        self,
        opened: OpenModal,
        values: dict[str, Any],
        attachments: dict[str, list[Any]],
        resolved: Resolved,
    ) -> list[payloads.Payload]:
        """The submitted rows, built from the modal the bot sent, keyed by custom_id or label."""
        normalized_values = {components.normalize_label(k): v for k, v in values.items()}
        normalized_files = {components.normalize_label(k): v for k, v in attachments.items()}
        submitted: list[payloads.Payload] = []
        missing: list[str] = []

        def lookup(table: dict[str, Any], normal: dict[str, Any], keys: list[str]) -> Any:
            for key in keys:
                if key in table:
                    return table[key]
                if components.normalize_label(key) in normal:
                    return normal[components.normalize_label(key)]
            return MISSING

        def answer(inner: payloads.Payload, label: str | None) -> payloads.Payload:
            custom_id = inner.get("custom_id", "")
            keys = [k for k in (custom_id, label, inner.get("label")) if k]
            kind = inner.get("type")
            out: payloads.Payload = {"type": kind, "id": inner.get("id"), "custom_id": custom_id}
            if kind == components.TEXT_INPUT:
                value = lookup(values, normalized_values, keys)
                if value is MISSING:
                    value = inner.get("value") or ""
                if not value and inner.get("required", True):
                    missing.append(label or custom_id)
                out["value"] = str(value)
            elif kind == components.FILE_UPLOAD:
                specs = lookup(attachments, normalized_files, keys)
                files = [] if specs is MISSING else list(specs)
                made = [self.make_attachment(opened.channel_id, s) for s in files]
                resolved.attachments.extend(made)
                if not made and inner.get("required", True):
                    missing.append(label or custom_id)
                out["values"] = [str(a.id) for a in made]
            elif kind in components.SELECTS:
                picked = lookup(values, normalized_values, keys)
                picks = [] if picked is MISSING else picked
                picks = picks if isinstance(picks, list) else [picks]
                if not picks and inner.get("required", True):
                    missing.append(label or custom_id)
                out["values"] = (
                    self._select_values(inner | {"min_values": 0}, picks, resolved) if picks else []
                )
            return out

        for top in opened.data.get("components") or []:
            kind = top.get("type")
            if kind == components.LABEL and isinstance(top.get("component"), dict):
                submitted.append(
                    {
                        "type": components.LABEL,
                        "id": top.get("id"),
                        "component": answer(top["component"], top.get("label")),
                    }
                )
            elif kind == components.ACTION_ROW:
                submitted.append(
                    {
                        "type": components.ACTION_ROW,
                        "id": top.get("id"),
                        "components": [answer(c, None) for c in top.get("components") or []],
                    }
                )
            elif kind == components.TEXT_DISPLAY:
                submitted.append({"type": components.TEXT_DISPLAY, "id": top.get("id")})
        if missing:
            raise ControlError(400, f"The modal needs answers for {missing}.")
        return submitted

    # --- The bot's side (REST) --------------------------------------------------------------

    def callback(
        self,
        interaction_id: int,
        token: str,
        body: payloads.Payload,
        files: list[UploadedFile],
        base: str,
    ) -> payloads.Payload:
        """POST /interactions/{id}/{token}/callback. Returns the with_response body."""
        interaction = self.by_id.get(interaction_id)
        if interaction is None or interaction.token != token:
            raise errors.unknown_interaction()
        if interaction.response is not None:
            raise errors.already_acknowledged()
        age = time.monotonic() - interaction.created
        if self.config.interaction_ack_seconds and age > self.config.interaction_ack_seconds:
            raise errors.unknown_interaction()
        kind = body.get("type")
        if kind not in ALLOWED_CALLBACKS.get(interaction.type, set()) or (
            kind in (DEFERRED_UPDATE_MESSAGE, UPDATE_MESSAGE) and interaction.message_id is None
        ):
            raise errors.invalid_form(
                {"type": ("INTERACTION_RESPONSE_TYPE_INVALID", "Invalid interaction response type")}
            )
        data = body.get("data") or {}
        state = self.state
        message: Message | None = None
        ephemeral = False
        if kind == CHANNEL_MESSAGE:
            mb = MessageBody.parse(data, files)
            ephemeral = bool(_flags(mb) & components.EPHEMERAL)
            message = self._post(interaction, mb, ephemeral=ephemeral)
            interaction.original_message_id = message.id
        elif kind == DEFERRED_CHANNEL_MESSAGE:
            ephemeral = bool(int(data.get("flags") or 0) & components.EPHEMERAL)
            message = self._post(
                interaction,
                MessageBody(content=""),
                ephemeral=ephemeral,
                extra_flags=components.LOADING,
            )
            interaction.original_message_id = message.id
            interaction.loading = True
        elif kind == DEFERRED_UPDATE_MESSAGE:
            interaction.original_message_id = interaction.message_id
        elif kind == UPDATE_MESSAGE:
            assert interaction.message_id is not None
            message = state.message(interaction.channel_id, interaction.message_id)
            state.edit_message(message, MessageBody.parse(data, files))
            ephemeral = message.ephemeral
            interaction.original_message_id = message.id
            self.gateway.message_update(message)
        elif kind == AUTOCOMPLETE_RESULT:
            interaction.choices = list(data.get("choices") or [])
        elif kind == MODAL:
            self._open_modal(interaction, data)
        interaction.response = {"type": kind, "data": copy.deepcopy(data)}
        interaction.responded.set()
        if kind != DEFERRED_CHANNEL_MESSAGE:
            interaction.settle(message.id if message else interaction.message_id)
        reply: payloads.Payload = {
            "interaction": {
                "id": str(interaction.id),
                "type": interaction.type,
                "response_message_loading": kind == DEFERRED_CHANNEL_MESSAGE,
                "response_message_ephemeral": ephemeral,
            },
            "resource": {"type": kind},
        }
        if interaction.original_message_id is not None:
            reply["interaction"]["response_message_id"] = str(interaction.original_message_id)
        if message is not None:
            reply["resource"]["message"] = payloads.message(state, message, base)
        return reply

    def execute_webhook(
        self, application_id: int, token: str, body: payloads.Payload, files: list[UploadedFile]
    ) -> Message:
        """POST /webhooks/{app}/{token}: the first one after a type 5 replaces the loading reply."""
        interaction = self._by_token(application_id, token)
        if interaction.response is None:
            raise errors.unknown_webhook()
        mb = MessageBody.parse(body, files)
        if interaction.loading and interaction.original_message_id is not None:
            message = self.state.message(interaction.channel_id, interaction.original_message_id)
            self.state.edit_message(message, mb, clear_loading=True)
            interaction.loading = False
            self.gateway.message_update(message)
        else:
            ephemeral = bool(_flags(mb) & components.EPHEMERAL)
            message = self._post(interaction, mb, ephemeral=ephemeral, followup=True)
            if interaction.settled.is_set():
                interaction.followup_ids.append(message.id)
                interaction.followed.set()
        interaction.settle(message.id)
        return message

    def webhook_message(self, application_id: int, token: str, ref: str) -> Message:
        interaction = self._by_token(application_id, token)
        message_id = interaction.original_message_id if ref == "@original" else int(ref)
        if message_id is None:
            raise errors.unknown_message()
        message = self.state.find_message(message_id)
        metadata = message.interaction_metadata or {}
        if message_id != interaction.message_id and metadata.get("id") != str(interaction.id):
            raise errors.unknown_message()
        return message

    def edit_webhook_message(
        self,
        application_id: int,
        token: str,
        ref: str,
        body: payloads.Payload,
        files: list[UploadedFile],
    ) -> Message:
        interaction = self._by_token(application_id, token)
        message = self.webhook_message(application_id, token, ref)
        self.state.edit_message(message, MessageBody.parse(body, files), clear_loading=True)
        if interaction.loading and message.id == interaction.original_message_id:
            interaction.loading = False
        interaction.settle(message.id)
        self.gateway.message_update(message)
        return message

    def delete_webhook_message(self, application_id: int, token: str, ref: str) -> None:
        message = self.webhook_message(application_id, token, ref)
        self.state.delete_message(message.channel_id, message.id)
        self.gateway.message_delete(message)

    def _by_token(self, application_id: int, token: str) -> Interaction:
        interaction = self.by_token.get(token)
        if application_id != self.state.application_id or interaction is None:
            raise errors.unknown_webhook()
        if time.monotonic() - interaction.created > self.config.interaction_token_seconds:
            raise errors.unknown_webhook()
        return interaction

    def _post(
        self,
        interaction: Interaction,
        body: MessageBody,
        *,
        ephemeral: bool,
        extra_flags: int = 0,
        followup: bool = False,
    ) -> Message:
        state = self.state
        metadata: payloads.Payload = {
            "id": str(interaction.id),
            "type": interaction.type,
            "user": payloads.user(state.users[interaction.user_id]),
            "authorizing_integration_owners": {"0": str(state.guild.id)},
        }
        if interaction.name:
            metadata["name"] = interaction.name
        if interaction.message_id is not None:
            metadata["interacted_message_id"] = str(interaction.message_id)
        if followup and interaction.original_message_id is not None:
            metadata["original_response_message_id"] = str(interaction.original_message_id)
        message = state.post_message(
            interaction.channel_id,
            state.bot_user.id,
            body,
            message_type=20 if interaction.type == APPLICATION_COMMAND else 0,
            webhook_id=state.application_id,
            interaction_metadata=metadata,
            ephemeral_for=interaction.user_id if ephemeral else None,
            extra_flags=extra_flags,
        )
        self.gateway.message_create(message)
        return message

    def _open_modal(self, interaction: Interaction, data: payloads.Payload) -> None:
        problems: dict[str, tuple[str, str]] = {}
        title = data.get("title")
        if not isinstance(title, str) or not 1 <= len(title) <= 45:
            problems["data.title"] = ("BASE_TYPE_BAD_LENGTH", "Must be between 1 and 45 long.")
        custom_id = data.get("custom_id")
        if not isinstance(custom_id, str) or not 1 <= len(custom_id) <= 100:
            problems["data.custom_id"] = ("BASE_TYPE_BAD_LENGTH", "Must be 1 to 100 long.")
        rows = data.get("components")
        if not isinstance(rows, list) or not 1 <= len(rows) <= 5:
            problems["data.components"] = ("BASE_TYPE_BAD_LENGTH", "Must be 1 to 5 long.")
        if problems or not isinstance(rows, list):
            raise errors.invalid_form(problems)
        if self.config.strict:
            components.validate(rows, v2=False, modal=True)
        stored = {"custom_id": custom_id, "title": title, "components": components.assign_ids(rows)}
        interaction.modal = stored
        self.open_modals[interaction.user_id] = OpenModal(
            interaction.id, interaction.channel_id, interaction.message_id, stored
        )


def upload_from_spec(state: SimState, spec: Any, index: int = 0) -> UploadedFile:
    """A file a fake user sends: an attachment ID (its bytes are reused) or {filename, data_base64?,
    content_type?}. Without data_base64 it is a 1x1 PNG, enough for a placeholder screenshot."""
    if isinstance(spec, (int, str)) and str(spec).isdigit():
        existing = state.attachments.get(int(spec))
        if existing is None:
            raise ControlError(404, f"No attachment {spec}.")
        return UploadedFile(index, existing.filename, existing.content_type, existing.data)
    if not isinstance(spec, dict):
        raise ControlError(400, "An attachment is an ID or {filename, data_base64?}.")
    raw = spec.get("data_base64")
    try:
        data = base64.b64decode(raw, validate=True) if raw else PLACEHOLDER_PNG
    except (binascii.Error, ValueError):
        raise ControlError(400, "data_base64 isn't valid base64.") from None
    filename = str(spec.get("filename") or "screenshot.png")
    return UploadedFile(index, filename, spec.get("content_type"), data)


def _flags(body: MessageBody) -> int:
    return int(body.flags) if body.flags is not MISSING else 0


def _is_user(state: SimState, value: Any) -> bool:
    try:
        state.find_user(value)
    except errors.DiscordError:
        return False
    return True


def _resolved_channel(state: SimState, channel: Channel, viewer_id: int) -> payloads.Payload:
    data: payloads.Payload = {
        "id": str(channel.id),
        "type": channel.type,
        "name": channel.name,
        "permissions": str(state.channel_permissions(viewer_id, channel)),
        "parent_id": str(channel.parent_id) if channel.parent_id else None,
    }
    if channel.guild_id is not None:
        data["guild_id"] = str(channel.guild_id)
    if channel.type in VOICE_TYPES:
        data["bitrate"] = channel.bitrate
    return data
