from __future__ import annotations

from devtools import api, control, readmodels
from devtools.api import JSON, Body


@api.route("GET", "state", "Community, queue, live matches, timers and the simulator")
def get_state(body: Body) -> JSON:
    return readmodels.state()


@api.route("POST", "reset", "Back to the dev fixtures, and reset the simulator")
def reset(body: Body) -> JSON:
    report = control.reset(body.text("fixture", "dev_default") or "dev_default")
    return {"ok": True, "seed": report.as_json(), "state": readmodels.state()}


@api.route("PUT", "lobbies", 'Whether deadlock-api makes lobbies: {"lobby": "create" | "fail"}')
def set_lobbies(body: Body) -> JSON:
    control.set_lobbies(body.text("lobby") or "")
    return {"lobbies": control.lobbies()}
