"""What the log formatters keep out of a line: uvicorn's coloured copy, request query strings."""

from __future__ import annotations

import json
import logging

import pytest
from django.test import Client, RequestFactory

from config.logging import JsonFormatter, TextFormatter


def test_uvicorns_coloured_copy_of_the_message_stays_out_of_the_json() -> None:
    record = logging.makeLogRecord(
        {
            "name": "uvicorn.error",
            "levelname": "INFO",
            "msg": "Started server process [%d]",
            "args": (1,),
            "color_message": "Started server process [\x1b[36m%d\x1b[0m]",
        }
    )
    line = JsonFormatter().format(record)
    assert "color_message" not in line and "\\u001b" not in line


def test_a_request_is_logged_as_its_method_and_path_without_the_query() -> None:
    request = RequestFactory().get("/auth/discord/callback/", {"code": "OAUTHCODE1", "state": "x"})
    record = logging.makeLogRecord(
        {"name": "django.request", "levelname": "WARNING", "msg": "Bad Request", "request": request}
    )
    for formatter in (JsonFormatter(), TextFormatter()):
        line = formatter.format(record)
        assert "OAUTHCODE1" not in line and "state=" not in line, line
        assert "GET /auth/discord/callback/" in line
    assert json.loads(JsonFormatter().format(record))["request"] == ("GET /auth/discord/callback/")


@pytest.mark.django_db
def test_djangos_own_4xx_lines_carry_no_query_string(caplog: pytest.LogCaptureFixture) -> None:
    """django.request attaches the request to every 4xx and 5xx it logs."""
    with caplog.at_level(logging.WARNING, logger="django.request"):
        Client().get("/api/no-such-page/?code=OAUTHCODE2&state=x")
    records = [record for record in caplog.records if record.name == "django.request"]
    assert records
    for record in records:
        line = JsonFormatter().format(record)
        assert "OAUTHCODE2" not in line, line
        assert "GET /api/no-such-page/" in line
