"""The application, its slash commands, and gateway discovery."""

from __future__ import annotations

from aiohttp import web

from discord_sim import errors, payloads
from discord_sim.context import Sim, sim_of
from discord_sim.http import json_response, read_body, snowflake_param

routes = web.RouteTableDef()


@routes.get("/api/v10/oauth2/applications/@me")
@routes.get("/api/v10/applications/@me")
async def get_application(request: web.Request) -> web.Response:
    return json_response(payloads.application(sim_of(request).state))


def _check_app(sim: Sim, request: web.Request) -> None:
    if snowflake_param(request, "application_id") != sim.state.application_id:
        raise errors.missing_access()


@routes.get(r"/api/v10/applications/{application_id:\d+}/commands")
async def get_global_commands(request: web.Request) -> web.Response:
    sim = sim_of(request)
    _check_app(sim, request)
    return json_response([payloads.command(sim.state, c) for c in sim.state.commands_for(None)])


@routes.put(r"/api/v10/applications/{application_id:\d+}/commands")
async def put_global_commands(request: web.Request) -> web.Response:
    return await _put_commands(request, None)


@routes.get(r"/api/v10/applications/{application_id:\d+}/guilds/{guild_id:\d+}/commands")
async def get_guild_commands(request: web.Request) -> web.Response:
    sim = sim_of(request)
    _check_app(sim, request)
    guild = sim.state.require_guild(snowflake_param(request, "guild_id"))
    return json_response([payloads.command(sim.state, c) for c in sim.state.commands_for(guild.id)])


@routes.put(r"/api/v10/applications/{application_id:\d+}/guilds/{guild_id:\d+}/commands")
async def put_guild_commands(request: web.Request) -> web.Response:
    return await _put_commands(request, snowflake_param(request, "guild_id"))


async def _put_commands(request: web.Request, guild_id: int | None) -> web.Response:
    sim = sim_of(request)
    _check_app(sim, request)
    body, _files = await read_body(request)
    if not isinstance(body, list):
        raise errors.invalid_form({"_": ("LIST_TYPE_CONVERT", "Only iterables may be used.")})
    commands = sim.state.put_commands(guild_id, body)
    return json_response([payloads.command(sim.state, c) for c in commands])


@routes.get("/api/v10/gateway")
async def get_gateway(request: web.Request) -> web.Response:
    return json_response({"url": _gateway_url(sim_of(request), request)})


@routes.get("/api/v10/gateway/bot")
async def get_gateway_bot(request: web.Request) -> web.Response:
    sim = sim_of(request)
    return json_response(
        {
            "url": _gateway_url(sim, request),
            "shards": 1,
            "session_start_limit": {
                "total": 1000,
                "remaining": 1000,
                "reset_after": 0,
                "max_concurrency": 1,
            },
        }
    )


def _gateway_url(sim: Sim, request: web.Request) -> str:
    return sim.base_url(request).replace("http", "ws", 1) + "/gateway"
