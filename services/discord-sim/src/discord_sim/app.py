"""The aiohttp application: REST v10, the gateway, attachments and the control API on one port."""

from __future__ import annotations

from aiohttp import web

from discord_sim import control, rest
from discord_sim.config import Config
from discord_sim.context import SIM, Sim
from discord_sim.http import api_middleware, control_middleware

MAX_UPLOAD_BYTES = 30 * 1024 * 1024  # Above Discord's 25 MB, so its own 20 MB check is what bites.


def create_app(config: Config | None = None) -> web.Application:
    sim = Sim.create(config or Config.from_env())
    app = web.Application(
        middlewares=[control_middleware, api_middleware], client_max_size=MAX_UPLOAD_BYTES
    )
    app[SIM] = sim
    rest.setup(app)
    control.setup(app)
    app.router.add_get("/gateway", sim.gateway.handle)
    app.router.add_get("/gateway/", sim.gateway.handle)
    app.on_shutdown.append(_shutdown)
    return app


async def _shutdown(app: web.Application) -> None:
    """Close what never ends by itself: gateway sockets and /_sim/events streams."""
    sim = app[SIM]
    sim.log.close()
    await sim.gateway.shutdown()
