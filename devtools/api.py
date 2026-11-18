"""The control API's routing, shared by the HTTP view and the scenario runner.

Each route is a plain function of a `Body` and its path parameters that returns JSON. The view
and `scenarios.run` both go through `call`, so a scenario step is exactly an API request.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from devtools import timers
from devtools.errors import BadRequest, ControlError, NotFound
from league.domain.errors import DomainError, NotAllowed, StaleAction

logger = logging.getLogger(__name__)

JSON = dict[str, Any]
Handler = Callable[..., JSON]
PARAMS = {"match": r"(?P<match>\d+|latest)", "player": r"(?P<player>\d+)"}


@dataclass(frozen=True, slots=True)
class Route:
    method: str
    path: str
    summary: str
    handler: Handler
    pattern: re.Pattern[str]


ROUTES: list[Route] = []


def route(method: str, path: str, summary: str) -> Callable[[Handler], Handler]:
    regex = re.sub(r"\{(\w+)\}", lambda m: PARAMS[m.group(1)], path)

    def register(handler: Handler) -> Handler:
        ROUTES.append(Route(method, path, summary, handler, re.compile(f"^{regex}$")))
        return handler

    return register


class Body:
    """A request's JSON body and query string, with typed getters that answer 400."""

    def __init__(self, data: Any = None, query: dict[str, str] | None = None) -> None:
        if data is None:
            data = {}
        if not isinstance(data, dict):
            raise BadRequest("The body must be a JSON object.")
        self.data: JSON = data
        self.query = query or {}

    def has(self, key: str) -> bool:
        return self.data.get(key) is not None

    def raw(self, key: str, default: Any = None) -> Any:
        value = self.data.get(key)
        return default if value is None else value

    def integer(self, key: str, default: int | None = None) -> int | None:
        value = self.data.get(key)
        if value is None:
            return default
        if isinstance(value, bool) or not isinstance(value, int | str):
            raise BadRequest(f"{key} must be a whole number.")
        try:
            return int(value)
        except ValueError as exc:
            raise BadRequest(f"{key} must be a whole number.") from exc

    def text(self, key: str, default: str | None = None) -> str | None:
        value = self.data.get(key)
        if value is None:
            return default
        if not isinstance(value, str):
            raise BadRequest(f"{key} must be a string.")
        return value

    def flag(self, key: str, default: bool | None = None) -> bool | None:
        value = self.data.get(key)
        if value is None:
            return default
        if not isinstance(value, bool):
            raise BadRequest(f"{key} must be true or false.")
        return value

    def mapping(self, key: str) -> JSON:
        value = self.data.get(key)
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise BadRequest(f"{key} must be an object.")
        return value

    def ids(self, key: str) -> list[int]:
        value = self.data.get(key)
        if not isinstance(value, list) or not value:
            raise BadRequest(f"{key} must be a list of ids.")
        try:
            return [int(item) for item in value]
        except (TypeError, ValueError) as exc:
            raise BadRequest(f"{key} must be a list of ids.") from exc


def error(status: int, code: str, message: str) -> tuple[int, JSON]:
    return status, {"error": {"code": code, "message": message}}


def resolve(method: str, path: str) -> tuple[Route, dict[str, str]]:
    path = path.strip("/")
    found = [(r, m) for r in ROUTES if (m := r.pattern.match(path))]
    if not found:
        raise NotFound(f"No route {path!r}. GET /_control/api/ lists them.")
    for candidate, matched in found:
        if candidate.method == method:
            return candidate, matched.groupdict()
    allowed = ", ".join(sorted({r.method for r, _ in found}))
    raise BadRequest(f"{path} takes {allowed}, not {method}.")


def call(
    method: str, path: str, data: Any = None, query: dict[str, str] | None = None
) -> tuple[int, JSON]:
    """Run one API request. Returns (HTTP status, JSON body)."""
    try:
        target, params = resolve(method.upper(), path)
        body = Body(data, query)
        timers.sweep()
        result = target.handler(body, **params)
        timers.sweep()
        return 200, result
    except ControlError as exc:
        return error(exc.status, exc.code, exc.message)
    except NotAllowed as exc:
        return error(403, "not_allowed", exc.message)
    except StaleAction as exc:
        return error(409, "stale_action", exc.message)
    except DomainError as exc:
        return error(409, "invalid_action", exc.message)
    except Exception:
        logger.exception("Control API request failed", extra={"method": method, "path": path})
        return error(500, "server_error", "The request failed: the web process logged why.")


def describe() -> JSON:
    return {
        "name": "devtools",
        "docs": "devtools/README.md",
        "routes": [{"method": r.method, "path": r.path, "summary": r.summary} for r in ROUTES],
    }
