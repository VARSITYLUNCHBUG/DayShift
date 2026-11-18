from __future__ import annotations

from devtools import api
from devtools import timers as freezes
from devtools.api import JSON, Body


@api.route("POST", "timers/pause", "Freeze every live match's timers, and new ones too")
def pause_all(body: Body) -> JSON:
    return {"paused_all": True, "frozen_matches": freezes.pause_all()}


@api.route("POST", "timers/resume", "Restore every frozen timer")
def resume_all(body: Body) -> JSON:
    return {"paused_all": False, "frozen_matches": freezes.resume_all()}
