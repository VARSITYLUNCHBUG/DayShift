"""The bot process: gateway connection, startup recovery and the two background loops."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import time

import discord
from discord import app_commands
from django.conf import settings

from bot.commands.registry import all_commands
from bot.db import db
from bot.effects.gateway import DiscordGateway
from bot.effects.worker import EffectWorker
from bot.error_log import ErrorSink, discord_error_handler

# Importing the handlers registers them with the router.
from bot.handlers import alerts as _alerts  # noqa: F401
from bot.handlers import draft as _draft  # noqa: F401
from bot.handlers import lobby as _lobby  # noqa: F401
from bot.handlers import queue as _queue  # noqa: F401
from bot.handlers import results as _results  # noqa: F401
from bot.handlers import subs as _subs  # noqa: F401
from bot.routing import RouteButton, RouteSelect, RouteUserSelect
from league import log_context
from league.services import community as community_service
from league.services import deadlines, effects, prio

logger = logging.getLogger(__name__)

DEADLINE_INTERVAL_SECONDS = 1.0
EFFECT_IDLE_SECONDS = 0.5
PRUNE_INTERVAL_SECONDS = 24 * 3600


class DraftBot(discord.Client):
    def __init__(self) -> None:
        # The bot moves members but never joins voice itself, so it has no use for voice libraries.
        discord.VoiceClient.warn_nacl = False
        discord.VoiceClient.warn_dave = False
        # None is privileged. Guild messages only tell us that someone chatted in a match channel;
        # without the Message Content intent the bot can't read what they said.
        intents = discord.Intents.none()
        intents.guilds = True
        intents.voice_states = True
        intents.guild_messages = True
        super().__init__(
            intents=intents,
            allowed_mentions=discord.AllowedMentions.none(),
            max_messages=None,  # Nothing reads the message cache, so don't spend memory on it.
        )
        self.tree = _Tree(self)
        self.gateway = DiscordGateway(self)
        self.worker = EffectWorker(self.gateway, on_lane_done=self.wake_effects)
        self._effects_wake = asyncio.Event()
        self._started = False
        self._tasks: list[asyncio.Task[None]] = []
        self.error_sink = ErrorSink(
            self, self._error_channel, settings.ERROR_LOG_CHANNEL_ID or None
        )

    def wake_effects(self) -> None:
        """Called after each click, so board updates follow immediately rather than on a poll."""
        self._effects_wake.set()

    async def setup_hook(self) -> None:
        discord_error_handler.bind(asyncio.get_running_loop())
        self.add_dynamic_items(RouteButton, RouteSelect, RouteUserSelect)
        for command in all_commands():
            self.tree.add_command(command)
        if settings.DISCORD_GUILD_ID:
            guild = discord.Object(id=settings.DISCORD_GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)  # Guild commands update instantly.
        else:
            await self.tree.sync()

    async def on_ready(self) -> None:
        logger.info("Connected", extra={"user": str(self.user), "guilds": len(self.guilds)})
        if self._started:
            # on_ready fires again after a full reconnect. Discord doesn't replay voice moves
            # made while the bot was away, so catch the priority list up again.
            await self._reconcile_prio()
            return
        self._started = True
        queue = discord_error_handler.queue
        if queue is not None:
            self._tasks.append(asyncio.create_task(self.error_sink.run(queue), name="errors"))
        extended = await db(deadlines.extend_past_due)
        logger.info("Startup grace applied", extra={"extended": extended})
        await db(effects.request_reconcile)
        await self._sweep_stale_channels()
        # Before the deadline loop starts, or its first pass would expire the grace of anyone
        # who came back to the Waiting Room while the bot was down.
        await self._reconcile_prio()
        self._tasks += [
            asyncio.create_task(self._deadline_loop(), name="deadlines"),
            asyncio.create_task(self._effect_loop(), name="effects"),
        ]

    async def _error_channel(self, guild_id: int) -> int | None:
        return await db(community_service.error_channel, guild_id)

    async def _sweep_stale_channels(self) -> None:
        """Delete channels whose cleanup failed for good. By stored ID only, never by name."""
        for match_id, kind, channel_id in await db(effects.stale_resources):
            try:
                await self.gateway.delete_channel(channel_id)
                await db(effects.mark_resource_deleted, match_id, kind)
            except discord.HTTPException:
                logger.exception("Sweep failed", extra={"match": match_id, "channel": channel_id})

    async def _reconcile_prio(self) -> None:
        """Catch the priority list up with voice moves made while the bot was down."""
        try:
            communities = await db(prio.tracked_communities)
        except Exception:
            logger.exception("Priority list catch-up failed")
            return  # Never stop startup over it: the list catches up at the next match end.
        for community in communities:
            try:
                waiting = self.gateway.voice_members(
                    community.discord_guild_id, community.waiting_room_channel_id
                )
                if waiting is None:
                    continue  # Discord hasn't sent that server yet; it isn't an empty room.
                await db(prio.reconcile, community.pk, waiting)
            except Exception:
                logger.exception(
                    "Priority list catch-up failed", extra={"guild": community.discord_guild_id}
                )

    async def _deadline_loop(self) -> None:
        last_prune = time.monotonic()
        while True:
            try:
                fired = await db(deadlines.tick)
                if fired:
                    self.wake_effects()
                settings.BOT_HEARTBEAT_FILE.touch()
                if time.monotonic() - last_prune > PRUNE_INTERVAL_SECONDS:
                    last_prune = time.monotonic()
                    await db(effects.prune_finished)
            except Exception:
                logger.exception("Deadline loop error")
            await asyncio.sleep(DEADLINE_INTERVAL_SECONDS)

    async def _effect_loop(self) -> None:
        """Hand due effects to per-match lanes. Wakes on a click, a fired timer or a lane ending."""
        while True:
            try:
                self._effects_wake.clear()
                await self.worker.dispatch()
            except Exception:
                logger.exception("Effect loop error")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._effects_wake.wait(), EFFECT_IDLE_SECONDS)

    async def on_message(self, message: discord.Message) -> None:
        """Chat is welcome in match channels, but the board has to stay in view."""
        if message.guild is None or self.user is None or message.author.id == self.user.id:
            return
        with log_context.bind(guild=message.guild.id):
            try:
                await db(effects.note_chat, message.channel.id)
            except Exception:
                logger.exception("Couldn't note chat", extra={"channel": message.channel.id})

    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ) -> None:
        """Joining the Waiting Room after your lobby popped moves you straight into it."""
        if before.channel == after.channel:
            return  # Mute, deafen, stream and the like.
        with log_context.bind(guild=member.guild.id):
            await self._update_prio(member, before.channel, after.channel)
            await self._auto_move(member, after.channel)

    async def _update_prio(
        self,
        member: discord.Member,
        before: discord.VoiceChannel | discord.StageChannel | None,
        after: discord.VoiceChannel | discord.StageChannel | None,
    ) -> None:
        """The priority list follows the Waiting Room. Bots (music, recording) don't queue."""
        if member.bot:
            return
        try:
            community = await db(community_service.get, member.guild.id)
            if community is None or not community.waiting_room_channel_id:
                return
            await db(
                prio.on_voice_state,
                community.pk,
                community.waiting_room_channel_id,
                member.id,
                member.display_name,
                before.id if before else None,
                after.id if after else None,
            )
            self.wake_effects()
        except Exception:
            logger.exception(
                "Priority list update failed", extra={"user": member.id, "guild": member.guild.id}
            )

    async def _auto_move(
        self, member: discord.Member, channel: discord.VoiceChannel | discord.StageChannel | None
    ) -> None:
        if channel is None:
            return  # They left voice.
        try:
            target = await db(effects.on_voice_join, member.id, channel.id)
            if target is not None:
                await self.gateway.move_member(target[0], member.id, target[1])
        except Exception:
            logger.exception(
                "Auto-move failed", extra={"user": member.id, "guild": member.guild.id}
            )


