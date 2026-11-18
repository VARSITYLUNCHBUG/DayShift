from __future__ import annotations

from devtools import api, autopilot, control, lookup, readmodels
from devtools import timers as freezes
from devtools.api import JSON, Body
from devtools.errors import BadRequest


@api.route("GET", "matches/{match}", "One match")
def get_match(body: Body, match: str) -> JSON:
    return readmodels.match(lookup.match(match))


@api.route("PUT", "matches/{match}/script", "How the autopilot plays this match")
def set_script(body: Body, match: str) -> JSON:
    row = lookup.match(match)
    control.set_script(row, body.data)
    return readmodels.match(row)


@api.route("POST", "matches/{match}/advance", "Complete the phase, or every phase up to until")
def advance(body: Body, match: str) -> JSON:
    row, start, done, phases = autopilot.advance(match, body.text("until"), body.text("via"))
    return {
        "match": readmodels.match(row),
        "from": start,
        "to": row.status,
        "phases": [phase.as_json() for phase in phases],
        "actions": [entry.as_json() for entry in done],
    }


@api.route("POST", "matches/{match}/act", "One action as one player")
def act(body: Body, match: str) -> JSON:
    action = body.text("action")
    if not action:
        raise BadRequest("act needs an action.")
    row = lookup.match(match)
    refs = body.raw("player_ids")
    if refs is not None and not isinstance(refs, list):
        raise BadRequest("player_ids must be a list of player ids or selectors.")
    done = []
    for ref in refs if refs is not None else [body.raw("player_id")]:
        done += autopilot.act(row.pk, ref, action, body.mapping("args"), body.text("via"))
    return {"match": readmodels.match(row), "actions": [entry.as_json() for entry in done]}


@api.route("POST", "matches/{match}/fire", "Run out the current timer now")
def fire(body: Body, match: str) -> JSON:
    row = lookup.match(match)
    fired = freezes.fire(row.pk)
    return {"match": readmodels.match(row), "fired": fired}


@api.route("POST", "matches/{match}/pause", "Freeze this match's timers")
def pause(body: Body, match: str) -> JSON:
    row = lookup.match(match)
    freezes.freeze(row.pk)
    return readmodels.match(row)


@api.route("POST", "matches/{match}/resume", "Restore this match's timers")
def resume(body: Body, match: str) -> JSON:
    row = lookup.match(match)
    freezes.resume(row.pk)
    return readmodels.match(row)
