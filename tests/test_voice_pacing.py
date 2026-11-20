"""Voice delays must stay off the board lane, and obsolete setup must yield to cleanup."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterator
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from django.db import connections

from bot.db import db
from bot.voice_pacing import VoicePacer
from league.models import Community, OutboxEffect
from league.models.matches import ResourceKind
from league.models.outbox import EffectStatus
from league.services import common, community, effects, lobby, voice_pool
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


def test_concurrent_calls_get_spaced_slots_and_a_slow_one_holds_nobody_up() -> None:
    """Starts are spaced in the order asked, but a call stuck in Discord (a rate-limit wait,
    say) doesn't stop the next one starting in its own slot."""
    stamp = [0.0]
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)
        stamp[0] += seconds
        await asyncio.sleep(0)

    async def scenario() -> None:
        pacer = VoicePacer(
            create_interval=5, action_interval=1, clock=lambda: stamp[0], sleep=sleep
        )
        release = asyncio.Event()
        starts: list[str] = []

        async def stuck() -> None:
            starts.append("stuck")
            await release.wait()

        def quick(name: str) -> Callable[[], Awaitable[None]]:
            async def call() -> None:
                starts.append(name)

            return call

        first = asyncio.create_task(pacer.run(1, stuck, create=True))
        await asyncio.sleep(0)
        await asyncio.gather(pacer.run(1, quick("second")), pacer.run(1, quick("third")))
        assert not first.done()  # Still stuck, and the others ran anyway.
        assert starts == ["stuck", "second", "third"]
        assert waits == [5, 1]  # Second waits out the creation's 5 s; third 1 s after it.
        release.set()
        await first

    asyncio.run(scenario())


def test_main_lane_voice_calls_skip_the_pacer(wired: Community) -> None:
    """The lobby code's voice status runs in the match's main lane, so it never waits behind
    another match's paced voice setup."""
    from bot.effects.handlers import Env, announce_lobby_code

    match = popped_match(wired, FakeGateway())
    match.lobby_code = "ABC123"
    match.save(update_fields=["lobby_code"])
    effects.record_resource(match.pk, ResourceKind.TEXT, 4242)
    effects.record_resource(match.pk, ResourceKind.TEAM_A_VOICE, 4243)
    common.add_effect(wired, "announce_lobby_code", match=match)
    effect = OutboxEffect.objects.get(match=match, kind="announce_lobby_code")
    gateway = FakeGateway()
    asyncio.run(announce_lobby_code(Env(gateway, effect, wired, match)))
    assert ("set_voice_status", 4243) in gateway.unpaced


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
    assert not voice_pool.record_created(match.pk, ResourceKind.TEAM_A_VOICE, 12345, 1, False)
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
