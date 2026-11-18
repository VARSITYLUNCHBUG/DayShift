"""The simulator's deadlock-api stand-in serves what the app reads: the admin's champion sync
(`/v1/assets/heroes`) and /link's Steam names (`/v1/players/steam`), over real HTTP, with the
repo's seed roster (presets/champions.yaml)."""

from __future__ import annotations

import asyncio
import sys
import threading
from collections.abc import Iterator
from io import StringIO
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from django.conf import settings
from django.core.management import call_command

from league.integrations import deadlock_api
from league.services import champions

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "discord-sim" / "src"))

from aiohttp import web  # noqa: E402
from discord_sim.app import create_app  # noqa: E402
from discord_sim.heroes import HEROES  # noqa: E402


@pytest.fixture(scope="module")
def sim_url() -> Iterator[str]:
    """The simulator, running on a free local port in a thread of its own."""
    loop = asyncio.new_event_loop()
    runner = web.AppRunner(create_app())
    started = threading.Event()
    url: list[str] = []

    async def start() -> None:
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        server: Any = site._server
        url.append(f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}")
        started.set()

    thread = threading.Thread(target=lambda: (loop.run_until_complete(start()), loop.run_forever()))
    thread.start()
    assert started.wait(10), "The simulator didn't start."
    yield url[0]
    asyncio.run_coroutine_threadsafe(runner.cleanup(), loop).result(10)
    loop.call_soon_threadsafe(loop.stop)
    thread.join(10)


@pytest.fixture
def standin(sim_url: str, settings: Any) -> Iterator[str]:
    settings.DEADLOCK_API_BASE = f"{sim_url}/deadlock-api"
    yield sim_url
    httpx.post(f"{sim_url}/_sim/reset").raise_for_status()


def test_the_stand_in_roster_is_the_seed_roster() -> None:
    seed = yaml.safe_load((ROOT / "presets" / "champions.yaml").read_text(encoding="utf-8"))
    assert list(HEROES) == [(entry["id"], entry["name"]) for entry in seed["champions"]]


@pytest.mark.django_db
def test_the_champion_sync_finds_nothing_to_change_on_a_dev_stack(standin: str) -> None:
    call_command("load_presets", stdout=StringIO())
    assert settings.DEADLOCK_API_BASE.startswith("http://127.0.0.1:")
    remote = champions.fetch_remote()
    assert len(remote) == len(HEROES)
    assert champions.diff(remote).is_empty


@pytest.mark.django_db
def test_the_champion_sync_sees_a_roster_change_made_in_the_simulator(standin: str) -> None:
    call_command("load_presets", stdout=StringIO())
    # Seven renamed, Vindicta gone, Lady Geist no longer pickable, and a new hero.
    heroes: list[dict[str, Any]] = [
        {"id": pk, "name": "Seven Again" if pk == 2 else name, "player_selectable": pk != 4}
        for pk, name in HEROES
        if pk != 3
    ]
    heroes.append({"id": 99, "name": "Newcomer"})
    httpx.put(f"{standin}/_sim/deadlock-api", json={"heroes": heroes}).raise_for_status()
    diff = champions.diff(champions.fetch_remote())
    assert [hero.name for hero in diff.new] == ["Newcomer"]
    assert [(old.name, new) for old, new in diff.renamed] == [("Seven", "Seven Again")]
    assert sorted(champion.name for champion in diff.missing_upstream) == [
        "Lady Geist",
        "Vindicta",
    ]


def test_link_reads_steam_names_from_the_stand_in(standin: str) -> None:
    assert deadlock_api.steam_names([123, 456]) == {123: "steam_123", 456: "steam_456"}
    names = {"123": "Ash", "456": None}
    httpx.put(f"{standin}/_sim/deadlock-api", json={"steam_names": names}).raise_for_status()
    assert deadlock_api.steam_names([123, 456]) == {123: "Ash"}
