"""Discord REST v10 under /api/v10, the CDN-style attachment host, and the deadlock-api stand-in."""

from __future__ import annotations

from aiohttp import web

from discord_sim.context import sim_of
from discord_sim.rest import (
    applications,
    channels,
    deadlock,
    guilds,
    interactions,
    messages,
    users,
)

attachment_routes = web.RouteTableDef()


@attachment_routes.get(r"/attachments/{channel_id:\d+}/{attachment_id:\d+}/{filename}")
async def get_attachment(request: web.Request) -> web.Response:
    """Uploaded files, served without auth like Discord's CDN."""
    attachment = sim_of(request).state.attachments.get(int(request.match_info["attachment_id"]))
    if attachment is None or attachment.filename != request.match_info["filename"]:
        raise web.HTTPNotFound(reason="Unknown attachment")
    return web.Response(body=attachment.data, content_type=attachment.content_type)


def setup(app: web.Application) -> None:
    for module in (users, applications, guilds, channels, messages, interactions, deadlock):
        app.router.add_routes(module.routes)
    app.router.add_routes(attachment_routes)
