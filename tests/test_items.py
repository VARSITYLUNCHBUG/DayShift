"""The shop items' names, for the postgame's builds (league/services/items.py). Nothing here calls
deadlock-api: the catalogue comes from small hand-made entries in its shape."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from io import StringIO
from typing import Any

import pytest
from django.core.management import call_command

from bot.effects import handlers
from league.integrations import deadlock_api
from league.models import DeadlockItem, Match
from league.services import api_results, items, postgame
from tests.conftest import Clock
from tests.test_postgame import DEADLOCK_ID, metadata
from tests.test_postgame import reported as reported


def _entry(item_id: Any, name: Any, kind: str = "upgrade", **more: Any) -> dict[str, Any]:
    return {"id": item_id, "name": name, "type": kind, **more}


CATALOGUE = [
    _entry(1548066885, "Extended Magazine", item_slot_type="weapon", item_tier=1),
    _entry(7409189, "Healing Rite ", item_slot_type="vitality", item_tier=1),
    _entry(1, "Charged Shot", "ability"),
    _entry(2, "Pistol", "weapon"),
    _entry(None, "No ID"),
    _entry(3, ""),
    _entry(4, "Odd Slot", item_slot_type="hats", item_tier=0),
]


def test_only_shop_items_with_an_id_and_a_name_are_kept() -> None:
    parsed = items.parse(CATALOGUE)
    assert [(i.id, i.name, i.slot, i.tier) for i in parsed] == [
        (1548066885, "Extended Magazine", "weapon", 1),
        (7409189, "Healing Rite", "vitality", 1),
        (4, "Odd Slot", "", None),
    ]


@pytest.mark.django_db
def test_storing_renames_and_keeps_items_that_left_the_shop() -> None:
    items.store(items.parse(CATALOGUE))
    renamed = [items.RemoteItem(1548066885, "Big Magazine", "weapon", 1)]
    assert items.store(renamed) == 1
    assert items.names([1548066885, 7409189, 999]) == {
        "1548066885": "Big Magazine",
        "7409189": "Healing Rite",
    }
    assert items.names([]) == {}


@pytest.mark.django_db
def test_the_copy_goes_stale_after_a_day(clock: Clock) -> None:
    assert items.is_stale()  # Nothing copied yet.
    items.store(items.parse(CATALOGUE))
    assert not items.is_stale()
    clock.advance(int(items.STALE_AFTER.total_seconds()))
    assert items.is_stale()


@pytest.mark.django_db
def test_sync_items_stores_the_catalogue(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(deadlock_api, "shop_items", lambda: CATALOGUE)
    out = StringIO()
    call_command("sync_items", stdout=out)
    assert "Stored 3 items." in out.getvalue()
    assert DeadlockItem.objects.count() == 3


@pytest.mark.django_db
def test_the_served_postgame_names_the_items_it_knows(reported: Match) -> None:
    api_results.record_metadata(reported.pk, DEADLOCK_ID, metadata())
    first = postgame.stored(reported)
    assert first is not None and first.item_names == {}  # The copy is empty: "Item <id>".
    bought = sorted({buy.item_id for line in first.players for buy in line.build})
    items.store([items.RemoteItem(bought[0], "Extended Magazine", "weapon", 1)])
    doc = postgame.stored(reported)
    assert doc is not None and doc.item_names == {str(bought[0]): "Extended Magazine"}
    # The stored document itself never carries names, so a rename reaches old postgames too.
    assert reported.postgame.data["item_names"] == {}


@pytest.mark.django_db(transaction=True)
def test_the_bot_refreshes_a_stale_copy_after_a_check(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fetch() -> list[dict[str, Any]]:
        calls.append("fetch")
        return CATALOGUE

    monkeypatch.setattr(deadlock_api, "shop_items", fetch)
    asyncio.run(handlers._refresh_items())
    asyncio.run(handlers._refresh_items())  # Fresh now: no second fetch.
    assert calls == ["fetch"] and DeadlockItem.objects.count() == 3


@pytest.mark.django_db(transaction=True)
def test_a_failed_refresh_keeps_the_old_names(monkeypatch: pytest.MonkeyPatch) -> None:
    items.store(items.parse(CATALOGUE))
    DeadlockItem.objects.update(synced_at=items.common.now() - timedelta(days=2))

    def down() -> list[dict[str, Any]]:
        raise deadlock_api.ApiError("deadlock-api unreachable: ConnectError")

    monkeypatch.setattr(deadlock_api, "shop_items", down)
    asyncio.run(handlers._refresh_items())
    assert items.names([1548066885]) == {"1548066885": "Extended Magazine"}
