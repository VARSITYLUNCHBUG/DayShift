"""The bot process: gateway connection, startup recovery and its background loops.

One process runs everything: the Discord connection and clicks, the effect worker, the deadline
loop (timers and the daily prune) and the health watchdog. Deadlines only read and write the
database; the effects they queue are picked up by the effect loop, which also polls the outbox
every `EFFECT_IDLE_SECONDS`.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import signal
import time
from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

import discord
import httpx
import yarl
from discord import app_commands
from discord.gateway import DiscordWebSocket
from django.conf import settings

from bot import request_health
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
from bot.handlers import swaps as _swaps  # noqa: F401
from bot.ratelimits import install as install_ratelimit_compatibility
from bot.request_health import FailedRequests
from bot.routing import RouteButton, RouteSelect, RouteUserSelect
from bot.watched import ChannelWatch
from league import log_context, timings
from league.services import community as community_service
from league.services import deadlines, effects, health, leaderboards
from league.services.common import now

logger = logging.getLogger(__name__)

DEADLINE_INTERVAL_SECONDS = 1.0
# The effect loop's fallback poll. A click, a fired timer and a finished lane wake it at once,
# and it sleeps only until the next delayed effect is due; the poll is for effects nothing in
# this process wakes it for, such as a retry staff start from the admin.
EFFECT_IDLE_SECONDS = 2.0
# Shortest sleep before a delayed effect, so a clock rounding to now never spins the loop.
EFFECT_MIN_WAIT_SECONDS = 0.01
# How often the timing summary (league.timings) is logged.
TIMINGS_INTERVAL_SECONDS = 60.0
PRUNE_INTERVAL_SECONDS = 24 * 3600
# How often the watchdog checks the league is keeping up, and pings HEALTHCHECK_PING_URL.
WATCHDOG_INTERVAL_SECONDS = 60.0
# A loop that keeps failing logs the same kind of error with its traceback at most this often.
ERROR_REPEAT_SECONDS = 60.0
# Waits between attempts at the gateway's startup recovery; the last one repeats.
STARTUP_RETRY_SECONDS = (1.0, 2.0, 5.0, 10.0, 30.0)
# The longest rate-limit wait discord.py sleeps through; longer ones come back as RateLimited.
RATE_LIMIT_WAIT_SECONDS = 60.0
# discord.py's own endpoints. Only a dev or test setup points the bot anywhere else.
DISCORD_API_BASE = "https://discord.com/api/v10"
DISCORD_GATEWAY_URL = "wss://gateway.discord.gg/"


def effect_wait(next_due: datetime | None, moment: datetime | None = None) -> float:
    """Seconds the effect loop sleeps: until `next_due`, at most `EFFECT_IDLE_SECONDS`."""
    if next_due is None:
        return EFFECT_IDLE_SECONDS
    seconds = (next_due - (moment or now())).total_seconds()
    return min(EFFECT_IDLE_SECONDS, max(EFFECT_MIN_WAIT_SECONDS, seconds))


class Heartbeat:
    """Touches the healthcheck's file each time every one of `loops` has gone round since the last
    touch, so one stuck loop is enough to make the process unhealthy."""

    def __init__(self, path: Path, loops: Iterable[str]) -> None:
        self.path = path
        self._loops = frozenset(loops)
        self._waiting = set(self._loops)

    def beat(self, loop: str) -> None:
        self._waiting.discard(loop)
        if not self._waiting:
            self.path.touch()
            self._waiting = set(self._loops)


class LoopErrors:
    """A background loop's errors, logged without flooding.

    A database outage fails every pass, once a second. Logging each one would write a traceback
    a second and rotate the start of the incident out of the logs, so each kind of error is
    logged in full the first time and then at most every `ERROR_REPEAT_SECONDS`, and the
    recovery is logged once, with how many passes failed."""

    def __init__(self, message: str, recovered: str | None = None) -> None:
        self.message = message
        self.recovered = recovered or f"{message}: recovered"
        self.failures = 0
        self._since = 0.0
        self._logged: dict[type[BaseException], float] = {}

    def failed(self, error: BaseException) -> None:
        now = time.monotonic()
        if not self.failures:
            self._since = now
        self.failures += 1
        last = self._logged.get(type(error))
        if last is None or now - last >= ERROR_REPEAT_SECONDS:
            self._logged[type(error)] = now
            logger.error(self.message, exc_info=error, extra={"failures": self.failures})

    def passed(self) -> None:
        if self.failures:
            logger.warning(
                self.recovered,
                extra={
                    "failures": self.failures,
                    "seconds": round(time.monotonic() - self._since, 1),
                },
            )
            self.failures = 0
            self._logged.clear()


async def deadline_loop(
    heartbeat: Heartbeat,
    on_fired: Callable[[], None] | None = None,
    stop: asyncio.Event | None = None,
) -> None:
    """Fire due deadlines every second and prune old effects daily, until `stop` is set.

    A pass that is under way when `stop` is set finishes first."""
    stop = stop or asyncio.Event()
    last_prune = time.monotonic()
    errors = LoopErrors("Deadline loop error")
    while not stop.is_set():
        try:
            fired = await db(deadlines.tick)
            if fired and on_fired is not None:
                on_fired()
            heartbeat.beat("deadlines")
            if time.monotonic() - last_prune > PRUNE_INTERVAL_SECONDS:
                last_prune = time.monotonic()
                await db(effects.prune_finished)
            errors.passed()
        except Exception as exc:
            errors.failed(exc)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), DEADLINE_INTERVAL_SECONDS)


class Watchdog:
    """Checks the league is keeping up (`health.problems`) and says so when that changes.

    A new problem is logged as an ERROR, which the error log posts to the operator's channel, and
    its recovery as a WARNING. Each pass also pings `HEALTHCHECK_PING_URL` in the healthchecks.io
    style (the URL when healthy, the URL + `/fail` with the problems when not), so a dead host or
    a stuck process shows up as a ping that never arrives."""

    def __init__(self, ping_url: str = "") -> None:
        self.ping_url = ping_url.rstrip("/")
        self.problems: list[str] = []

    async def check(self) -> list[str]:
        problems = await db(health.problems)
        if problems != self.problems:
            if problems:
                logger.error("Health check failed: %s", "; ".join(problems))
            else:
                logger.warning("Health check recovered")
        self.problems = problems
        await self._ping(problems)
        return problems

    async def _ping(self, problems: list[str]) -> None:
        if not self.ping_url:
            return
        url = f"{self.ping_url}/fail" if problems else self.ping_url
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(url, content="\n".join(problems).encode())
        except httpx.HTTPError as error:
            # A warning, not an error: an error would post to Discord on every missed ping.
            logger.warning("Health ping failed", extra={"error": str(error)})


async def watchdog_loop(watchdog: Watchdog, stop: asyncio.Event | None = None) -> None:
    """Run `watchdog.check` every `WATCHDOG_INTERVAL_SECONDS` until `stop` is set."""
    stop = stop or asyncio.Event()
    errors = LoopErrors("Watchdog error")
    while not stop.is_set():
        try:
            await watchdog.check()
            errors.passed()
        except Exception as exc:
            errors.failed(exc)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), WATCHDOG_INTERVAL_SECONDS)


def command_fingerprint(tree: app_commands.CommandTree[Any], guild: discord.Object | None) -> str:
    """What a sync would send, hashed. Unchanged commands needn't be registered again, and
    Discord caps how many new ones it accepts a day."""
    payload = [command.to_dict(tree) for command in tree.get_commands(guild=guild)]
    text = json.dumps(sorted(payload, key=lambda c: str(c.get("name"))), sort_keys=True)
    return hashlib.sha256(text.encode()).hexdigest()


class DayShiftBot(discord.Client):
    def __init__(self, heartbeat_file: Path | None = None) -> None:
        # The bot moves members but never joins voice itself, so it has no use for voice libraries.
        discord.VoiceClient.warn_nacl = False
        discord.VoiceClient.warn_dave = False
        # None is privileged. Guild messages only tell us that someone chatted in a match channel;
        # without the Message Content intent the bot can't read what they said.
        intents = discord.Intents.none()
        intents.guilds = True
        intents.voice_states = True
        intents.guild_messages = True
        # Every response passes through this, to count what Discord counts against us.
        self.failed_requests = FailedRequests()
        super().__init__(
            http_trace=self.failed_requests.trace_config(),
            intents=intents,
            allowed_mentions=discord.AllowedMentions.none(),
            max_messages=None,  # Nothing reads the message cache, so don't spend memory on it.
            # discord.py waits out a 429 itself, however long, which would stall a match's
            # effect lane in place. Past a minute it raises RateLimited instead, and the worker
            # retries the effect after the wait.
            max_ratelimit_timeout=RATE_LIMIT_WAIT_SECONDS,
        )
        install_ratelimit_compatibility(self.http)
        self.tree = _Tree(self)
        self.gateway = DiscordGateway(self)
        self.watch = ChannelWatch()
        self.worker = EffectWorker(
            self.gateway, on_lane_done=self.wake_effects, on_effect_done=self.watch.request_refresh
        )
        self._effects_wake = asyncio.Event()
        self._started = False
        self._tasks: list[asyncio.Task[None]] = []
        self.heartbeat = Heartbeat(
            heartbeat_file or settings.BOT_HEARTBEAT_FILE, ("deadlines", "effects")
        )
        self.watchdog = Watchdog(settings.HEALTHCHECK_PING_URL)
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
        guild_id = settings.DISCORD_GUILD_ID or None
        guild = discord.Object(id=guild_id) if guild_id else None
        if guild is not None:
            self.tree.copy_global_to(guild=guild)  # Guild commands update instantly.
        fingerprint = command_fingerprint(self.tree, guild)
        try:
            if await db(community_service.commands_synced, guild_id, fingerprint):
                logger.info("Slash commands unchanged; not registering them again")
                return
        except Exception:
            logger.warning("Couldn't check the last command sync; syncing", exc_info=True)
        try:
            await self.tree.sync(guild=guild)
            with contextlib.suppress(Exception):  # Only costs a sync next time.
                await db(community_service.record_commands_synced, guild_id, fingerprint)
        except discord.Forbidden as exc:
            # Missing Access (50001): the bot isn't in DISCORD_GUILD_ID, or was invited without
            # the applications.commands scope. Crashing here only restarts into the same refusal,
            # and the buttons, timers and effects work without slash commands, so carry on.
            logger.error(
                "Couldn't register slash commands: re-invite the bot with the "
                "applications.commands scope, then restart it",
                extra={"guild": settings.DISCORD_GUILD_ID or None, "code": exc.code},
            )

    async def on_ready(self) -> None:
        logger.info("Connected", extra={"user": str(self.user), "guilds": len(self.guilds)})
        if self._started:
            # on_ready fires again after a full reconnect, which can miss messages: forget what
            # was last in each channel, so the next check reads it from Discord.
            self.gateway.forget_last_messages()
            return
        self._started = True
        queue = discord_error_handler.queue
        if queue is not None:
            self._tasks.append(asyncio.create_task(self.error_sink.run(queue), name="errors"))
        await self._recover()
        self._tasks.append(asyncio.create_task(self._deadline_loop(), name="deadlines"))
        self._tasks.append(asyncio.create_task(self._effect_loop(), name="effects"))
        self._tasks.append(asyncio.create_task(self._leaderboard_loop(), name="leaderboard"))
        self._tasks.append(asyncio.create_task(watchdog_loop(self.watchdog), name="watchdog"))
        self._tasks.append(asyncio.create_task(self.watch.run(), name="watched-channels"))
        self._tasks.append(asyncio.create_task(self._failed_request_loop(), name="failed-requests"))
        self._tasks.append(asyncio.create_task(self._timings_loop(), name="timings"))

    async def _recover(self) -> None:
        """Startup recovery, retried until the database answers.

        This runs once (on_ready returns early ever after), so giving up would leave a process
        that stays connected to Discord but never starts its loops. A bot that connects while
        Postgres is still coming up (a reboot, a db restart) waits here instead,
        unhealthy, and carries on when the database is back. Each step is safe to repeat."""
        errors = LoopErrors(
            "Startup recovery failed, retrying", recovered="Startup recovery done after retries"
        )
        while True:
            try:
                extended = await db(deadlines.extend_past_due)
                logger.info("Startup grace applied", extra={"extended": extended})
                await db(effects.request_reconcile)
                await self._sweep_stale_channels()
                errors.passed()
                return
            except Exception as exc:
                errors.failed(exc)
                retries = STARTUP_RETRY_SECONDS
                await asyncio.sleep(retries[min(errors.failures, len(retries)) - 1])

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

    async def _deadline_loop(self) -> None:
        await deadline_loop(self.heartbeat, on_fired=self.wake_effects)

    async def _failed_request_loop(self) -> None:
        while True:
            await asyncio.sleep(request_health.WINDOW_SECONDS)
            self.failed_requests.log_summary()

    async def _timings_loop(self) -> None:
        """Log where the last minute's time went, when anything happened (league.timings)."""
        while True:
            await asyncio.sleep(TIMINGS_INTERVAL_SECONDS)
            self.failed_requests.log_usage_summary()
            if summary := timings.summary():
                logger.info("Timings", extra={"timings": summary})

    async def _leaderboard_loop(self) -> None:
        """Redraw every server's leaderboard images on the hour, starting now, so a deploy shows
        fresh ones at once. The redraw is an ordinary effect: it coalesces with the one each
        result asks for, and a failure retries like any other."""
        errors = LoopErrors("Leaderboard refresh failed")
        while True:
            try:
                await db(leaderboards.request_all)
                self.wake_effects()
                errors.passed()
            except Exception as exc:
                errors.failed(exc)
            await asyncio.sleep(leaderboards.REFRESH_SECONDS)

    async def _effect_loop(self) -> None:
        """Hand due effects to per-match lanes. Wakes on a click, a fired timer, a lane ending,
        or when the next delayed effect is due; otherwise every `EFFECT_IDLE_SECONDS`."""
        errors = LoopErrors("Effect loop error")
        while True:
            wait = EFFECT_IDLE_SECONDS
            try:
                self._effects_wake.clear()
                looked = now()  # Before the dispatch's own look at what is due (next_due_at).
                await self.worker.dispatch()
                self.heartbeat.beat("effects")
                wait = effect_wait(await db(effects.next_due_at, looked))
                errors.passed()
            except Exception as exc:
                errors.failed(exc)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._effects_wake.wait(), wait)

    async def on_message(self, message: discord.Message) -> None:
        """Chat is welcome in match channels, but the board has to stay in view. Other
        channels cost nothing: the watch list is in memory."""
        if message.guild is None or self.user is None:
            return
        # Whoever posted it, it's now the channel's last message: the board checks against
        # this instead of reading the channel's history. Recorded for every channel (one entry
        # each), so a channel the watch list hasn't caught up with yet is still right.
        self.gateway.note_last_message(message.channel.id, message.id)
        if message.author.id == self.user.id or not self.watch.chat_matters(message.channel.id):
            return
        with log_context.bind(guild=message.guild.id):
            try:
                await db(effects.note_chat, message.channel.id)
                # It may have queued or put off a board move: sleep until that one instead.
                self.wake_effects()
            except Exception:
                logger.exception("Couldn't note chat", extra={"channel": message.channel.id})

    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent) -> None:
        """A deleted last message means the one before it is last now, which only Discord knows."""
        self.gateway.forget_last_message(payload.channel_id, payload.message_id)

    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ) -> None:
        """Joining the Waiting Room after your lobby popped moves you straight into it."""
        if before.channel == after.channel:
            return  # Mute, deafen, stream and the like.
        if after.channel is None or not self.watch.voice_matters(after.channel.id):
            return  # Left voice, or joined a channel no match uses.
        with log_context.bind(guild=member.guild.id):
            await self._auto_move(member, after.channel)

    async def _auto_move(
        self, member: discord.Member, channel: discord.VoiceChannel | discord.StageChannel | None
    ) -> None:
        if channel is None:
            return  # They left voice.
        try:
            target = await db(effects.on_voice_join, member.id, channel.id)
            if target is not None:
                # Someone waiting to be moved shouldn't queue behind other matches' setup.
                await self.gateway.move_member(target[0], member.id, target[1], paced=False)
        except Exception:
            logger.exception(
                "Auto-move failed", extra={"user": member.id, "guild": member.guild.id}
            )