class _Tree(app_commands.CommandTree[DraftBot]):
    async def on_error(
        self, interaction: discord.Interaction[DraftBot], error: app_commands.AppCommandError
    ) -> None:
        """Errors outside `guarded`, such as a bad argument. Tagged with their server."""
        with log_context.bind(guild=interaction.guild_id, interaction=interaction.id):
            command = interaction.command.name if interaction.command else None
            logger.error("Command error", extra={"command": command}, exc_info=error)


def run() -> None:
    if not settings.DISCORD_TOKEN:
        raise SystemExit("DISCORD_TOKEN isn't set. Add it to .env.")
    # In a container the bot is PID 1, which ignores SIGTERM by default, so `docker compose stop`
    # waited out the grace period and then killed it. Treat SIGTERM like Ctrl+C: discord.py then
    # closes the connection cleanly, and any effect cut short stays pending and runs on restart.
    signal.signal(signal.SIGTERM, _stop_on_sigterm)
    bot = DraftBot()
    # Only the bot process posts errors to Discord, so this isn't in settings.LOGGING, which the
    # web process and tests share. It's bound to the loop once that's running (setup_hook).
    logging.getLogger().addHandler(discord_error_handler)
    bot.run(settings.DISCORD_TOKEN, log_handler=None)


def _stop_on_sigterm(signum: int, frame: object) -> None:
    logger.info("SIGTERM received, shutting down")
    raise KeyboardInterrupt
