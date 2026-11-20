"""Deadlock's shop items by name, for the postgame's builds.

A postgame document refers to items by deadlock-api's item ID only (league/services/postgame.py).
The names live here, in a copy of deadlock-api's shop catalogue (`DeadlockItem`), and are added
to a document when it's served. So names reach old postgames too, and a patch that renames an
item renames it everywhere at the next refresh.

The copy is refreshed by `manage.py sync_items`, and by the bot after each match check once it's
`STALE_AFTER` old. An item the copy doesn't know yet shows as "Item <id>" on the web.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.db import transaction
from django.db.models import Max

from league.integrations import deadlock_api
from league.models import DeadlockItem
from league.services import common

logger = logging.getLogger(__name__)

STALE_AFTER = timedelta(days=1)
SLOTS = frozenset({"weapon", "vitality", "spirit"})


@dataclass(frozen=True, slots=True)
class RemoteItem:
    id: int
    name: str
    slot: str
    tier: int | None


def parse(payload: Iterable[Mapping[str, Any]]) -> list[RemoteItem]:
    """The shop items in deadlock-api's catalogue. Abilities and weapons aren't bought, so
    they're left out, as is anything without an ID or a name."""
    out = []
    for item in payload:
        item_id, name = item.get("id"), item.get("name")
        if item.get("type") != "upgrade" or not isinstance(item_id, int) or item_id <= 0:
            continue
        if not isinstance(name, str) or not name.strip():
            continue
        slot = item.get("item_slot_type")
        tier = item.get("item_tier")
        out.append(
            RemoteItem(
                id=item_id,
                name=name.strip()[:100],
                slot=slot if slot in SLOTS else "",
                tier=tier if isinstance(tier, int) and tier > 0 else None,
            )
        )
    return out


def fetch_remote() -> list[RemoteItem]:
    """Network call. Run it outside any database transaction or the bot's DB thread."""
    return parse(deadlock_api.shop_items())


@transaction.atomic
def store(items: Iterable[RemoteItem]) -> int:
    """Write the catalogue: new items are added and known ones renamed. An item that has left
    the shop stays, so past builds keep its name."""
    moment = common.now()
    rows = [
        DeadlockItem(id=i.id, name=i.name, slot=i.slot, tier=i.tier, synced_at=moment)
        for i in items
    ]
    DeadlockItem.objects.bulk_create(
        rows,
        update_conflicts=True,
        unique_fields=["id"],
        update_fields=["name", "slot", "tier", "synced_at"],
    )
    return len(rows)


def sync() -> int:
    """Fetch and store the catalogue. Returns how many items it has."""
    return store(fetch_remote())


def is_stale() -> bool:
    newest = DeadlockItem.objects.aggregate(newest=Max("synced_at"))["newest"]
    return newest is None or common.now() - newest >= STALE_AFTER


def names(item_ids: Iterable[int]) -> dict[str, str]:
    """Item ID (as a string, as JSON keys are) to name, for the IDs the copy knows."""
    ids = set(item_ids)
    if not ids:
        return {}
    rows = DeadlockItem.objects.filter(id__in=ids).values_list("id", "name")
    return {str(item_id): name for item_id, name in rows}
