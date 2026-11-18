"""/channels: fetch, edit, delete, permission overwrites, invites and voice status."""

from __future__ import annotations

from aiohttp import web

from discord_sim import errors, payloads
from discord_sim.context import Sim, sim_of
from discord_sim.http import json_response, no_content, read_json_object, snowflake_param
from discord_sim.state import Channel

routes = web.RouteTableDef()


@routes.get(r"/api/v10/channels/{channel_id:\d+}")
async def get_channel(request: web.Request) -> web.Response:
    sim = sim_of(request)
    channel = sim.state.channel(snowflake_param(request, "channel_id"))
    return json_response(payloads.channel(sim.state, channel))


@routes.patch(r"/api/v10/channels/{channel_id:\d+}")
async def edit_channel(request: web.Request) -> web.Response:
    sim = sim_of(request)
    channel = sim.state.edit_channel(
        snowflake_param(request, "channel_id"), await read_json_object(request)
    )
    return await _updated(sim, channel)


@routes.delete(r"/api/v10/channels/{channel_id:\d+}")
async def delete_channel(request: web.Request) -> web.Response:
    """Deleting a voice channel drops everyone in it out of voice, as on Discord."""
    sim = sim_of(request)
    deleted = sim.state.delete_channel(snowflake_param(request, "channel_id"))
    for change in deleted.left_voice:
        sim.gateway.voice_state_update(change)
    for child in deleted.orphans:
        sim.gateway.channel_event("CHANNEL_UPDATE", child)
    sim.gateway.channel_event("CHANNEL_DELETE", deleted.channel)
    await sim.gateway.drain()
    return json_response(payloads.channel(sim.state, deleted.channel))


@routes.put(r"/api/v10/channels/{channel_id:\d+}/permissions/{target_id:\d+}")
async def put_permission(request: web.Request) -> web.Response:
    sim = sim_of(request)
    channel = sim.state.set_overwrite(
        snowflake_param(request, "channel_id"),
        snowflake_param(request, "target_id"),
        await read_json_object(request),
    )
    await _updated(sim, channel)
    return no_content()


@routes.delete(r"/api/v10/channels/{channel_id:\d+}/permissions/{target_id:\d+}")
async def delete_permission(request: web.Request) -> web.Response:
    sim = sim_of(request)
    channel = sim.state.remove_overwrite(
        snowflake_param(request, "channel_id"), snowflake_param(request, "target_id")
    )
    await _updated(sim, channel)
    return no_content()


@routes.post(r"/api/v10/channels/{channel_id:\d+}/invites")
async def create_invite(request: web.Request) -> web.Response:
    sim = sim_of(request)
    invite = sim.state.create_invite(
        snowflake_param(request, "channel_id"),
        sim.state.bot_user.id,
        await read_json_object(request),
    )
    return json_response(payloads.invite(sim.state, invite))


@routes.get("/api/v10/invites/{code}")
async def get_invite(request: web.Request) -> web.Response:
    sim = sim_of(request)
    invite = sim.state.invites.get(request.match_info["code"])
    if invite is None:
        raise errors.unknown_invite()
    return json_response(payloads.invite(sim.state, invite))


@routes.put(r"/api/v10/channels/{channel_id:\d+}/voice-status")
async def put_voice_status(request: web.Request) -> web.Response:
    sim = sim_of(request)
    body = await read_json_object(request)
    status = body.get("status")
    sim.state.set_voice_status(
        snowflake_param(request, "channel_id"), str(status) if status is not None else None
    )
    return no_content()


async def _updated(sim: Sim, channel: Channel) -> web.Response:
    sim.gateway.channel_event("CHANNEL_UPDATE", channel)
    await sim.gateway.drain()
    return json_response(payloads.channel(sim.state, channel))
