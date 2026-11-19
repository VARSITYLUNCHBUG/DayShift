"""The web process under ASGI, and its probes: /healthz (serving) and /readyz (the database
answers)."""

from __future__ import annotations

import asyncio
import json

import pytest
from django.db import OperationalError, connections
from django.test import AsyncClient, Client, override_settings

import bot.db
import config.health
import league.asyncdb
from league.asyncdb import db


def asgi_get(path: str, host: str = "localhost") -> tuple[int, bytes]:
    """GET through Django's ASGI handler, as uvicorn serves it."""

    async def go() -> tuple[int, bytes]:
        response = await AsyncClient(headers={"host": host}).get(path)
        await db(connections.close_all)
        return response.status_code, response.content

    return asyncio.run(go())


class Unreachable:
    """A connection whose every query fails, as when Postgres is down."""

    def cursor(self) -> None:
        raise OperationalError("connection refused")


def test_healthz_never_touches_the_database() -> None:
    # No django_db mark: any query here would fail the test.
    status, body = asgi_get("/healthz")
    assert status == 200
    assert json.loads(body) == {"status": "ok"}


@pytest.mark.django_db(transaction=True)
def test_readyz_answers_when_the_database_does() -> None:
    status, body = asgi_get("/readyz")
    assert status == 200
    assert json.loads(body) == {"status": "ok"}


def test_readyz_fails_when_the_database_does_not(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config.health, "connection", Unreachable())
    status, body = asgi_get("/readyz")
    assert status == 503
    assert json.loads(body) == {"status": "unavailable"}
    assert Client().get("/readyz").status_code == 503


@pytest.mark.django_db(transaction=True)
@override_settings(ALLOWED_HOSTS=["draft.example.com"], SECURE_SSL_REDIRECT=True)
def test_probes_answer_whatever_the_host_and_scheme() -> None:
    # A container healthcheck asks 127.0.0.1 over plain HTTP; the public host is the domain.
    assert asgi_get("/readyz", host="127.0.0.1:8000")[0] == 200
    assert asgi_get("/healthz", host="127.0.0.1:8000")[0] == 200
    assert Client().get("/readyz", HTTP_HOST="127.0.0.1:8000").status_code == 200
    # Everything else still goes through ALLOWED_HOSTS.
    assert Client().get("/admin/login/", HTTP_HOST="127.0.0.1:8000").status_code == 400


@pytest.mark.django_db
def test_asgi_serves_the_admin_login() -> None:
    status, body = asgi_get("/admin/login/")
    assert status == 200
    assert b"Django" in body


def test_the_bot_and_the_web_share_one_db_boundary() -> None:
    assert bot.db.db is league.asyncdb.db
    assert asyncio.run(db(sum, [1, 2, 3])) == 6
