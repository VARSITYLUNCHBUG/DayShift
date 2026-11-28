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
from league.models.matches import ResourceKind
from league.models.outbox import EffectStatus
from league.services import common, community, effects, lobby, queue
from league.services.effects import WatchedChannels
from tests.conftest import make_player
from tests.helpers import fresh, to_champion_draft
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
    assert effect.attempts == 0  # A rate limit isn't a failure: no attempt is used.
    assert effect.run_after >= common.now() + timedelta(seconds=85)
    # Its lane still waits for it, so the lane's effects stay in order.
    later = OutboxEffect.objects.create(
        community=wired, kind="render_queue", run_after=common.now(), created_at=common.now()
    )
    assert later.pk not in [row.pk for group in effects.due_by_match() for row in group]


def test_repeated_long_rate_limits_never_fail_the_effect(wired: Community) -> None:
    _render_queue(wired)
    effect = OutboxEffect.objects.get(kind="render_queue")
    for _ in range(effects.MAX_ATTEMPTS + 2):
        OutboxEffect.objects.filter(pk=effect.pk).update(run_after=common.now())
        gateway = FakeGateway(fail_next={"send_view": discord.RateLimited(3600.0)})
        gateway.messages[QUEUE_CHANNEL] = []
        drain(gateway)
    effect.refresh_from_db()
    assert (effect.status, effect.attempts) == (EffectStatus.PENDING, 0)


def _effect(wired: Community, kind: str, **fields: Any) -> OutboxEffect:
    moment = common.now()
    fields.setdefault("run_after", moment)
    return OutboxEffect.objects.create(community=wired, kind=kind, created_at=moment, **fields)


def test_a_held_lane_cannot_crowd_other_lanes_out_of_the_batch(wired: Community) -> None:
    """Effects waiting behind a long wait are left out before the batch limit, so other lanes'
    due work is still fetched however many pile up."""
    match = popped_match(wired, FakeGateway())
    OutboxEffect.objects.all().delete()
    hour = common.now() + timedelta(hours=1)
    _effect(wired, "create_team_voice", match=match, attempts=1, run_after=hour)
    for _ in range(5):
        _effect(wired, "team_move_player", match=match)  # Behind the voice setup.
    _effect(wired, "check_match_api", match=match, started_at=common.now(), run_after=hour)
    _effect(wired, "fetch_api_match_id", match=match)  # Behind deadlock-api's wait.
    _effect(wired, "post_text", lane="stuck", started_at=common.now(), run_after=hour)
    for _ in range(5):
        _effect(wired, "post_text", lane="stuck")  # Behind a rate-limit wait.
    board = _effect(wired, "render_board", match=match)  # The match's own main lane.
    other = _effect(wired, "post_text", lane="free")
    panel = _effect(wired, "render_queue")
    due = effects.due_by_match(limit=3)
    assert sorted(row.pk for group in due for row in group) == [board.pk, other.pk, panel.pk]


def test_a_board_too_large_to_post_fails_at_once(
    wired: Community, monkeypatch: pytest.MonkeyPatch
) -> None:
    from bot.effects import handlers
    from bot.renderers.board import BoardTooLarge

    gateway = FakeGateway()
    match = popped_match(wired, gateway)

    def too_large(state: Any) -> Any:
        raise BoardTooLarge("over 40")

    monkeypatch.setattr(handlers, "render_board", too_large)
    common.render_board(match)
    drain(gateway)
    effect = OutboxEffect.objects.filter(kind="render_board").latest("id")
    assert (effect.status, effect.attempts) == (EffectStatus.FAILED, 0)  # Not retried.


def test_a_failed_lobby_code_status_does_not_ping_everyone_again(wired: Community) -> None:
    gateway = FakeGateway()
    match = popped_match(wired, gateway)
    match.lobby_code = "ABC123"
    match.save(update_fields=["lobby_code"])
    effects.record_resource(match.pk, ResourceKind.TEAM_A_VOICE, 4243)
    common.add_effect(wired, "announce_lobby_code", match=match)
    common.add_effect(wired, "lobby_code_status", match=match)
    gateway.fail_next["set_voice_status"] = _http_error(503, 0)
    drain(gateway)
    status = OutboxEffect.objects.get(kind="lobby_code_status")
    assert (status.status, status.attempts) == (EffectStatus.PENDING, 1)
    OutboxEffect.objects.filter(pk=status.pk).update(run_after=common.now())
    drain(gateway)
    pings = [text for _channel, text, _users in gateway.texts if "Lobby code" in text]
    assert len(pings) == 1
    assert "ABC123" in gateway.statuses[4243]


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
    monkeypatch.setattr(common, "BURST_BOARD_DELAY_SECONDS", 1.0)
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
    # setup_hook binds the process-wide error handler to this test's loop. Left bound, later
    # tests in the same worker see an error queue and start an extra loop.
    monkeypatch.setattr(client_module.discord_error_handler, "bind", lambda _loop: None)

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


