"""The bot process: runbot, its heartbeat and healthcheck, the deadline loop, the watchdog, and
pointing discord.py at a stand-in."""

from __future__ import annotations

import ast
import asyncio
import logging
import os
import time
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import discord
import httpx
import pytest
import yarl
from django.conf import settings
from django.core.management import call_command
from django.db import connections
from django.utils import timezone

import config.logging
from bot import client as client_module
from bot.client import DraftBot, Heartbeat, Watchdog, deadline_loop, point_at_discord
from bot.db import db
from bot.effects import worker as worker_module
from league.domain.engine import Status
from league.models import Match, OutboxEffect, Player
from league.models.outbox import EffectStatus
from league.services import deadlines, health, lobby

LEAGUE_DIR = Path(__file__).resolve().parent.parent / "league"


@pytest.fixture(autouse=True)
def _clean_process_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config.logging, "_process", {})


@pytest.fixture
def close_db_thread() -> Iterator[None]:
    yield
    # The DB thread holds its own connection, which would block dropping the test DB.
    asyncio.run(db(connections.close_all))


# --- runbot -----------------------------------------------------------------------------------


def test_runbot_runs_the_bot(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(client_module, "run", lambda *a: calls.append(a))
    call_command("runbot")
    assert calls == [()]
    assert config.logging._process == {"service": "bot"}


# --- Healthcheck ----------------------------------------------------------------------------


def test_the_healthcheck_needs_a_fresh_heartbeat(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
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


# --- The loops --------------------------------------------------------------------------------


async def _fake_db(fn: object, *args: object, **kwargs: object) -> list[object]:
    return []


def test_the_bot_runs_every_loop(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(client_module, "db", _fake_db)
    monkeypatch.setattr(worker_module, "db", _fake_db)
    beat = tmp_path / "beat"

    async def scenario() -> set[str]:
        bot = DraftBot(beat)
        await bot.on_ready()
        await asyncio.sleep(0.05)
        names = {task.get_name() for task in bot._tasks}
        for task in bot._tasks:
            task.cancel()
        await asyncio.gather(*bot._tasks, return_exceptions=True)
        return names

    assert asyncio.run(scenario()) == {"deadlines", "effects", "watchdog"}
    assert beat.exists()


def test_league_code_never_imports_discord_or_the_bot() -> None:
    """Everything a click or a deadline runs lives in `league`, which only reads and writes the
    database. Discord work happens later, as outbox effects."""
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


@pytest.mark.django_db(transaction=True)
def test_the_deadline_loop_fires_a_due_deadline(
    popped: Match,
    players: list[Player],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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
    # The effect loop picks these up on its next poll.
    queued = OutboxEffect.objects.exclude(pk__in=effects_before)
    assert queued.filter(status=EffectStatus.PENDING).exists()
    assert beat.exists()


# --- The watchdog -----------------------------------------------------------------------------


@pytest.mark.django_db
def test_health_reports_late_timers_and_a_backlog(popped: Match) -> None:
    at = timezone.now()
    assert health.problems(at) == []
    Match.objects.filter(pk=popped.pk).update(deadline_at=at - timedelta(minutes=2))
    OutboxEffect.objects.filter(status=EffectStatus.PENDING).update(
        run_after=at - timedelta(minutes=7)
    )
    assert health.problems(at) == [
        "1 match timer(s) over a minute late: deadlines aren't firing",
        "Discord updates waiting 7 min: the effect worker isn't keeping up",
    ]


class Pings:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.urls.append(str(request.url))
        return httpx.Response(200)


def test_the_watchdog_logs_changes_and_pings(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    found: list[list[str]] = [[], ["timers late"], ["timers late"], []]

    async def fake_db(fn: object, *args: object, **kwargs: object) -> list[str]:
        return found.pop(0)

    pings = Pings()
    real_client = httpx.AsyncClient

    def client(**kwargs: Any) -> httpx.AsyncClient:
        return real_client(transport=httpx.MockTransport(pings.handler), **kwargs)

    monkeypatch.setattr(client_module, "db", fake_db)
    monkeypatch.setattr(client_module.httpx, "AsyncClient", client)
    watchdog = Watchdog("https://ping.example.com/abc/")

    async def scenario() -> None:
        for _ in range(4):
            await watchdog.check()

    with caplog.at_level(logging.WARNING, logger="bot.client"):
        asyncio.run(scenario())
    assert pings.urls == [
        "https://ping.example.com/abc",
        "https://ping.example.com/abc/fail",
        "https://ping.example.com/abc/fail",
        "https://ping.example.com/abc",
    ]
    # Once when it breaks and once when it recovers, not every minute in between.
    assert [r.getMessage() for r in caplog.records] == [
        "Health check failed: timers late",
        "Health check recovered",
    ]
    assert [r.levelno for r in caplog.records] == [logging.ERROR, logging.WARNING]


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
