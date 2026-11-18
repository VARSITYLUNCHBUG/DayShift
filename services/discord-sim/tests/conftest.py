"""Fixtures: a sim on a random port, and a real discord.py client connected to it."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Callable

import aiohttp
import discord.gateway
import discord.http
import pytest
import yarl
from aiohttp import web

from discord_sim.app import create_app
from discord_sim.config import Config

from .support import Connected, Recorder, RunningSim, SimClient, connect


@pytest.fixture
async def running() -> AsyncIterator[RunningSim]:
    app = create_app(Config(port=0, interaction_ack_seconds=3.0))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    host, port = runner.addresses[0][:2]
    async with aiohttp.ClientSession() as session:
        yield RunningSim(app, f"http://{host}:{port}", session)
    await runner.cleanup()


@pytest.fixture
def point_at(monkeypatch: pytest.MonkeyPatch) -> Callable[[str], None]:
    """Override discord.py's hard-coded hosts, as bot/client.py does with DISCORD_API_BASE."""

    def apply(url: str) -> None:
        monkeypatch.setattr(discord.http.Route, "BASE", f"{url}/api/v10")
        monkeypatch.setattr(
            discord.gateway.DiscordWebSocket,
            "DEFAULT_GATEWAY",
            yarl.URL(url.replace("http", "ws", 1) + "/gateway"),
        )

    return apply


@pytest.fixture
async def connected(
    running: RunningSim, point_at: Callable[[str], None]
) -> AsyncIterator[Connected]:
    point_at(running.url)
    client = SimClient(Recorder())
    task = await connect(client)
    try:
        yield Connected(running, client, client.recorder)
    finally:
        await client.close()
        with contextlib.suppress(asyncio.CancelledError):
            await task