# --- Fewer requests for the same board -----------------------------------------------------


def _grid_ids(match_id: int) -> list[int | None]:
    from bot.effects.handlers import GRID_KINDS

    return [effects.resource_id(match_id, kind) for kind in GRID_KINDS]


def test_a_champion_draft_step_edits_the_grid_in_place(wired: Community) -> None:
    from league.domain.draft_plan import build_plan, team_for_role
    from league.services import draft

    gateway = FakeGateway()
    match = to_champion_draft(popped_match(wired, gateway))
    drain(gateway)
    common.clear_notices(match)  # The pings of the steps above, which a real match spaces out.
    common.render_board(match)
    drain(gateway)
    board = effects.resource_id(match.pk, ResourceKind.BOARD_MESSAGE)
    grid = _grid_ids(match.pk)
    assert board is not None and any(grid)
    posted = len(gateway.views)
    step = build_plan(match.mode)[match.step_index]
    captain = match.captain_of(team_for_role(step.role, match.champion_first_pick)).player
    draft.choose_champion(match.pk, captain, match.step_index, draft.available_champions(match)[0])
    drain(gateway)
    assert len(gateway.views) == posted  # Nothing posted afresh, nothing deleted.
    assert effects.resource_id(match.pk, ResourceKind.BOARD_MESSAGE) == board
    assert _grid_ids(match.pk) == grid
    assert {board, *[g for g in grid if g]} <= gateway.edited


def test_a_notice_below_the_board_leaves_it_where_it_is(wired: Community) -> None:
    gateway = FakeGateway()
    match = popped_match(wired, gateway)
    drain(gateway)
    board = effects.resource_id(match.pk, ResourceKind.BOARD_MESSAGE)
    channel = effects.resource_id(match.pk, ResourceKind.TEXT)
    common.add_effect(wired, "ping_lobby", {"text": "hello"}, match=match)
    drain(gateway)
    common.render_board(fresh(match), at_once=True)
    drain(gateway)
    # The notice is last and the board above it was edited in place, not posted again.
    assert effects.resource_id(match.pk, ResourceKind.BOARD_MESSAGE) == board
    assert gateway.messages[channel][-1] in effects.live_notices(match.pk)
    # Chat on top of it counts towards a move as before.
    for _ in range(effects.BOARD_MOVE_AFTER_MESSAGES):
        effects.note_chat(channel)
    assert not effects.notices_below_board(match.pk, board)


def test_bursty_phases_fold_board_renders_and_the_first_board_goes_up_at_once(
    wired: Community, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(common, "BURST_BOARD_DELAY_SECONDS", 1.0)
    gateway = FakeGateway()
    for player in [make_player(n) for n in range(1, 13)]:
        queue.join(wired.pk, player)
    match = OutboxEffect.objects.get(kind="create_lobby").match
    first = OutboxEffect.objects.get(kind="render_board", match=match)
    assert first.run_after <= common.now()  # Ahead of the twelve DMs, not behind them.
    drain(gateway)
    for status in (Status.CAPTAIN_PHASE, Status.CAPTAIN_CHECKIN, Status.TEAM_CONFIRM):
        match.status = status
        common.render_board(match)
        render = OutboxEffect.objects.filter(
            kind="render_board", match=match, status=EffectStatus.PENDING
        ).get()
        assert render.run_after > common.now()
        render.delete()
    match.status = Status.CHAMPION_DRAFT
    common.render_board(match)
    assert (
        OutboxEffect.objects.get(
            kind="render_board", match=match, status=EffectStatus.PENDING
        ).run_after
        <= common.now()
    )


def test_ready_from_the_dm_edits_that_dm_once(wired: Community) -> None:
    gateway = FakeGateway()
    match = popped_match(wired, gateway)
    participant = match.participants.select_related("player").first()
    participant.ready_dm_message_id = 777
    participant.save(update_fields=["ready_dm_message_id"])
    lobby.mark_ready(match.pk, participant.player, from_dm=True)
    assert not OutboxEffect.objects.filter(kind="ready_dm_done").exists()
    other = match.participants.select_related("player").exclude(pk=participant.pk).first()
    other.ready_dm_message_id = 778
    other.save(update_fields=["ready_dm_message_id"])
    lobby.mark_ready(match.pk, other.player)  # On the board: the DM still needs its edit.
    assert OutboxEffect.objects.filter(kind="ready_dm_done").count() == 1


def test_match_channels_are_made_with_the_servers_slowmode(wired: Community) -> None:
    from league.services import runtime

    gateway = FakeGateway()
    match = popped_match(wired, gateway)
    text_id = effects.resource_id(match.pk, ResourceKind.TEXT)
    assert gateway.slowmodes[text_id] == 3  # The default, in the create call itself.
    runtime.update(wired, match_chat_slowmode_seconds=0)
    assert runtime.of(wired).match_chat_slowmode_seconds == 0
