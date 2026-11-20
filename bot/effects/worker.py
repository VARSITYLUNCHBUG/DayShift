"""Runs outbox effects, in order per lane, with retry and backoff.

Each match gets a main lane and a voice lane, so a slow Discord call in one match (deleting
voice channels, uploading a screenshot, waiting out a rate limit) never holds up another's board.
Work outside a match is split the same way (see `effects.lane_key`).
"""

from __future__ import annotations

import asyncio
import functools
import logging
import time
from collections.abc import Callable
from datetime import datetime

import discord

from bot.db import db
from bot.effects.gateway import ChannelGone, EditCapped, Gateway
from bot.effects.handlers import HANDLERS, Env, Later, Skip
from league import log_context, timings
from league.models import OutboxEffect
from league.models.outbox import EffectStatus
from league.services import effects, lobby, scrims
from league.services.common import now

logger = logging.getLogger(__name__)

# Discord will keep refusing these whatever we do, so retrying only delays the fallback.
_PERMANENT_STATUS = {400, 401, 403, 404}


def _due_and_next() -> tuple[list[list[OutboxEffect]], datetime | None]:
    """What is due now and when the next delayed effect is, in one trip to the database thread.
    The moment is taken before the look at what's due (see `effects.next_due_at`)."""
    looked = now()
    return effects.due_by_match(), effects.next_due_at(looked)


