"""Optional Steam accounts: a player may link several, and an account belongs to one player.

A link is what the player says. It becomes verified when deadlock-api shows that account on the
player's own team in one of their matches, which nobody can fake from Discord. Verified links let
result checks and awards work by account instead of by scoreboard name.
"""

from __future__ import annotations

from collections.abc import Iterable

from django.db import transaction

from league.domain.errors import InvalidAction
from league.models import Player, SteamAccount
from league.services.common import now


@transaction.atomic
def link(player: Player, account_id: int, steam_name: str = "") -> SteamAccount:
    """Link an account to the player, or refresh the name of one they already have."""
    row = SteamAccount.objects.select_for_update().filter(account_id=account_id).first()
    if row is not None and row.player_id != player.pk:
        raise InvalidAction(
            "That Steam account is already linked to someone else. Ask staff if it's yours."
        )
    if row is None:
        return SteamAccount.objects.create(
            player=player, account_id=account_id, steam_name=steam_name[:100], linked_at=now()
        )
    if steam_name and row.steam_name != steam_name[:100]:
        row.steam_name = steam_name[:100]
        row.save(update_fields=["steam_name"])
    return row


@transaction.atomic
def unlink(player: Player, account_id: int | None = None) -> int:
    """Remove one of the player's accounts, or every one with no account given. Returns how many
    went."""
    rows = SteamAccount.objects.filter(player=player)
    if account_id is not None:
        rows = rows.filter(account_id=account_id)
    removed, _ = rows.delete()
    return removed


def mark_verified(account_ids: Iterable[int]) -> int:
    """Linked accounts that deadlock-api showed on their player's team."""
    ids = list(account_ids)
    if not ids:
        return 0
    return SteamAccount.objects.filter(account_id__in=ids, verified_at__isnull=True).update(
        verified_at=now()
    )


def accounts_of(player_ids: Iterable[int]) -> dict[int, int]:
    """Every linked account of these players, as account ID to player ID."""
    return dict(
        SteamAccount.objects.filter(player_id__in=list(player_ids)).values_list(
            "account_id", "player_id"
        )
    )


def describe(player: Player) -> str:
    rows = list(SteamAccount.objects.filter(player=player))
    if not rows:
        return "No Steam account linked. Use /link to add one (optional)."
    parts = []
    for row in rows:
        name = f"**{row.steam_name}**" if row.steam_name else f"account {row.account_id}"
        status = "verified in a match" if row.verified_at else "not yet seen in a match"
        parts.append(f"{name}, {status}")
    label = "Steam" if len(rows) == 1 else f"Steam ({len(rows)} accounts)"
    return f"{label}: {'; '.join(parts)}."
