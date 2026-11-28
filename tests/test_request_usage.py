"""Request accounting must see retries, preserve cooldowns and keep tokens out of logs."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from bot import request_health
from bot.effects import gateway as gateway_module
from bot.effects.gateway import DiscordGateway


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://discord.com/api/v10/channels/123/messages/456?secret=yes",
            "/channels/:id/messages/:id",
        ),
        (
            "https://discord.com/api/v10/interactions/123/secret/callback",
            "/interactions/:id/:token/callback",
        ),
        (
            "https://discord.com/api/v10/webhooks/123/secret/messages/@original",
            "/webhooks/:id/:token/messages/@original",
        ),
        ("https://discord.com/api/v10/invites/secret", "/invites/:code"),
    ],
)
def test_routes_do_not_contain_ids_tokens_or_query_strings(url: str, expected: str) -> None:
    assert request_health.request_route(url) == expected


def test_usage_counts_retries_and_reports_headers_without_tokens(
    caplog: pytest.LogCaptureFixture,
) -> None:
    clock = [0.0]
    counter = request_health.FailedRequests(clock=lambda: clock[0])
    url = "https://discord.com/api/v10/webhooks/123/private-token/messages/@original?secret=x"
    headers = {
        "X-RateLimit-Bucket": "bucket-a",
        "X-RateLimit-Limit": "5",
        "X-RateLimit-Remaining": "0",
        "X-RateLimit-Reset-After": "1.5",
        "X-RateLimit-Scope": "shared",
        "Retry-After": "84927",
    }
    with caplog.at_level(logging.INFO, logger="bot.request_health"):
        counter.response("PATCH", url, 429, headers)
        counter.response("PATCH", url, 200, {**headers, "X-RateLimit-Remaining": "4"})
        clock[0] = 60.0
        counter.log_usage_summary()
        counter.log_usage_summary()  # An empty interval doesn't repeat the previous numbers.
    limited = next(r for r in caplog.records if r.getMessage() == "Discord request rate limited")
    assert limited.retry_after_seconds == "84927"
    assert limited.scope == "shared"
    summaries = [r for r in caplog.records if r.getMessage() == "Discord API usage"]
    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.requests == 2
    assert summary.window_seconds == 60.0
    assert {r["status"]: r["count"] for r in summary.routes} == {200: 1, 429: 1}
    assert summary.invalid_requests_10m == 0
    assert summary.last_observed_buckets[0]["remaining"] == "4"
    assert "private-token" not in repr([r.__dict__ for r in caplog.records])
    assert "secret=x" not in repr([r.__dict__ for r in caplog.records])


def test_trace_records_actual_responses_and_network_failures(
    caplog: pytest.LogCaptureFixture,
) -> None:
    counter = request_health.FailedRequests()
    trace = counter.trace_config()
    trace.freeze()
    context = SimpleNamespace()
    url = "https://discord.com/api/v10/channels/123/messages"

    async def scenario() -> None:
        await trace.on_request_start.send(None, context, SimpleNamespace())
        await trace.on_request_end.send(
            None,
            context,
            SimpleNamespace(
                method="GET",
                url="wss://gateway.discord.gg/?v=10",
                response=SimpleNamespace(status=101, headers={}),
            ),
        )
        await trace.on_request_end.send(
            None,
            context,
            SimpleNamespace(
                method="POST", url=url, response=SimpleNamespace(status=403, headers={})
            ),
        )
        await trace.on_request_exception.send(
            None,
            context,
            SimpleNamespace(method="POST", url=url, exception=TimeoutError("secret detail")),
        )

    asyncio.run(scenario())
    with caplog.at_level(logging.INFO, logger="bot.request_health"):
        counter.log_usage_summary()
    summary = next(r for r in caplog.records if r.getMessage() == "Discord API usage")
    assert summary.requests == 1
    assert summary.invalid_requests_10m == 1
    assert summary.network_errors == [
        {"method": "POST", "route": "/channels/:id/messages", "error": "TimeoutError", "count": 1}
    ]
    assert "secret detail" not in repr(summary.__dict__)


def test_failed_dms_are_not_repeated_during_the_cooldown_then_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stamp = [0.0]
    monkeypatch.setattr(gateway_module, "time", SimpleNamespace(monotonic=lambda: stamp[0]))
    failure = discord.Forbidden(
        SimpleNamespace(status=403, reason="Forbidden"), {"code": 50007, "message": "DMs closed"}
    )
    channel = MagicMock(send=AsyncMock(side_effect=[failure, SimpleNamespace(id=77)]))
    client = MagicMock(create_dm=AsyncMock(return_value=channel))
    gateway = DiscordGateway(client)

    async def scenario() -> None:
        assert await gateway.send_dm(123, MagicMock()) is None
        assert await gateway.send_dm(123, MagicMock()) is None
        assert client.create_dm.await_count == 1
        assert channel.send.await_count == 1
        stamp[0] = gateway_module.DM_UNAVAILABLE_SECONDS + 1
        assert await gateway.send_dm(123, MagicMock()) == 77
        assert channel.send.await_count == 2

    asyncio.run(scenario())


def test_server_errors_do_not_suppress_later_dm_attempts() -> None:
    failure = discord.HTTPException(
        SimpleNamespace(status=503, reason="Unavailable"), {"code": 0, "message": "Unavailable"}
    )
    channel = MagicMock(send=AsyncMock(side_effect=[failure, SimpleNamespace(id=77)]))
    gateway = DiscordGateway(MagicMock(create_dm=AsyncMock(return_value=channel)))

    async def scenario() -> None:
        with pytest.raises(discord.HTTPException):
            await gateway.send_dm(123, MagicMock())
        assert await gateway.send_dm(123, MagicMock()) == 77

    asyncio.run(scenario())


def test_unavailable_dm_cache_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gateway_module, "DM_UNAVAILABLE_CACHE_SIZE", 2)
    gateway = DiscordGateway(MagicMock())
    for user_id in (1, 2, 3):
        gateway._remember_unavailable_dm(user_id)
    assert set(gateway._dm_unavailable_until) == {2, 3}


def test_the_busiest_second_counts_bot_token_requests_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    clock = iter([0.0, 0.1, 0.2, 0.3, 1.5, 1.6, 2.0])
    failed = request_health.FailedRequests(clock=lambda: next(clock))
    url = "https://discord.com/api/v10/channels/9/messages"
    for _ in range(3):
        failed.response("POST", url, 200, {})
    failed.response("POST", "https://discord.com/api/v10/interactions/1/tok/callback", 204, {})
    failed.response("PATCH", url + "/5", 200, {})  # 1.5 s: the first three have left the window.
    with caplog.at_level(logging.INFO, logger="bot.request_health"):
        failed.log_usage_summary()
    summary = next(r for r in caplog.records if r.getMessage() == "Discord API usage")
    assert summary.peak_per_second == 3


def test_load_tests_get_a_line_per_request_without_tokens(
    caplog: pytest.LogCaptureFixture,
) -> None:
    failed = request_health.FailedRequests()
    failed.log_each = True
    headers = {"X-RateLimit-Bucket": "abc", "X-RateLimit-Limit": "5", "X-RateLimit-Remaining": "4"}
    with caplog.at_level(logging.INFO, logger="bot.request_log"):
        failed.response(
            "POST", "https://discord.com/api/v10/channels/77/messages", 200, headers, 0.25
        )
        failed.response("POST", "https://discord.com/api/v10/webhooks/8/secret", 200, {}, 0.1)
    lines = [r for r in caplog.records if r.name == "bot.request_log"]
    assert [(r.route, r.major, r.ms) for r in lines] == [
        ("/channels/:id/messages", "77", 250),
        ("/webhooks/:id/:token", None, 100),
    ]
    assert "secret" not in str([r.__dict__ for r in lines])
