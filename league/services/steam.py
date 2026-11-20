"""Optional Steam accounts: a player may link several, and an account belongs to one player.

A link starts as what the player says (/link). It becomes proven when the player signs in to that
account through Steam on the web, and verified when deadlock-api shows that account on the
player's own team in one of their matches. Neither can be faked from Discord. Verified links let
result checks and awards work by account instead of by scoreboard name; proven or verified links
can sign in to the web with Steam.

Only proof moves an account between players: a claim nobody proved or verified gives way to the
player who signs in to it, while a plain /link never takes an account from anyone.

Every change publishes `player:<id>` for each player it touched, so their open pages refresh.
"""

from __future__ import annotations

from collections.abc import Iterable

from django.db import IntegrityError, transaction

from league.domain.errors import InvalidAction
from league.models import Player, SteamAccount
from league.services import live
from league.services.common import now

TAKEN = "That Steam account is already linked to someone else. Ask staff if it's yours."
PROVEN_ELSEWHERE = (
    "That Steam account belongs to another player, who has already proven or verified it. "
    "Ask staff if it's yours."
)
RACED = "That Steam account was linked by someone else just now. Ask staff if it's yours."


def is_proven_or_verified(account: SteamAccount) -> bool:
    """Whether the account's owner showed it's theirs: by Steam sign-in, or in a match."""
    return account.proven_at is not None or account.verified_at is not None


def _create(player: Player, account_id: int, steam_name: str, **extra: object) -> SteamAccount:
    """A new row. Two players linking the same new account at once can't both get it."""
    try:
        with transaction.atomic():
            return SteamAccount.objects.create(
                player=player,
                account_id=account_id,
                steam_name=steam_name,
                linked_at=now(),
                **extra,
            )
    except IntegrityError as exc:
        raise InvalidAction(RACED) from exc


@transaction.atomic
def link(player: Player, account_id: int, steam_name: str = "") -> SteamAccount:
    """Link an account to the player, or refresh the name of one they already have. Never takes
    an account another player holds, proven or not."""
    name = steam_name[:100]
    row = SteamAccount.objects.select_for_update().filter(account_id=account_id).first()
    if row is not None and row.player_id != player.pk:
        raise InvalidAction(TAKEN)
    if row is None:
        row = _create(player, account_id, name)
    elif name and row.steam_name != name:
        row.steam_name = name
        row.save(update_fields=["steam_name"])
    else:
        return row
    live.publish(live.player_topic(player.pk))
    return row


@transaction.atomic
def link_proven(player: Player, account_id: int, steam_name: str = "") -> SteamAccount:
    """The player signed in to this account through Steam, so it's theirs. Another player's
    unproven, unverified claim on it moves to them; a proven or verified one is refused."""
    name = steam_name[:100]
    moment = now()
    row = SteamAccount.objects.select_for_update().filter(account_id=account_id).first()
    if row is None:
        row = _create(player, account_id, name, proven_at=moment)
        live.publish(live.player_topic(player.pk))
        return row
    topics = [live.player_topic(player.pk)]
    if row.player_id != player.pk:
        if is_proven_or_verified(row):
            raise InvalidAction(PROVEN_ELSEWHERE)
        topics.append(live.player_topic(row.player_id))
        row.player = player
        row.linked_at = moment
        row.verified_at = None
    if name:
        row.steam_name = name
    row.proven_at = moment
    row.save(update_fields=["player", "linked_at", "verified_at", "steam_name", "proven_at"])
    live.publish(*topics)
    return row


@transaction.atomic
def unlink(player: Player, account_id: int | None = None) -> int:
    """Remove one of the player's accounts, or every one with no account given. Returns how many
    went."""
    rows = SteamAccount.objects.filter(player=player)
    if account_id is not None:
        rows = rows.filter(account_id=account_id)
    removed, _ = rows.delete()
    if removed:
        live.publish(live.player_topic(player.pk))
    return removed


@transaction.atomic
def mark_verified(account_ids: Iterable[int]) -> int:
    """Linked accounts that deadlock-api showed on their player's team."""
    ids = list(account_ids)
    if not ids:
        return 0
    unverified = SteamAccount.objects.select_for_update().filter(
        account_id__in=ids, verified_at__isnull=True
    )
    newly = dict(unverified.values_list("pk", "player_id"))
    if not newly:
        return 0
    updated = SteamAccount.objects.filter(pk__in=list(newly)).update(verified_at=now())
    live.publish(*(live.player_topic(player_id) for player_id in sorted(set(newly.values()))))
    return updated


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
