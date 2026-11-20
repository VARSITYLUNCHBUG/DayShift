"""/deadlock-api/v1: the routes the app calls on deadlock-api.com.

Point the app's `DEADLOCK_API_BASE` at `<sim>/deadlock-api`. Answers use deadlock-api's shapes;
the app treats a 404 as "not known yet" and anything else at or above 400 as a failure. The
custom lobby routes are the bot's; the hero roster is the admin's champion sync (and
`manage.py sync_champions`); Steam names are /link's.
"""

from __future__ import annotations

import time
from typing import Any

from aiohttp import web

from discord_sim.context import sim_of
from discord_sim.deadlock_api import account_ids
from discord_sim.errors import ControlError

PREFIX = "/deadlock-api/v1"

routes = web.RouteTableDef()


def _reply(request: web.Request, body: dict[str, Any], status: int = 200) -> web.Response:
    sim_of(request).log.add("deadlock_api", method=request.method, path=request.path, status=status)
    return web.json_response(body, status=status)


@routes.post(f"{PREFIX}/matches/custom/create")
async def create(request: web.Request) -> web.Response:
    sim = sim_of(request)
    try:
        body = await request.json() if request.can_read_body else {}
    except ValueError:
        body = {}
    region = str(body.get("server_region") or "") if isinstance(body, dict) else ""
    lobby = sim.deadlock_api.create(str(sim.state.ids.next()), region)
    if lobby is None:
        return _reply(request, {"error": "The lobby bot is unavailable (simulated)."}, 503)
    return _reply(
        request,
        {"party_id": lobby.party_id, "party_code": lobby.party_code, "created": int(time.time())},
    )


@routes.post(PREFIX + "/matches/custom/{party_id}/start")
async def start(request: web.Request) -> web.Response:
    lobby = sim_of(request).deadlock_api.lobbies.get(request.match_info["party_id"])
    if lobby is None:
        return _reply(request, {"error": "Unknown party."}, 404)
    lobby.started = True
    return _reply(request, {"ok": True})


@routes.get(PREFIX + "/matches/custom/{party_id}/match-id")
@routes.get(PREFIX + "/matches/{match_id}/metadata")
@routes.get(PREFIX + "/matches/metadata")
async def unknown(request: web.Request) -> web.Response:
    """Nothing is ever played, so no match has an ID or metadata."""
    return _reply(request, {"error": "Not found."}, 404)


@routes.get(f"{PREFIX}/assets/heroes")
async def heroes(request: web.Request) -> web.Response:
    """The hero roster as a JSON list; `?only_active=true` leaves out heroes nobody can pick."""
    only_active = request.query.get("only_active", "").lower() == "true"
    roster = sim_of(request).deadlock_api.roster(only_active=only_active)
    sim_of(request).log.add("deadlock_api", method=request.method, path=request.path, status=200)
    return web.json_response(roster)


@routes.get(f"{PREFIX}/players/steam")
async def steam(request: web.Request) -> web.Response:
    """Steam profiles for `?account_ids=1,2`, as a JSON list of the accounts it knows."""
    try:
        ids = account_ids(request.query.get("account_ids", ""))
    except ControlError as exc:
        return _reply(request, {"error": exc.error}, 400)
    rows = sim_of(request).deadlock_api.steam(ids)
    sim_of(request).log.add("deadlock_api", method=request.method, path=request.path, status=200)
    return web.json_response(rows)
