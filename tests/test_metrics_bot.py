"""The bot's metrics: the endpoint the gateway and the scheduler serve, and what feeds it."""

from __future__ import annotations

import asyncio
import logging
import math
import socket
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from django.test import override_settings

from bot import client as client_module
from bot import metrics
from bot.client import Heartbeat, deadline_loop
from bot.effects import worker as worker_module


def sample(name: str, **labels: str) -> float:
    return metrics.REGISTRY.get_sample_value(name, labels) or 0.0


@pytest.fixture
def root_handlers(monkeypatch: pytest.MonkeyPatch) -> None:
    """`serve` adds a handler to the root logger: take it off again afterwards."""
    root = logging.getLogger()
    monkeypatch.setattr(root, "handlers", list(root.handlers))


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


def test_serve_exposes_the_bots_metrics_and_nothing_else(root_handlers: None) -> None:
    port = free_port()
    with override_settings(METRICS_PORT=port):
        server = metrics.serve()
    assert server is not None
    try:
        body = httpx.get(f"http://127.0.0.1:{port}/metrics", timeout=5).text
    finally:
        server.shutdown()
        server.server_close()
    for name in ("draftbot_loop_heartbeat_timestamp_seconds", "draftbot_effects_total"):
        assert name in body
    assert "python_info" in body
    # The web process's series stay out, even though importing the URL conf loads them.
    assert "draftbot_http_requests" not in body
    assert "draftbot_queue_players" not in body


def test_serve_binds_loopback_unless_metrics_addr_says_otherwise(root_handlers: None) -> None:
    from django.conf import settings

    # A run on this machine never exposes the port to the network; compose sets 0.0.0.0.
    assert settings.METRICS_ADDR == "127.0.0.1"
    for addr in ("127.0.0.1", "0.0.0.0"):
        with override_settings(METRICS_PORT=free_port(), METRICS_ADDR=addr):
            server = metrics.serve()
        assert server is not None
        try:
            assert server.server_address[0] == addr
        finally:
            server.shutdown()
            server.server_close()


def test_port_zero_serves_nothing(root_handlers: None) -> None:
    with override_settings(METRICS_PORT=0):
        assert metrics.serve() is None


def test_gateway_latency_is_nan_until_the_first_heartbeat(root_handlers: None) -> None:
    gateway: Any = SimpleNamespace(latency=math.inf)
    with override_settings(METRICS_PORT=0):
        metrics.serve(gateway)
    assert math.isnan(sample("draftbot_gateway_latency_seconds"))
    gateway.latency = 0.042
    assert sample("draftbot_gateway_latency_seconds") == pytest.approx(0.042)


def test_error_logs_are_counted_by_logger(root_handlers: None) -> None:
    with override_settings(METRICS_PORT=0):
        metrics.serve()
    before = sample("draftbot_log_errors_total", logger="bot.routing")
    logging.getLogger("bot.routing").error("Interaction failed")
    logging.getLogger("bot.routing").warning("Not an error")
    assert sample("draftbot_log_errors_total", logger="bot.routing") == before + 1


def test_a_heartbeat_records_when_each_loop_went_round(tmp_path: Path) -> None:
    heartbeat = Heartbeat(tmp_path / "beat", ("effects",))
    heartbeat.beat("effects")
    assert time.time() - sample("draftbot_loop_heartbeat_timestamp_seconds", loop="effects") < 5


def test_a_loop_has_a_heartbeat_series_before_it_first_goes_round(tmp_path: Path) -> None:
    """Seeded with the start time, so BotHeartbeatStale fires for a loop that never started."""
    loop = f"never-{time.monotonic_ns()}"
    assert (
        metrics.REGISTRY.get_sample_value(
            "draftbot_loop_heartbeat_timestamp_seconds", {"loop": loop}
        )
        is None
    )
    Heartbeat(tmp_path / "beat", (loop,))
    assert time.time() - sample("draftbot_loop_heartbeat_timestamp_seconds", loop=loop) < 5
    assert not (tmp_path / "beat").exists()


def test_a_deadline_pass_is_timed_and_its_fired_deadlines_counted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    stop = asyncio.Event()

    def tick() -> int:
        stop.set()
        return 2

    monkeypatch.setattr(client_module.deadlines, "tick", tick)
    passes = sample("draftbot_deadline_tick_duration_seconds_count")
    fired = sample("draftbot_deadlines_fired_total")
    asyncio.run(
        asyncio.wait_for(deadline_loop(Heartbeat(tmp_path / "b", ("deadlines",)), stop=stop), 10)
    )
    assert sample("draftbot_deadline_tick_duration_seconds_count") == passes + 1
    assert sample("draftbot_deadlines_fired_total") == fired + 2
    beat = sample("draftbot_loop_heartbeat_timestamp_seconds", loop="deadlines")
    assert time.time() - beat < 5


def _run(monkeypatch: pytest.MonkeyPatch, kind: str, behaviour: Any, retry_to: str) -> None:
    async def handler(env: Any) -> None:
        behaviour()

    monkeypatch.setitem(worker_module.HANDLERS, kind, handler)
    for name in ("mark_started", "mark_done", "mark_failed"):
        monkeypatch.setattr(worker_module.effects, name, lambda *_: True)
    monkeypatch.setattr(worker_module.effects, "mark_retry", lambda *_: retry_to)
    effect = SimpleNamespace(
        pk=1, match_id=None, kind=kind, lane="", community_id=1, community=None, match=None
    )
    worker = worker_module.EffectWorker(gateway=None)  # type: ignore[arg-type]
    asyncio.run(worker._run_effect(effect))  # type: ignore[arg-type]


def _raise() -> None:
    raise RuntimeError("Discord is having a moment")


def _skip() -> None:
    raise worker_module.Skip("nothing to do")


@pytest.mark.parametrize(
    ("behaviour", "retry_to", "outcome"),
    [
        (lambda: None, "pending", "done"),
        (_skip, "pending", "skipped"),
        (_raise, "pending", "retried"),
        (_raise, "failed", "failed"),
    ],
)
def test_effects_are_counted_by_kind_and_outcome(
    monkeypatch: pytest.MonkeyPatch, behaviour: Any, retry_to: str, outcome: str
) -> None:
    before = sample("draftbot_effects_total", kind="metric_probe", outcome=outcome)
    runs = sample("draftbot_effect_duration_seconds_count")
    _run(monkeypatch, "metric_probe", behaviour, retry_to)
    assert sample("draftbot_effects_total", kind="metric_probe", outcome=outcome) == before + 1
    assert sample("draftbot_effect_duration_seconds_count") == runs + 1
