"""`runbot --role`: the gateway and the scheduler split one bot into two processes, and the
scheduler fires deadlines with no Discord connection at all."""

from __future__ import annotations

import ast
import asyncio
import os
import signal
import sys
import time
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import discord
import pytest
import yarl
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connections
from django.utils import timezone

import config.logging
from bot import client as client_module
from bot.client import DraftBot, Heartbeat, deadline_loop, point_at_discord, schedule
from bot.db import db
from bot.effects import worker as worker_module
from league.domain.engine import Status
from league.management.commands import runbot
from league.models import Match, OutboxEffect, Player
from league.models.outbox import EffectStatus
from league.services import deadlines, lobby

LEAGUE_DIR = Path(__file__).resolve().parent.parent / "league"


@pytest.fixture(autouse=True)
def _clean_process_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config.logging, "_process", {})
    monkeypatch.delenv("BOT_ROLE", raising=False)


@pytest.fixture
def close_db_thread() -> Iterator[None]:
    yield
    # The DB thread holds its own connection, which would block dropping the test DB.
    asyncio.run(db(connections.close_all))


# --- Choosing a role ------------------------------------------------------------------------


def test_the_role_comes_from_the_option_then_bot_role_then_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert runbot.resolve_role(None) == "all"
    monkeypatch.setenv("BOT_ROLE", "scheduler")
    assert runbot.resolve_role(None) == "scheduler"
    assert runbot.resolve_role("gateway") == "gateway"
    monkeypatch.setenv("BOT_ROLE", "everything")
    with pytest.raises(CommandError, match="BOT_ROLE must be one of"):
        runbot.resolve_role(None)


def test_runbot_starts_the_part_its_role_names(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, Any]] = []
    monkeypatch.setattr(client_module, "run", lambda *a: calls.append(("run", a)))
    monkeypatch.setattr(client_module, "run_scheduler", lambda *a: calls.append(("sched", a)))

    call_command("runbot")
    call_command("runbot", role="scheduler")
    monkeypatch.setenv("BOT_ROLE", "gateway")
    call_command("runbot")

    assert calls == [
        ("run", ("all",)),
        ("sched", ()),
        ("run", ("gateway",)),
    ]
    assert config.logging._process == {"service": "bot", "role": "gateway"}


def test_runbot_refuses_an_unknown_role() -> None:
    with pytest.raises(CommandError):
        call_command("runbot", "--role", "everything")


# --- Healthcheck ----------------------------------------------------------------------------


def test_the_healthcheck_needs_a_fresh_heartbeat(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Every role writes the same file, so a service's healthcheck needs no role of its own."""
    beat = tmp_path / "beat"
    monkeypatch.setattr(settings, "BOT_HEARTBEAT_FILE", beat)
    with pytest.raises(SystemExit):
        call_command("bot_healthcheck")  # Never written.
    beat.touch()
    call_command("bot_healthcheck")
    stale = time.time() - 120
    os.utime(beat, (stale, stale))
    with pytest.raises(SystemExit):
        call_command("bot_healthcheck")


def test_the_heartbeat_waits_for_every_loop(tmp_path: Path) -> None:
    path = tmp_path / "beat"
    heartbeat = Heartbeat(path, ("deadlines", "effects"))
    heartbeat.beat("effects")
    heartbeat.beat("effects")
    assert not path.exists()  # The deadline loop hasn't gone round.
    heartbeat.beat("deadlines")
    assert path.exists()


# --- The gateway role -----------------------------------------------------------------------


async def _fake_db(fn: object, *args: object, **kwargs: object) -> list[object]:
    return []


@pytest.mark.parametrize(
    ("role", "tasks"), [("all", {"deadlines", "effects"}), ("gateway", {"effects"})]
)
def test_only_the_all_role_runs_the_deadline_loop_in_the_bot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, role: runbot.Role, tasks: set[str]
) -> None:
    monkeypatch.setattr(client_module, "db", _fake_db)
    monkeypatch.setattr(worker_module, "db", _fake_db)
    beat = tmp_path / "beat"

    async def scenario() -> set[str]:
        bot = DraftBot(role, beat)
        await bot.on_ready()
        await asyncio.sleep(0.05)
        names = {task.get_name() for task in bot._tasks}
        for task in bot._tasks:
            task.cancel()
        await asyncio.gather(*bot._tasks, return_exceptions=True)
        return names

    assert asyncio.run(scenario()) == tasks
    assert beat.exists()  # Without a deadline loop, the effect loop keeps the heartbeat going.


# --- The scheduler role ---------------------------------------------------------------------


def test_league_code_never_imports_discord_or_the_bot() -> None:
    """What makes the scheduler safe: everything a deadline runs lives in `league`, which only
    reads and writes the database. Discord work happens later, as outbox effects."""
    allowed = {LEAGUE_DIR / "management" / "commands" / "runbot.py"}
    offenders = []
    for path in LEAGUE_DIR.rglob("*.py"):
        if path in allowed:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            offenders += [
                f"{path.relative_to(LEAGUE_DIR)}: {name}"
                for name in names
                if name.split(".")[0] in {"discord", "bot"}
            ]
    assert offenders == []


