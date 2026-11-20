"""Staying inside Discord's limits: rate-limit waits, the old-message edit cap, chat and voice
events kept off the database thread, quieter ready checks, renders that change nothing, one
invite per channel, no screenshot downloads to refresh a post, command syncs only on change,
and a count of the requests Discord holds against us."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from datetime import timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from django.db import connections

from bot import client as client_module
from bot import request_health
from bot.client import DayShiftBot, command_fingerprint
from bot.db import db
from bot.effects.gateway import DiscordGateway, EditCapped
from bot.watched import ChannelWatch
from league.domain.engine import Status
from league.models import Community, OutboxEffect
from league.models.outbox import EffectStatus
from league.services import common, community, effects, lobby, queue
from league.services.effects import WatchedChannels
from tests.conftest import make_player
from tests.helpers import fresh
from tests.test_bot import (
    ARCHIVE_CHANNEL,
    QUEUE_CHANNEL,
    RESULTS_CHANNEL,
    WAITING_ROOM,
    FakeGateway,
    _http_error,
    drain,
    popped_match,
)


@pytest.fixture
def wired(transactional_db: None) -> Iterator[Community]:
    """A server wired as test_bot's is."""
    row = community.ensure(guild_id=999, name="Test")
    community.save_wiring(
        row.pk,
        waiting_room_channel_id=WAITING_ROOM,
        queue_channel_id=QUEUE_CHANNEL,
        results_channel_id=RESULTS_CHANNEL,
        archive_channel_id=ARCHIVE_CHANNEL,
    )
    row.refresh_from_db()
    yield row
    # The worker's DB thread holds its own connection, which would block dropping the test DB.
    asyncio.run(db(connections.close_all))


def _render_queue(wired: Community) -> None:
    common.render_queue(Community.objects.get(pk=wired.pk))


# --- 1. Long rate limits retry later instead of stalling the lane ---------------------------


def test_a_long_rate_limit_retries_the_effect_after_the_wait(wired: Community) -> None:
    gateway = FakeGateway(fail_next={"send_view": discord.RateLimited(90.0)})
    gateway.messages[QUEUE_CHANNEL] = []
    _render_queue(wired)
    drain(gateway)
    effect = OutboxEffect.objects.get(kind="render_queue")
    assert effect.status == EffectStatus.PENDING  # Not failed: it comes back.
    assert effect.attempts == 1
    assert effect.run_after >= common.now() + timedelta(seconds=85)


def test_the_client_caps_how_long_discord_py_sleeps_on_a_429() -> None:
    bot = DayShiftBot()
    assert bot.http.max_ratelimit_timeout == client_module.RATE_LIMIT_WAIT_SECONDS


# --- 2. The edit cap on old messages ---------------------------------------------------------


def test_the_gateway_turns_discords_edit_cap_into_edit_capped() -> None:
    message = MagicMock()
    message.edit = AsyncMock(side_effect=_http_error(400, 30046))
    channel = MagicMock()
    channel.get_partial_message.return_value = message
    gateway = DiscordGateway(MagicMock(get_channel=MagicMock(return_value=channel)))
    with pytest.raises(EditCapped):
        asyncio.run(gateway.edit_view(1, 2, MagicMock()))


def test_a_queue_panel_too_old_to_edit_is_posted_again(wired: Community) -> None:
    gateway = FakeGateway()
    gateway.messages[QUEUE_CHANNEL] = []
    _render_queue(wired)
    drain(gateway)
    old = Community.objects.get(pk=wired.pk).queue_message_id
    assert old is not None

    async def capped(*_args: Any, **_kwargs: Any) -> None:
        raise EditCapped(str(old))

    gateway.edit_view = capped  # type: ignore[method-assign]
    queue.join(wired.pk, make_player(1))  # Something to show, so the render isn't skipped.
    drain(gateway)
    new = Community.objects.get(pk=wired.pk).queue_message_id
    assert new is not None and new != old
    assert gateway.messages[QUEUE_CHANNEL] == [new]  # The old one is gone, not left behind.


# --- 3. Chat and voice outside the bot's channels never reach the database ------------------


def _bot(watch: ChannelWatch) -> Any:
    return SimpleNamespace(
        user=SimpleNamespace(id=1),
        watch=watch,
        gateway=SimpleNamespace(note_last_message=lambda *_: None),
        _auto_move=AsyncMock(),
    )


