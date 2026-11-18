from __future__ import annotations

from devtools import api
from devtools import scenarios as presets
from devtools.api import JSON, Body


@api.route("GET", "scenarios", "The preset scenarios in devtools/scenarios/")
def list_scenarios(body: Body) -> JSON:
    return {"scenarios": [scenario.as_json() for scenario in presets.load_all()]}


@api.route("POST", "scenarios/run", "Run a scenario by name, or a list of steps")
def run(body: Body) -> JSON:
    name = body.text("name")
    steps = presets.load(name).steps if name else presets.clean_steps(body.raw("steps"))
    return presets.run(steps, start=body.integer("from", 0) or 0, count=body.integer("count"))
