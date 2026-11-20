"""Voice delays must stay off the board lane, and obsolete setup must yield to cleanup."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from django.db import connections

from bot.db import db
from bot.effects.handlers import _record_created_voice
from bot.voice_pacing import VoicePacer
from league.models import Community, OutboxEffect
from league.models.matches import ResourceKind
from league.models.outbox import EffectStatus
from league.services import common, community, effects, lobby
from tests.test_bot import FakeGateway, popped_match


def test_voice_operations_are_spaced_per_guild_and_errors_also_consume_a_slot() -> None:
    stamp = [0.0]
    waits = []
    starts = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)
        stamp[0] += seconds

    async def call() -> None:
        starts.append(stamp[0])

    async def fail() -> None:
        raise RuntimeError("failed request")

    async def scenario() -> None:
        pacer = VoicePacer(clock=lambda: stamp[0], sleep=sleep)
        await pacer.run(1, call, create=True)
        await pacer.run(2, call)  # A different server does not wait for server 1.
        await pacer.run(1, call)
        with pytest.raises(RuntimeError):
            await pacer.run(1, fail)
        await pacer.run(1, call)

    asyncio.run(scenario())
    assert starts == [0, 0, 5, 7]
    assert waits == [5, 1, 1]


def test_concurrent_voice_calls_in_one_guild_are_serialized() -> None:
    async def scenario() -> None:
        pacer = VoicePacer(create_interval=0, action_interval=0)
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []

        async def slow() -> None:
            entered.set()
            await release.wait()
            calls.append("first")

        async def second() -> None:
            calls.append("second")

        first = asyncio.create_task(pacer.run(1, slow))
        await entered.wait()
        other = asyncio.create_task(pacer.run(1, second))
        await asyncio.sleep(0)
        assert not other.done()
        release.set()
        await asyncio.gather(first, other)
        assert calls == ["first", "second"]

    asyncio.run(scenario())


@pytest.fixture
def wired(transactional_db: None) -> Iterator[Community]:
    row = community.ensure(guild_id=999, name="Test")
    yield row
    asyncio.run(db(connections.close_all))


def test_a_voice_retry_cannot_block_a_board_and_cleanup_cancels_it(wired: Community) -> None:
    match = popped_match(wired, FakeGateway())
    common.add_effect(wired, "create_team_voice", match=match)
    voice = OutboxEffect.objects.get(match=match, kind="create_team_voice")
    voice.attempts = 1
    voice.run_after = common.now() + timedelta(hours=24)
    voice.save(update_fields=["attempts", "run_after"])
    common.render_board(match)
    due = [effect.kind for group in effects.due_by_match() for effect in group]
    assert "render_board" in due
    assert "create_team_voice" not in due
    assert effects.lane_of(voice) == f"voice:{match.pk}"
    common.add_effect(wired, "team_move_player", match=match)
    lobby.schedule_cleanup(match)
    voice.refresh_from_db()
    assert voice.status == EffectStatus.SKIPPED
    assert (
        OutboxEffect.objects.get(match=match, kind="team_move_player").status
        == EffectStatus.SKIPPED
    )
    due = [effect.kind for group in effects.due_by_match() for effect in group]
    assert "cleanup_voice" in due


def test_a_channel_created_as_the_match_ends_is_recorded_for_cleanup(wired: Community) -> None:
    match = popped_match(wired, FakeGateway())
    match.participants.update(is_active=False)
    assert not _record_created_voice(match.pk, ResourceKind.TEAM_A_VOICE, 12345)
    assert effects.resource_id(match.pk, ResourceKind.TEAM_A_VOICE) == 12345
    assert OutboxEffect.objects.filter(match=match, kind="cleanup_voice").exists()


def test_a_voice_setup_retry_after_the_players_leave_makes_no_discord_calls(
    wired: Community,
) -> None:
    from bot.effects.handlers import Env, Skip, create_team_voice

    match = popped_match(wired, FakeGateway())
    match.participants.update(is_active=False)
    common.add_effect(wired, "create_team_voice", match=match)
    effect = OutboxEffect.objects.get(match=match, kind="create_team_voice")
    gateway = FakeGateway()
    gateway.create_voice_channel = AsyncMock()
    with pytest.raises(Skip):
        asyncio.run(create_team_voice(Env(gateway, effect, wired, match)))
    gateway.create_voice_channel.assert_not_awaited()