def _watching(text: set[int], voice: set[int]) -> ChannelWatch:
    watch = ChannelWatch()
    watch.set(WatchedChannels(frozenset(text), frozenset(voice)))
    return watch


def test_chat_elsewhere_makes_no_database_call(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []

    async def fake_db(fn: object, *args: object) -> None:
        calls.append(args)

    monkeypatch.setattr(client_module, "db", fake_db)
    bot = _bot(_watching({7}, set()))

    def message(channel: int) -> Any:
        return SimpleNamespace(
            id=50,
            guild=SimpleNamespace(id=9),
            author=SimpleNamespace(id=2),
            channel=SimpleNamespace(id=channel),
        )

    asyncio.run(DayShiftBot.on_message(bot, message(8)))
    assert calls == []
    asyncio.run(DayShiftBot.on_message(bot, message(7)))
    assert calls == [(7,)]


def test_voice_elsewhere_is_ignored_but_the_waiting_room_still_moves_people() -> None:
    bot = _bot(_watching(set(), {WAITING_ROOM}))
    member = SimpleNamespace(id=3, guild=SimpleNamespace(id=9))
    nowhere = SimpleNamespace(channel=None)
    elsewhere = SimpleNamespace(channel=SimpleNamespace(id=12345))
    waiting = SimpleNamespace(channel=SimpleNamespace(id=WAITING_ROOM))
    asyncio.run(DayShiftBot.on_voice_state_update(bot, member, nowhere, elsewhere))
    bot._auto_move.assert_not_called()
    asyncio.run(DayShiftBot.on_voice_state_update(bot, member, nowhere, waiting))
    bot._auto_move.assert_awaited_once()


def test_the_watch_list_holds_live_match_channels_and_the_waiting_room(wired: Community) -> None:
    from league.models.matches import ResourceKind

    gateway = FakeGateway()
    match = popped_match(wired, gateway)
    watched = effects.watched_channels()
    text_id = effects.resource_id(match.pk, ResourceKind.TEXT)
    assert text_id in watched.text
    assert WAITING_ROOM in watched.voice
    assert QUEUE_CHANNEL not in watched.text


def test_effects_that_change_channels_reload_the_watch_list() -> None:
    watch = ChannelWatch()
    watch.request_refresh("render_queue")
    assert not watch._dirty.is_set()
    watch.request_refresh("create_lobby")
    assert watch._dirty.is_set()


# --- 4. A quieter ready check ----------------------------------------------------------------


def test_ready_presses_wait_a_moment_so_the_board_edits_once(
    wired: Community, monkeypatch: pytest.MonkeyPatch
) -> None:
    gateway = FakeGateway()
    match = popped_match(wired, gateway)
    monkeypatch.setattr(common, "READY_BOARD_DELAY_SECONDS", 1.0)
    players = [p.player for p in match.participants.select_related("player")][:4]
    for player in players:
        lobby.mark_ready(match.pk, player)
    renders = OutboxEffect.objects.filter(
        kind="render_board", match=match, status=EffectStatus.PENDING
    )
    assert renders.count() == 1  # Four presses, one board edit.
    assert renders.get().run_after > common.now()
    assert not OutboxEffect.objects.filter(
        kind=effects.READY_PING_KIND, status=EffectStatus.PENDING
    ).exists()  # And no ping edits at all.


# --- 6. Renders that would change nothing are skipped --------------------------------------


def test_a_board_render_that_changes_nothing_is_skipped(wired: Community) -> None:
    gateway = FakeGateway()
    match = popped_match(wired, gateway)
    drain(gateway)
    edits: list[int] = []
    real_edit = gateway.edit_view

    async def counted(channel_id: int, message_id: int, view: Any, **kwargs: Any) -> None:
        edits.append(message_id)
        await real_edit(channel_id, message_id, view, **kwargs)

    gateway.edit_view = counted  # type: ignore[method-assign]
    sent = len(gateway.views)
    common.render_board(fresh(match))
    drain(gateway)
    assert len(gateway.views) == sent and edits == []

    # A restart forgets what was shown, so the startup reconcile still draws it once.
    from bot.effects import flow

    flow.forget_shown()
    common.render_board(fresh(match))
    drain(gateway)
    assert len(edits) == 1


def test_a_queue_render_that_changes_nothing_is_skipped(wired: Community) -> None:
    gateway = FakeGateway()
    gateway.messages[QUEUE_CHANNEL] = []
    _render_queue(wired)
    drain(gateway)
    _render_queue(wired)
    drain(gateway)
    assert gateway.edited == set()


# --- 7. One invite per channel ---------------------------------------------------------------


def test_twelve_gathers_create_one_invite() -> None:
    voice = MagicMock(spec=discord.VoiceChannel)
    voice.create_invite = AsyncMock(return_value=SimpleNamespace(url="https://discord.gg/x"))
    guild = MagicMock()
    guild.get_channel.return_value = voice
    gateway = DiscordGateway(MagicMock(get_guild=MagicMock(return_value=guild)))

    async def gather() -> list[str | None]:
        return [await gateway.create_invite(1, WAITING_ROOM, 1800) for _ in range(12)]

    assert set(asyncio.run(gather())) == {"https://discord.gg/x"}
    voice.create_invite.assert_awaited_once()


# --- 8. Refreshing a results post downloads nothing ----------------------------------------


def test_refreshing_the_results_post_fetches_no_screenshot(wired: Community) -> None:
    from tests.helpers import finish, to_in_progress

    gateway = FakeGateway()
    gateway.messages[RESULTS_CHANNEL] = []
    match = finish(to_in_progress(popped_match(wired, gateway)))
    fetches: list[int] = []
    real_fetch = gateway.fetch_attachment

    async def counted(*args: Any) -> Any:
        fetches.append(1)
        return await real_fetch(*args)

    gateway.fetch_attachment = counted  # type: ignore[method-assign]
    drain(gateway)
    posted = len(fetches)
    assert posted >= 1  # The post itself uploads the screenshot.
    common.add_effect(match.community, "refresh_results", match=match)
    drain(gateway)
    assert len(fetches) == posted
    assert fresh(match).status == Status.COMPLETED


# --- 9. Slash commands sync only when they change ------------------------------------------


def test_command_sync_is_skipped_when_nothing_changed(
    wired: Community, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    from django.conf import settings

    monkeypatch.setattr(settings, "DISCORD_GUILD_ID", wired.discord_guild_id)

    async def boot() -> AsyncMock:
        bot = DayShiftBot(tmp_path / "beat")
        sync = AsyncMock()
        monkeypatch.setattr(bot.tree, "sync", sync)
        await bot.setup_hook()
        return sync

    assert asyncio.run(boot()).await_count == 1
    assert Community.objects.get(pk=wired.pk).commands_fingerprint
    assert asyncio.run(boot()).await_count == 0  # The same commands: no sync.

    community.record_commands_synced(wired.discord_guild_id, "something older")
    assert asyncio.run(boot()).await_count == 1


def test_the_command_fingerprint_follows_the_commands(tmp_path: Any) -> None:
    from discord import app_commands

    bot = DayShiftBot(tmp_path / "beat")
    before = command_fingerprint(bot.tree, None)
    assert before == command_fingerprint(bot.tree, None)

    @app_commands.command(name="zz_extra", description="A new one")
    async def extra(interaction: discord.Interaction[Any]) -> None:  # pragma: no cover
        return None

    bot.tree.add_command(extra)
    assert command_fingerprint(bot.tree, None) != before


# --- 11. Failed requests are counted ---------------------------------------------------------


def test_failed_requests_count_as_discord_counts_them(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    now = [0.0]
    counter = request_health.FailedRequests(clock=lambda: now[0])
    for status, scope in ((401, None), (403, None), (429, "user"), (429, "shared"), (200, None)):
        counter.record(status, scope)
    assert counter.count() == 3  # A shared 429 and a success don't count.
    now[0] = request_health.WINDOW_SECONDS + 1
    assert counter.count() == 0

    monkeypatch.setattr(request_health, "WARN_AT", 5)
    with caplog.at_level(logging.ERROR, logger="bot.request_health"):
        for _ in range(7):
            counter.record(403)
    assert len([r for r in caplog.records if r.levelno == logging.ERROR]) == 1  # Once a window.
