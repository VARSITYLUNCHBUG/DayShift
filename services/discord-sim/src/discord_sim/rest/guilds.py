"""/guilds: the guild, channel creation, roles and members (including voice moves)."""

from __future__ import annotations

from aiohttp import web

from discord_sim import errors, payloads
from discord_sim.context import sim_of
from discord_sim.http import json_response, read_json_object, snowflake_param

routes = web.RouteTableDef()


@routes.get(r"/api/v10/guilds/{guild_id:\d+}")
async def get_guild(request: web.Request) -> web.Response:
    sim = sim_of(request)
    sim.state.require_guild(snowflake_param(request, "guild_id"))
    return json_response(payloads.guild_rest(sim.state))


@routes.get(r"/api/v10/guilds/{guild_id:\d+}/channels")
async def get_channels(request: web.Request) -> web.Response:
    sim = sim_of(request)
    guild = sim.state.require_guild(snowflake_param(request, "guild_id"))
    return json_response([payloads.channel(sim.state, c) for c in guild.channels.values()])


@routes.post(r"/api/v10/guilds/{guild_id:\d+}/channels")
async def create_channel(request: web.Request) -> web.Response:
    """Creates a category, text or voice channel and sends CHANNEL_CREATE before replying."""
    sim = sim_of(request)
    sim.state.require_guild(snowflake_param(request, "guild_id"))
    channel = sim.state.create_channel(await read_json_object(request))
    sim.gateway.channel_event("CHANNEL_CREATE", channel)
    await sim.gateway.drain()
    return json_response(payloads.channel(sim.state, channel), 201)


@routes.get(r"/api/v10/guilds/{guild_id:\d+}/roles")
async def get_roles(request: web.Request) -> web.Response:
    sim = sim_of(request)
    guild = sim.state.require_guild(snowflake_param(request, "guild_id"))
    return json_response([payloads.role(r) for r in guild.roles.values()])


@routes.get(r"/api/v10/guilds/{guild_id:\d+}/members/{user_id:\d+}")
async def get_member(request: web.Request) -> web.Response:
    sim = sim_of(request)
    sim.state.require_guild(snowflake_param(request, "guild_id"))
    member = sim.state.member(snowflake_param(request, "user_id"))
    return json_response(payloads.member(sim.state, member))


@routes.patch(r"/api/v10/guilds/{guild_id:\d+}/members/{user_id:\d+}")
async def edit_member(request: web.Request) -> web.Response:
    """Nick, roles, server mute/deaf and voice moves. Moving someone not in voice is 40032."""
    sim = sim_of(request)
    state = sim.state
    state.require_guild(snowflake_param(request, "guild_id"))
    user_id = snowflake_param(request, "user_id")
    member = state.member(user_id)
    body = await read_json_object(request)
    if "channel_id" in body:
        target = body["channel_id"]
        change = state.move_member(user_id, int(target) if target is not None else None)
        sim.gateway.voice_state_update(change)
    voice = state.guild.voice_states.get(user_id)
    for key in ("mute", "deaf"):
        if key in body:
            if voice is None:
                raise errors.not_in_voice()
            setattr(voice, key, bool(body[key]))
    if "nick" in body:
        member.nick = body["nick"] or None
    if "roles" in body:
        roles = [int(r) for r in body["roles"] or []]
        for role_id in roles:
            state.find_role(role_id)
        member.roles = roles
    if body.keys() & {"nick", "roles", "mute", "deaf"}:
        sim.gateway.member_event("GUILD_MEMBER_UPDATE", user_id)
    await sim.gateway.drain()
    return json_response(payloads.member(state, member))
