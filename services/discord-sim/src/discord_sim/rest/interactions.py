"""Interaction callbacks and the interaction webhook (followups, @original). No auth needed."""

from __future__ import annotations

from aiohttp import web

from discord_sim import errors, payloads
from discord_sim.context import sim_of
from discord_sim.http import json_response, no_content, read_body, snowflake_param
from discord_sim.message_body import UploadedFile

routes = web.RouteTableDef()

WEBHOOK = r"/api/v10/webhooks/{application_id:\d+}/{token}"
WEBHOOK_MESSAGE = WEBHOOK + r"/messages/{message_ref:\d+|@original}"


async def _object_body(
    request: web.Request,
) -> tuple[payloads.Payload, list[UploadedFile]]:
    data, files = await read_body(request)
    if not isinstance(data, dict):
        raise errors.invalid_form({"_": ("DICT_TYPE_CONVERT", "Only dictionaries may be used.")})
    return data, files


@routes.post(r"/api/v10/interactions/{interaction_id:\d+}/{token}/callback")
async def callback(request: web.Request) -> web.Response:
    """The bot's first answer. With `with_response=1` (discord.py always sends it), a body."""
    sim = sim_of(request)
    body, files = await _object_body(request)
    reply = sim.interactions.callback(
        snowflake_param(request, "interaction_id"),
        request.match_info["token"],
        body,
        files,
        sim.base_url(request),
    )
    await sim.gateway.drain()
    if request.query.get("with_response", "").lower() in {"1", "true"}:
        return json_response(reply)
    return no_content()


@routes.post(WEBHOOK)
async def execute(request: web.Request) -> web.Response:
    sim = sim_of(request)
    body, files = await _object_body(request)
    message = sim.interactions.execute_webhook(
        snowflake_param(request, "application_id"), request.match_info["token"], body, files
    )
    await sim.gateway.drain()
    if request.query.get("wait", "").lower() in {"1", "true"}:
        return json_response(payloads.message(sim.state, message, sim.base_url(request)))
    return no_content()


@routes.get(WEBHOOK_MESSAGE)
async def get_message(request: web.Request) -> web.Response:
    sim = sim_of(request)
    message = sim.interactions.webhook_message(
        snowflake_param(request, "application_id"),
        request.match_info["token"],
        request.match_info["message_ref"],
    )
    return json_response(payloads.message(sim.state, message, sim.base_url(request)))


@routes.patch(WEBHOOK_MESSAGE)
async def edit_message(request: web.Request) -> web.Response:
    sim = sim_of(request)
    body, files = await _object_body(request)
    message = sim.interactions.edit_webhook_message(
        snowflake_param(request, "application_id"),
        request.match_info["token"],
        request.match_info["message_ref"],
        body,
        files,
    )
    await sim.gateway.drain()
    return json_response(payloads.message(sim.state, message, sim.base_url(request)))


@routes.delete(WEBHOOK_MESSAGE)
async def delete_message(request: web.Request) -> web.Response:
    sim = sim_of(request)
    sim.interactions.delete_webhook_message(
        snowflake_param(request, "application_id"),
        request.match_info["token"],
        request.match_info["message_ref"],
    )
    await sim.gateway.drain()
    return no_content()
