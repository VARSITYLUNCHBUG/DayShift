from __future__ import annotations

from devtools import api, autopilot, control, lookup, readmodels
from devtools.api import JSON, Body
from devtools.errors import BadRequest
from league.models import Community, Match, Player


def _via(body: Body) -> str:
    via = body.text("via") or autopilot.default_via()
    if via not in {autopilot.SERVICE, autopilot.DISCORD}:
        raise BadRequest('via is "service" or "discord".')
    return via


def _newest_match(league: Community) -> int:
    return (
        Match.objects.filter(community=league).order_by("-pk").values_list("pk", flat=True).first()
        or 0
    )


def _join(league: Community, players: list[Player], via: str) -> int | None:
    if via == autopilot.SERVICE:
        return control.join_queue_players(league, players)
    before = _newest_match(league)
    autopilot.press_queue(league, players, "join")
    after = _newest_match(league)
    return after if after > before else None


@api.route("POST", "queue/join", "Join players to the queue, by id or the first N free")
def join(body: Body) -> JSON:
    league = lookup.community()
    if body.has("player_ids"):
        players = [lookup.player(pk) for pk in body.ids("player_ids")]
    else:
        players = control.free_players(body.integer("count", 1) or 0)
    match_id = _join(league, players, _via(body))
    return {"queue": readmodels.queue(league), "match_id": match_id}


@api.route("POST", "queue/leave", "Take players out of the queue")
def leave(body: Body) -> JSON:
    league = lookup.community()
    players = [lookup.player(pk) for pk in body.ids("player_ids")]
    if _via(body) == autopilot.SERVICE:
        control.leave_queue(league, players)
    else:
        autopilot.press_queue(league, players, "leave")
    return {"queue": readmodels.queue(league)}


@api.route("POST", "queue/fill", "Fill the queue to the lobby size with new fake players")
def fill(body: Body) -> JSON:
    created, match_id = control.fill_queue(rating=body.raw("rating"))
    return {
        "players": readmodels.players(created),
        "queue": readmodels.queue(lookup.community()),
        "match_id": match_id,
    }
