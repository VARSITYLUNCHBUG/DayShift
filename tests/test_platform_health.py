"""The web process's probes: /healthz (serving) and /readyz (and the database answers)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from channels.testing import HttpCommunicator
from django.db import OperationalError, connections
from django.test import Client, override_settings

import config.asgi
import config.health
from league.asyncdb import db


def asgi_get(path: str, host: bytes = b"localhost") -> dict[str, Any]:
    async def go() -> dict[str, Any]:
        communicator = HttpCommunicator(
            config.asgi.application, "GET", path, headers=[(b"host", host)]
        )
        response: dict[str, Any] = await communicator.get_response(timeout=10)
        await db(connections.close_all)
        return response

    return asyncio.run(go())


class Unreachable:
    """A connection whose every query fails, as when pgbouncer or Postgres is down."""

    def cursor(self) -> None:
        raise OperationalError("connection refused")


def test_healthz_never_touches_the_database() -> None:
    # No django_db mark: any query here would fail the test.
    response = asgi_get("/healthz")
    assert response["status"] == 200
    assert json.loads(response["body"]) == {"status": "ok"}


@pytest.mark.django_db(transaction=True)
def test_readyz_answers_when_the_database_does() -> None:
    response = asgi_get("/readyz")
    assert response["status"] == 200
    assert json.loads(response["body"]) == {"status": "ok"}


def test_readyz_fails_when_the_database_does_not(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config.health, "connection", Unreachable())
    response = asgi_get("/readyz")
    assert response["status"] == 503
    assert json.loads(response["body"]) == {"status": "unavailable"}
    assert Client().get("/readyz").status_code == 503


@pytest.mark.django_db(transaction=True)
@override_settings(ALLOWED_HOSTS=["draft.example.com"], SECURE_SSL_REDIRECT=True)
def test_probes_answer_whatever_the_host_and_scheme() -> None:
    # A container healthcheck asks 127.0.0.1 over plain HTTP; the public host is the domain.
    assert asgi_get("/readyz", host=b"127.0.0.1:8000")["status"] == 200
    assert asgi_get("/healthz", host=b"127.0.0.1:8000")["status"] == 200
    assert Client().get("/readyz", HTTP_HOST="127.0.0.1:8000").status_code == 200
    # Everything else still goes through ALLOWED_HOSTS.
    assert Client().get("/admin/login/", HTTP_HOST="127.0.0.1:8000").status_code == 400
