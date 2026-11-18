"""/users: the bot's own user, other users, and opening DM channels."""

from __future__ import annotations

from aiohttp import web

from discord_sim import errors, payloads
from discord_sim.context import sim_of
from discord_sim.http import json_response, read_json_object, snowflake_param

routes = web.RouteTableDef()


@routes.get("/api/v10/users/@me")
async def get_me(request: web.Request) -> web.Response:
    sim = sim_of(request)
    return json_response(
        payloads.user(sim.state.bot_user) | {"verified": True, "mfa_enabled": False}
    )


@routes.get(r"/api/v10/users/{user_id:\d+}")
async def get_user(request: web.Request) -> web.Response:
    sim = sim_of(request)
    return json_response(payloads.user(sim.state.user(snowflake_param(request, "user_id"))))


@routes.post("/api/v10/users/@me/channels")
async def open_dm(request: web.Request) -> web.Response:
    """Opening a DM always works; whether the user accepts DMs shows when the bot sends."""
    sim = sim_of(request)
    body = await read_json_object(request)
    recipient = body.get("recipient_id")
    if recipient is None or not str(recipient).isdigit():
        raise errors.invalid_form(
            {"recipient_id": ("BASE_TYPE_REQUIRED", "This field is required")}
        )
    channel = sim.state.open_dm(int(recipient))
    return json_response(payloads.channel(sim.state, channel))
