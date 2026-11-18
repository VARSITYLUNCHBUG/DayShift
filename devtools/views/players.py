from __future__ import annotations

from devtools import api, control, lookup, readmodels
from devtools.api import JSON, Body
from league.models import Player


@api.route("GET", "players", "Every player, with rating, queue place and live match")
def list_players(body: Body) -> JSON:
    rows = Player.objects.order_by("pk")
    if body.query.get("all") not in {"1", "true"}:
        rows = rows.exclude(dev_profile__retired=True)
    return {"players": readmodels.players(list(rows))}


@api.route("POST", "players", "Make fake players, seed their ratings, optionally queue them")
def create_players(body: Body) -> JSON:
    created, match_id = control.create_players(
        body.integer("count", 1) or 0,
        rating=body.raw("rating"),
        name_prefix=body.text("name_prefix", "Dev") or "Dev",
        join_queue=bool(body.flag("join_queue", False)),
        dm_open=bool(body.flag("dm_open", True)),
    )
    return {"players": readmodels.players(created), "match_id": match_id}


@api.route("PATCH", "players/{player}", "Change a player's rating, name or DM setting")
def update_player(body: Body, player: str) -> JSON:
    control.update_player(
        lookup.player(player),
        rating=body.integer("rating"),
        name=body.text("name"),
        dm_open=body.flag("dm_open"),
    )
    return readmodels.player(lookup.player(player))


@api.route("DELETE", "players/{player}", "Delete a player, or retire one with history")
def delete_player(body: Body, player: str) -> JSON:
    return {"deleted": control.delete_player(lookup.player(player))}


@api.route("PUT", "players/{player}/picks", "The champions this player prefers and bans")
def set_picks(body: Body, player: str) -> JSON:
    row = lookup.player(player)
    control.set_picks(row, prefer=body.raw("prefer", []), ban=body.raw("ban", []))
    return readmodels.player(row)
