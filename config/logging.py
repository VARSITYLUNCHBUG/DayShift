"""One-line JSON logs, so `docker compose logs` output can be shipped anywhere.

`LOG_FORMAT=text` gives plain lines instead, which read better in a local terminal. Either way each
line carries the process's service and role, then the server, match or effect the code was working
on (`league.log_context`), then the call's own `extra` fields, later ones winning.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

from league import log_context

# Not `extra` fields: the record's own attributes, the formatter's, and uvicorn's color_message
# (its message again, with ANSI colour codes, for its own formatter).
_RESERVED = set(logging.makeLogRecord({}).__dict__) | {
    "message",
    "asctime",
    "taskName",
    "color_message",
}

# Which process this is, such as {"service": "bot"}. Set by `set_process`.
_process: dict[str, str] = {}


def set_process(*, service: str, role: str | None = None) -> None:
    """Name this process in every log line. A `SERVICE_NAME` environment variable wins."""
    _process["service"] = os.environ.get("SERVICE_NAME") or service
    if role is not None:
        _process["role"] = role


def fields(record: logging.LogRecord) -> dict[str, Any]:
    """The line's context: process, then bound `log_context`, then the record's `extra`."""
    merged: dict[str, Any] = {**_process, **log_context.current()}
    merged.update(
        (key, _loggable(value)) for key, value in record.__dict__.items() if key not in _RESERVED
    )
    return merged


def _loggable(value: Any) -> Any:
    """A request (django.request attaches one to every 4xx and 5xx) as its method and path: its
    repr has the query string, and OAuth callbacks carry their code there."""
    from django.http import HttpRequest

    if isinstance(value, HttpRequest):
        return f"{value.method} {value.path}"
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            **fields(record),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class TextFormatter(logging.Formatter):
    """`12:00:01.234 INFO bot.client: Connected service=bot role=gateway user=...`"""

    def format(self, record: logging.LogRecord) -> str:
        moment = datetime.fromtimestamp(record.created).strftime("%H:%M:%S.%f")[:-3]
        line = f"{moment} {record.levelname} {record.name}: {record.getMessage()}"
        extras = " ".join(f"{key}={value}" for key, value in fields(record).items())
        if extras:
            line = f"{line} {extras}"
        if record.exc_info:
            line = f"{line}\n{self.formatException(record.exc_info)}"
        return line


def formatter() -> logging.Formatter:
    """The formatter `LOG_FORMAT` asks for: `json` (the default) or `text`."""
    choice = os.environ.get("LOG_FORMAT", "json").strip().lower()
    if choice == "text":
        return TextFormatter()
    if choice != "json":
        raise ValueError(f"LOG_FORMAT must be json or text, not {choice!r}.")
    return JsonFormatter()
