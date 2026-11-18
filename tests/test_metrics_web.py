"""The web process's metrics: requests by route, and /metrics for Prometheus but not the public."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from channels.testing import HttpCommunicator
from django.db import connections
from django.test import Client

import config.asgi
from league.asyncdb import db
from league.observability.metrics import REGISTRY


def requests(method: str, route: str, status: str) -> float:
    labels = {"method": method, "route": route, "status": status}
    return REGISTRY.get_sample_value("draftbot_http_requests_total", labels) or 0.0


def routes() -> set[str]:
    return {
        sample.labels["route"]
        for family in REGISTRY.collect()
        if family.name == "draftbot_http_requests"
        for sample in family.samples
    }


@pytest.mark.django_db
def test_requests_are_counted_and_timed_by_route() -> None:
    before = requests("GET", "/healthz", "200")
    assert Client().get("/healthz").status_code == 200
    assert requests("GET", "/healthz", "200") == before + 1
    count = REGISTRY.get_sample_value(
        "draftbot_http_request_duration_seconds_count", {"method": "GET", "route": "/healthz"}
    )
    assert count is not None and count >= 1


@pytest.mark.django_db
def test_the_route_is_the_url_pattern_never_the_path() -> None:
    """An ID in the path would make a new series per object."""
    response = Client().get("/admin/league/player/12345/change/")
    assert response.status_code == 302  # To the login page.
    assert "/admin/league/player/<path:object_id>/change/" in routes()
    assert not [route for route in routes() if "12345" in route]


def test_unknown_paths_and_odd_methods_share_one_series() -> None:
    before = requests("other", "unmatched", "404")
    response = Client().generic("BREW", "/no-such-page-at-all/")
    assert response.status_code == 404
    assert requests("other", "unmatched", "404") == before + 1
    assert "/no-such-page-at-all/" not in routes()


@pytest.mark.django_db
def test_metrics_answer_prometheus_by_service_name() -> None:
    """Prometheus scrapes web:8000, a host ALLOWED_HOSTS never lists."""
    response = Client(HTTP_HOST="web:8000").get("/metrics")
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/plain")
    body = response.content.decode()
    for name in ("draftbot_http_requests_total", "draftbot_queue_players", "python_info"):
        assert name in body
    assert "draftbot_league_metrics_up 1.0" in body


def test_metrics_are_refused_through_the_edge_proxy() -> None:
    assert Client(HTTP_X_FORWARDED_FOR="203.0.113.9").get("/metrics").status_code == 404
    assert Client().post("/metrics").status_code == 404


def _asgi_get(path: str, host: bytes) -> dict[str, Any]:
    async def go() -> dict[str, Any]:
        communicator = HttpCommunicator(
            config.asgi.application, "GET", path, headers=[(b"host", host)]
        )
        response: dict[str, Any] = await communicator.get_response(timeout=10)
        await db(connections.close_all)
        return response

    return asyncio.run(go())


@pytest.mark.django_db(transaction=True)
def test_under_asgi_requests_are_counted_and_metrics_read_the_database() -> None:
    before = requests("GET", "/healthz", "200")
    assert _asgi_get("/healthz", b"localhost")["status"] == 200
    assert requests("GET", "/healthz", "200") == before + 1

    response = _asgi_get("/metrics", b"web:8000")
    assert response["status"] == 200
    assert b"draftbot_league_metrics_up 1.0" in response["body"]