@pytest.fixture
def no_discord_client(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("The scheduler must not make a Discord client")

    monkeypatch.setattr(discord.Client, "__init__", refuse)


@pytest.mark.django_db(transaction=True)
def test_the_scheduler_fires_a_due_deadline_with_no_discord_client(
    popped: Match,
    players: list[Player],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    no_discord_client: None,
    close_db_thread: None,
) -> None:
    for player in players[:11]:
        lobby.mark_ready(popped.pk, player)
    Match.objects.filter(pk=popped.pk).update(deadline_at=timezone.now() - timedelta(seconds=1))
    effects_before = set(OutboxEffect.objects.values_list("pk", flat=True))
    stop = asyncio.Event()
    fired: list[int] = []
    real_tick = deadlines.tick

    def tick_once() -> int:
        fired.append(real_tick())
        stop.set()
        return fired[-1]

    monkeypatch.setattr(deadlines, "tick", tick_once)
    beat = tmp_path / "beat"
    asyncio.run(asyncio.wait_for(deadline_loop(Heartbeat(beat, ("deadlines",)), stop=stop), 10))

    assert fired == [1]
    match = Match.objects.get(pk=popped.pk)
    assert match.status == Status.READY_CHECK and match.held_seconds is not None
    assert not match.participants.filter(player=players[11], is_active=True).exists()
    # The gateway's effect loop picks these up on its next poll.
    queued = OutboxEffect.objects.exclude(pk__in=effects_before)
    assert queued.filter(status=EffectStatus.PENDING).exists()
    assert beat.exists()


@pytest.mark.django_db(transaction=True)
def test_the_scheduler_applies_the_startup_grace_first(
    popped: Match, tmp_path: Path, no_discord_client: None, close_db_thread: None
) -> None:
    Match.objects.filter(pk=popped.pk).update(deadline_at=timezone.now() - timedelta(seconds=30))
    stop = asyncio.Event()
    stop.set()
    asyncio.run(schedule(Heartbeat(tmp_path / "beat", ("deadlines",)), stop))
    match = Match.objects.get(pk=popped.pk)
    assert match.deadline_at is not None and match.deadline_at > timezone.now()
    assert match.status == Status.READY_CHECK


@pytest.mark.skipif(sys.platform == "win32", reason="Windows event loops have no signal handlers")
def test_sigterm_stops_the_scheduler_after_its_current_pass(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(client_module, "db", _fake_tick_db)

    async def scenario() -> None:
        task = asyncio.create_task(schedule(Heartbeat(tmp_path / "beat", ("deadlines",))))
        await asyncio.sleep(0.1)
        signal.raise_signal(signal.SIGTERM)
        await asyncio.wait_for(task, 5)

    asyncio.run(scenario())
    assert (tmp_path / "beat").exists()


async def _fake_tick_db(fn: object, *args: object, **kwargs: object) -> int:
    return 0


# --- Pointing at a Discord stand-in ---------------------------------------------------------


@pytest.fixture
def library_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    """Put discord.py's globals back afterwards, whatever the test does to them."""
    monkeypatch.setattr(discord.http.Route, "BASE", discord.http.Route.BASE)
    monkeypatch.setattr(
        discord.gateway.DiscordWebSocket,
        "DEFAULT_GATEWAY",
        discord.gateway.DiscordWebSocket.DEFAULT_GATEWAY,
    )


def test_discord_endpoints_are_left_alone_by_default(
    library_endpoints: None, caplog: pytest.LogCaptureFixture
) -> None:
    point_at_discord()
    assert discord.http.Route.BASE == "https://discord.com/api/v10"
    gateway = discord.gateway.DiscordWebSocket.DEFAULT_GATEWAY
    assert gateway == yarl.URL("wss://gateway.discord.gg/")
    assert "stand-in" not in caplog.text


def test_settings_point_discord_py_at_a_stand_in(
    library_endpoints: None, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(settings, "DEBUG", True)
    monkeypatch.setattr(settings, "DISCORD_API_BASE", "http://discord-sim:8090/api/v10")
    monkeypatch.setattr(settings, "DISCORD_GATEWAY_URL", "ws://discord-sim:8090/gateway")
    point_at_discord()
    assert discord.http.Route.BASE == "http://discord-sim:8090/api/v10"
    route = discord.http.Route("GET", "/users/@me")
    assert route.url == "http://discord-sim:8090/api/v10/users/@me"
    gateway = discord.gateway.DiscordWebSocket.DEFAULT_GATEWAY
    assert gateway == yarl.URL("ws://discord-sim:8090/gateway")
    assert "Not talking to Discord" in caplog.text


def test_a_stand_in_needs_debug_on(
    library_endpoints: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The stand-in would get the bot token, so production refuses to start rather than send it."""
    monkeypatch.setattr(settings, "DEBUG", False)
    monkeypatch.setattr(settings, "DISCORD_API_BASE", "http://discord-sim:8090/api/v10")
    with pytest.raises(SystemExit, match="only works with DEBUG on"):
        point_at_discord()
    assert discord.http.Route.BASE == "https://discord.com/api/v10"


def test_empty_endpoint_settings_mean_discord(
    library_endpoints: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "DEBUG", False)
    monkeypatch.setattr(settings, "DISCORD_API_BASE", "")
    monkeypatch.setattr(settings, "DISCORD_GATEWAY_URL", "")
    point_at_discord()
    assert discord.http.Route.BASE == "https://discord.com/api/v10"
