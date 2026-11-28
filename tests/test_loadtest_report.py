"""The load test report reads the bot's request lines and finds how close each limit came."""

from __future__ import annotations

import json

from devtools import loadtest_report


def _line(at: str, route: str, status: int = 200, **fields: object) -> str:
    row = {"ts": f"2026-11-28T20:00:{at}+00:00", "msg": "Discord request", "method": "POST"}
    row.update(route=route, status=status, **fields)
    return json.dumps(row)


def test_the_report_finds_the_busiest_second_rate_limits_and_tightest_bucket() -> None:
    lines = [
        _line("00.1", "/channels/:id/messages", bucket="b", major="1", limit=5, remaining=4),
        _line("00.2", "/channels/:id/messages", bucket="b", major="1", limit=5, remaining=0),
        _line("00.3", "/channels/:id/messages", 429, bucket="b", major="1", scope="user"),
        _line("00.4", "/interactions/:id/:token/callback"),  # Not on the bot token.
        _line("05.0", "/guilds/:id/channels", bucket="g", major="2", limit=2000, remaining=1999),
        "not json",
        json.dumps({"msg": "Something else"}),
    ]
    requests = list(loadtest_report.parse(lines))
    assert len(requests) == 5
    text = loadtest_report.report(requests)
    assert "Busiest second: 3 bot-token requests" in text
    assert "Rate limits (429): 1" in text
    assert "scope=user" in text
    assert "Refused requests Discord counts: 1" in text
    buckets = text.split("Buckets")[1]
    assert buckets.index("limit     5") < buckets.index("limit  2000")  # Tightest first.
