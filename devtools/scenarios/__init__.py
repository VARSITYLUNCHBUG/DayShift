"""Preset scenarios: named lists of control API calls, stored as JSON next to this file."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from devtools import api
from devtools.errors import BadRequest, NotFound

HERE = Path(__file__).resolve().parent
METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})


@dataclass(frozen=True, slots=True)
class Scenario:
    name: str
    description: str
    steps: list[dict[str, Any]]

    def as_json(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "steps": self.steps}


def clean_steps(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not raw:
        raise BadRequest("steps must be a non-empty list of {method, path, body?, title?}.")
    steps = []
    for index, step in enumerate(raw):
        if not isinstance(step, dict) or not isinstance(step.get("path"), str):
            raise BadRequest(f"Step {index} needs a path.")
        method = str(step.get("method", "POST")).upper()
        if method not in METHODS:
            raise BadRequest(f"Step {index} has an unknown method {method}.")
        body = step.get("body") or {}
        if not isinstance(body, dict):
            raise BadRequest(f"Step {index}'s body must be an object.")
        title = str(step.get("title") or f"{method} {step['path']}")
        steps.append({"title": title, "method": method, "path": step["path"], "body": body})
    return steps


def _read(path: Path) -> Scenario:
    data = json.loads(path.read_text(encoding="utf-8"))
    return Scenario(path.stem, str(data.get("description", "")), clean_steps(data.get("steps")))


def load_all() -> list[Scenario]:
    return [_read(path) for path in sorted(HERE.glob("*.json"))]


def load(name: str) -> Scenario:
    path = HERE / f"{name}.json"
    if not name.replace("_", "").isalnum() or not path.exists():
        raise NotFound(f"No scenario {name!r}.")
    return _read(path)


def run(steps: list[dict[str, Any]], *, start: int = 0, count: int | None = None) -> dict[str, Any]:
    """Run steps from `start` (all of them, or `count`), stopping at the first error."""
    if not 0 <= start <= len(steps):
        raise BadRequest(f"from must be between 0 and {len(steps)}.")
    end = len(steps) if count is None else min(len(steps), start + max(count, 0))
    ran = []
    for index in range(start, end):
        step = steps[index]
        started = time.monotonic()
        status, response = api.call(step["method"], step["path"], step["body"])
        seconds = round(time.monotonic() - started, 3)
        ran.append(
            {"index": index, **step, "status": status, "seconds": seconds, "response": response}
        )
        if status >= 400:
            return {"ok": False, "ran": ran, "next": index, "total": len(steps)}
    return {"ok": True, "ran": ran, "next": end, "total": len(steps)}
