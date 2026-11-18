"""/channels/{id}/messages: send (JSON or multipart), history, fetch, edit and delete."""

from __future__ import annotations

from aiohttp import web

from discord_sim import errors, payloads
from discord_sim.context import Sim, sim_of
from discord_sim.http import json_response, no_content, read_body, snowflake_param
from discord_sim.message_body import MessageBody
from discord_sim.state import Message

routes = web.RouteTableDef()

MESSAGE = r"/api/v10/channels/{channel_id:\d+}/messages/{message_id:\d+}"


def _render(sim: Sim, request: web.Request, message: Message) -> payloads.Payload:
    """Without the Message Content intent, other people's messages come back blank."""
    state = sim.state
    hide = (
        not sim.config.message_content_intent
        and message.author_id != state.bot_user.id
        and message.channel_id not in state.dm_channels
        and state.bot_user.id not in message.mentions
    )
    return payloads.message(state, message, sim.base_url(request), hide_content=hide)


@routes.get(r"/api/v10/channels/{channel_id:\d+}/messages")
async def history(request: web.Request) -> web.Response:
    sim = sim_of(request)
    query = request.query
    try:
        limit = int(query.get("limit", "50"))
        anchors = {k: int(query[k]) for k in ("before", "after", "around") if k in query}
    except ValueError:
        raise errors.invalid_form(
            {"limit": ("NUMBER_TYPE_COERCE", "Value is not int or snowflake.")}
        ) from None
    if not 1 <= limit <= 100:
        raise errors.invalid_form({"limit": ("NUMBER_TYPE_MAX", "Must be between 1 and 100.")})
    messages = sim.state.history(snowflake_param(request, "channel_id"), limit=limit, **anchors)
    return json_response([_render(sim, request, m) for m in messages])


@routes.post(r"/api/v10/channels/{channel_id:\d+}/messages")
async def send(request: web.Request) -> web.Response:
    sim = sim_of(request)
    data, files = await read_body(request)
    if not isinstance(data, dict):
        raise errors.invalid_form({"_": ("DICT_TYPE_CONVERT", "Only dictionaries may be used.")})
    message = sim.state.post_message(
        snowflake_param(request, "channel_id"),
        sim.state.bot_user.id,
        MessageBody.parse(data, files),
    )
    sim.gateway.message_create(message)
    await sim.gateway.drain()
    return json_response(_render(sim, request, message))


@routes.get(MESSAGE)
async def fetch(request: web.Request) -> web.Response:
    sim = sim_of(request)
    message = sim.state.message(
        snowflake_param(request, "channel_id"), snowflake_param(request, "message_id")
    )
    if message.ephemeral:
        raise errors.unknown_message()
    return json_response(_render(sim, request, message))


@routes.patch(MESSAGE)
async def edit(request: web.Request) -> web.Response:
    sim = sim_of(request)
    message = sim.state.message(
        snowflake_param(request, "channel_id"), snowflake_param(request, "message_id")
    )
    if message.ephemeral:
        raise errors.unknown_message()
    if message.author_id != sim.state.bot_user.id:
        raise errors.edit_others_message()
    data, files = await read_body(request)
    if not isinstance(data, dict):
        raise errors.invalid_form({"_": ("DICT_TYPE_CONVERT", "Only dictionaries may be used.")})
    sim.state.edit_message(message, MessageBody.parse(data, files))
    sim.gateway.message_update(message)
    await sim.gateway.drain()
    return json_response(_render(sim, request, message))


@routes.delete(MESSAGE)
async def delete(request: web.Request) -> web.Response:
    sim = sim_of(request)
    channel_id = snowflake_param(request, "channel_id")
    message = sim.state.message(channel_id, snowflake_param(request, "message_id"))
    if message.ephemeral:
        raise errors.unknown_message()
    sim.state.delete_message(channel_id, message.id)
    sim.gateway.message_delete(message)
    await sim.gateway.drain()
    return no_content()
