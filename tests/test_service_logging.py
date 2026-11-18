"""Log lines name their process and the match they belong to, as JSON or, for a terminal, text."""

from __future__ import annotations

import json
import logging
import sys

import pytest

import config.logging
from config.logging import JsonFormatter, TextFormatter, formatter, set_process
from league import log_context


@pytest.fixture(autouse=True)
def _clean_process_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config.logging, "_process", {})
    monkeypatch.delenv("SERVICE_NAME", raising=False)


def record(msg: str = "Match deadline skipped", **extra: object) -> logging.LogRecord:
    made = logging.makeLogRecord({"name": "league.services.deadlines", "levelname": "INFO"})
    made.msg = msg
    made.__dict__.update(extra)
    return made


def test_json_lines_carry_the_process_and_the_bound_match() -> None:
    set_process(service="bot", role="scheduler")
    with log_context.bind(guild=999, match=42):
        line = json.loads(JsonFormatter().format(record(why="already moved")))
    assert line["msg"] == "Match deadline skipped"
    assert line["level"] == "INFO"
    assert line["logger"] == "league.services.deadlines"
    assert {key: line[key] for key in ("service", "role", "guild", "match", "why")} == {
        "service": "bot",
        "role": "scheduler",
        "guild": 999,
        "match": 42,
        "why": "already moved",
    }


def test_a_records_own_fields_win_over_the_bound_ones() -> None:
    with log_context.bind(match=42):
        line = json.loads(JsonFormatter().format(record(match=7)))
    assert line["match"] == 7


def test_service_name_in_the_environment_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVICE_NAME", "scheduler")
    set_process(service="bot", role="scheduler")
    assert json.loads(JsonFormatter().format(record()))["service"] == "scheduler"


def test_text_lines_read_well_in_a_terminal() -> None:
    set_process(service="bot", role="gateway")
    with log_context.bind(match=42):
        line = TextFormatter().format(record("Effect will retry", kind="render_board"))
    assert line.endswith(
        " INFO league.services.deadlines: Effect will retry"
        " service=bot role=gateway match=42 kind=render_board"
    )


def test_text_lines_keep_the_traceback() -> None:
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        failed = record("Deadline loop error")
        failed.exc_info = sys.exc_info()
    line = TextFormatter().format(failed)
    assert line.splitlines()[0].endswith("Deadline loop error")
    assert "RuntimeError: boom" in line


def test_log_format_picks_the_formatter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    assert type(formatter()) is JsonFormatter
    monkeypatch.setenv("LOG_FORMAT", "text")
    assert type(formatter()) is TextFormatter
    monkeypatch.setenv("LOG_FORMAT", "yaml")
    with pytest.raises(ValueError, match="LOG_FORMAT must be json or text"):
        formatter()