class EffectWorker:
    def __init__(
        self,
        gateway: Gateway,
        on_lane_done: Callable[[], None] | None = None,
        on_effect_done: Callable[[str], None] | None = None,
    ) -> None:
        self.gateway = gateway
        # Called when a lane finishes, since its effects may have queued more work.
        self.on_lane_done = on_lane_done
        # Called with each effect's kind once it has run, however it ended.
        self.on_effect_done = on_effect_done
        # One running task per lane: a match ID, or a key for work outside any match.
        self._lanes: dict[effects.Lane, asyncio.Task[int]] = {}
        # When the next delayed effect is due, as of the last dispatch. None: nothing delayed.
        self.next_due_at: datetime | None = None

    @property
    def busy_matches(self) -> set[effects.Lane]:
        return set(self._lanes)

    async def dispatch(self) -> int:
        """Start a task for each lane that has due effects and no task running. Doesn't wait.

        A lane that is still busy is left alone: its due effects are picked up once its task
        finishes, which keeps that lane's effects in order.
        """
        started = 0
        groups, self.next_due_at = await db(_due_and_next)
        for group in groups:
            key = effects.lane_of(group[0])
            if key in self._lanes:
                continue
            task = asyncio.create_task(self._run_group(group), name=f"effects:{key}")
            self._lanes[key] = task
            task.add_done_callback(functools.partial(self._lane_done, key))
            started += 1
        return started

    async def run_once(self) -> int:
        """Run everything currently due and wait for it. Returns how many effects were attempted."""
        await self.dispatch()
        if not self._lanes:
            return 0
        counts = await asyncio.gather(*self._lanes.values())
        return sum(counts)

    def _lane_done(self, key: effects.Lane, task: asyncio.Task[int]) -> None:
        if self._lanes.get(key) is task:
            del self._lanes[key]
        if not task.cancelled() and (error := task.exception()) is not None:
            logger.error("Effect lane crashed", extra={"lane": key}, exc_info=error)
        if self.on_lane_done is not None:
            self.on_lane_done()

    async def drain(self, limit: int = 500) -> int:
        """Keep running until nothing is due, for tests and tooling."""
        total = 0
        for _ in range(limit):
            ran = await self.run_once()
            if ran == 0:
                return total
            total += ran
        raise RuntimeError("Outbox didn't drain: an effect is probably re-enqueuing itself.")

    async def _run_group(self, group: list[OutboxEffect]) -> int:
        ran = 0
        for effect in group:
            ran += 1
            if not await self._run_effect(effect):
                break  # Keep this lane's effects in order: later ones wait for the retry.
        return ran

    async def _run_effect(self, effect: OutboxEffect) -> bool:
        # So an error is posted to its own server's error channel, and nobody else's.
        guild = getattr(effect.community, "discord_guild_id", None)
        with log_context.bind(guild=guild, match=effect.match_id, effect=effect.pk):
            try:
                return await self._run_bound(effect)
            finally:
                if self.on_effect_done is not None:
                    self.on_effect_done(effect.kind)

    async def _run_bound(self, effect: OutboxEffect) -> bool:
        handler = HANDLERS.get(effect.kind)
        if handler is None:
            await db(effects.mark_failed, effect.pk, f"No handler for {effect.kind}")
            logger.error("Unknown effect kind", extra={"kind": effect.kind})
            return True
        if not await db(effects.mark_started, effect.pk):
            return True  # Finished or cancelled since it was fetched.
        # How long it was due before it started: the worker's wake-up plus the lane ahead of it.
        # Read defensively: a timing must never be what fails an effect.
        if (due := getattr(effect, "run_after", None)) is not None:
            timings.record("effect.late", max(0.0, (now() - due).total_seconds()))
        env = Env(self.gateway, effect, effect.community, effect.match)
        started = time.perf_counter()
        try:
            try:
                await handler(env)
            finally:
                # The handler alone, however it ends: its Discord calls and its own reads.
                timings.record(f"effect.run:{effect.kind}", time.perf_counter() - started)
        except (Skip, ChannelGone) as exc:
            await db(effects.mark_done, effect.pk, EffectStatus.SKIPPED)
            logger.debug("Effect skipped", extra={"kind": effect.kind, "why": str(exc)})
            return True
        except Later as exc:
            await db(effects.mark_later, effect.pk, exc.seconds, str(exc))
            logger.info(
                "Effect put off",
                extra={"kind": effect.kind, "seconds": exc.seconds, "why": str(exc)},
            )
            return True
        except EditCapped as exc:
            # The panels that must stay current repost themselves; for anything else an old
            # message keeping its last version beats failing the lane, and retrying can't help.
            await db(effects.mark_done, effect.pk, EffectStatus.SKIPPED)
            logger.warning(
                "Edit refused: message too old", extra={"kind": effect.kind, "message": str(exc)}
            )
            return True
        except discord.RateLimited as exc:
            logger.warning(
                "Discord effect deferred by rate limit",
                extra={"kind": effect.kind, "retry_after_seconds": exc.retry_after},
            )
            # A wait longer than the client's max_ratelimit_timeout. Sleeping it out here would
            # stall every later effect in this lane, so step aside and come back after it.
            return await self._retry(
                effect, f"Rate limited for {exc.retry_after:.0f}s", wait_at_least=exc.retry_after
            )
        except discord.HTTPException as exc:
            if exc.status in _PERMANENT_STATUS:
                await self._fail(effect, f"{exc.status} {exc.code}: {exc.text}")
                return True
            return await self._retry(effect, f"{exc.status} {exc.code}: {exc.text}")
        except Exception as exc:
            # A warning: it will be retried. Only failing for good is logged as an error.
            logger.warning(
                "Effect raised", extra={"kind": effect.kind, "effect": effect.pk}, exc_info=True
            )
            return await self._retry(effect, repr(exc))
        await db(effects.mark_done, effect.pk)
        return True

    async def _retry(self, effect: OutboxEffect, error: str, wait_at_least: float = 0) -> bool:
        status = await db(effects.mark_retry, effect.pk, error, wait_at_least)
        if status == EffectStatus.FAILED:
            await self._on_failed(effect, error)
            return True
        logger.warning("Effect will retry", extra={"kind": effect.kind, "error": error})
        return False

    async def _fail(self, effect: OutboxEffect, error: str) -> None:
        await db(effects.mark_failed, effect.pk, error)
        await self._on_failed(effect, error)

    async def _on_failed(self, effect: OutboxEffect, error: str) -> None:
        logger.error(
            "Effect failed for good",
            extra={
                "kind": effect.kind,
                "effect": effect.pk,
                "match": effect.match_id,
                "error": error,
            },
        )
        if effect.kind == "create_lobby" and effect.match_id is not None:
            # With no lobby, nobody can continue: cancel and put everyone back in line.
            await db(lobby.fail_lobby_setup, effect.match_id, "Discord couldn't create the lobby")
        if effect.kind == "render_board" and effect.match_id is not None:
            # A scrim nobody can see would hold its channel: close it so they can start again.
            # A failed move doesn't count: the board is still there, just higher up.
            await db(scrims.close_gone, effect.match_id)
