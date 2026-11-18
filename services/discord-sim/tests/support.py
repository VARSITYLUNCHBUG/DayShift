"""Helpers for the tests: a running sim, and a real discord.py client pointed at it the way
bot/client.py does it (Route.BASE and DEFAULT_GATEWAY)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import aiohttp
import discord
from aiohttp import web

from discord_sim import snowflake
from discord_sim.context import SIM, Sim

TOKEN = "sim-token"


@dataclass
class RunningSim:
    app: web.Application
    url: str
    http: aiohttp.ClientSession

    @property
    def sim(self) -> Sim:
        return self.app[SIM]

    async def call(self, method: str, path: str, body: Any = None, status: int = 200) -> Any:
        """A control API call that must answer with `status`."""
        async with self.http.request(method, self.url + path, json=body) as response:
            data = await response.json(content_type=None)
            assert response.status == status, (response.status, data)
            return data


@dataclass
class Recorder:
    """What a test client saw: events by name, in order."""

    events: dict[str, list[Any]] = field(default_factory=dict)
    changed: asyncio.Event = field(default_factory=asyncio.Event)

    def add(self, name: str, value: Any) -> None:
        self.events.setdefault(name, []).append(value)
        self.changed.set()

    async def wait_for(self, name: str, count: int = 1, timeout: float = 5.0) -> list[Any]:
        async with asyncio.timeout(timeout):
            while len(self.events.get(name, [])) < count:
                self.changed.clear()
                await self.changed.wait()
        return self.events[name]


class SimClient(discord.Client):
    """The bot's intents (guilds, voice states, guild messages), recording what arrives."""

    def __init__(self, recorder: Recorder) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        intents.voice_states = True
        intents.guild_messages = True
        super().__init__(intents=intents, max_messages=None, guild_ready_timeout=0.1)
        self.recorder = recorder
        self.tree = discord.app_commands.CommandTree(self)

    async def before_identify_hook(self, shard_id: int | None, *, initial: bool = False) -> None:
        """discord.py waits 5 s before identifying again (after a reset); the sim needs no wait."""

    async def on_ready(self) -> None:
        self.recorder.add("ready", self.user)

    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ) -> None:
        self.recorder.add("voice", (member.id, after.channel.id if after.channel else None))

    async def on_message(self, message: discord.Message) -> None:
        self.recorder.add("message", message)

    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel) -> None:
        self.recorder.add("channel_create", channel)


@dataclass
class Connected:
    sim: RunningSim
    client: SimClient
    recorder: Recorder

    @property
    def guild(self) -> discord.Guild:
        guild = self.client.get_guild(snowflake.GUILD_ID)
        assert guild is not None
        return guild

    def text_channel(self, channel_id: int = snowflake.GENERAL_TEXT_ID) -> discord.TextChannel:
        channel = self.guild.get_channel(channel_id)
        assert isinstance(channel, discord.TextChannel)
        return channel


async def connect(client: SimClient) -> asyncio.Task[None]:
    """Start the client and wait for on_ready."""
    task = asyncio.create_task(client.start(TOKEN))
    async with asyncio.timeout(10):
        await client.recorder.wait_for("ready")
    return task