class _Tree(app_commands.CommandTree[DayShiftBot]):
    async def on_error(
        self, interaction: discord.Interaction[DayShiftBot], error: app_commands.AppCommandError
    ) -> None:
        """Errors outside `guarded`, such as a bad argument. Tagged with their server."""
        with log_context.bind(guild=interaction.guild_id, interaction=interaction.id):
            command = interaction.command.name if interaction.command else None
            logger.error("Command error", extra={"command": command}, exc_info=error)


def run() -> None:
    """Connect to Discord and run until stopped."""
    if not settings.DISCORD_TOKEN:
        raise SystemExit("DISCORD_TOKEN isn't set. Add it to .env.")
    point_at_discord()
    # In a container the bot is PID 1, which ignores SIGTERM by default, so `docker compose stop`
    # waited out the grace period and then killed it. Treat SIGTERM like Ctrl+C: discord.py then
    # closes the connection cleanly, and any effect cut short stays pending and runs on restart.
    signal.signal(signal.SIGTERM, _stop_on_sigterm)
    bot = DayShiftBot()
    # Only the bot process posts errors to Discord, so this isn't in settings.LOGGING, which the
    # web process and tests share. It's bound to the loop once that's running (setup_hook).
    logging.getLogger().addHandler(discord_error_handler)
    bot.run(settings.DISCORD_TOKEN, log_handler=None)


def _stop_on_sigterm(signum: int, frame: object) -> None:
    logger.info("SIGTERM received, shutting down")
    raise KeyboardInterrupt


def point_at_discord() -> None:
    """Send REST calls and the gateway connection where settings say. Left alone for Discord.

    A stand-in gets the bot token with every call, so it only works with DEBUG on."""
    api = settings.DISCORD_API_BASE or DISCORD_API_BASE
    gateway = settings.DISCORD_GATEWAY_URL or DISCORD_GATEWAY_URL
    if api == DISCORD_API_BASE and gateway == DISCORD_GATEWAY_URL:
        return
    if not settings.DEBUG:
        raise SystemExit(
            "DISCORD_API_BASE and DISCORD_GATEWAY_URL point away from Discord, which only works"
            " with DEBUG on. Unset them in production."
        )
    discord.http.Route.BASE = api
    DiscordWebSocket.DEFAULT_GATEWAY = yarl.URL(gateway)
    logger.warning(
        "Not talking to Discord: using a stand-in", extra={"api_base": api, "gateway": gateway}
    )
