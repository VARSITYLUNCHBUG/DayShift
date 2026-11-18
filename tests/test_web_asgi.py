"""The web process under ASGI, and the settings it adds."""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from channels.testing import HttpCommunicator
from django.core.exceptions import ImproperlyConfigured
from django.db import connections
from django.test import override_settings

import bot.db
import config.asgi
import league.asyncdb
from league.asyncdb import db

ROOT = Path(__file__).resolve().parent.parent


def _get(path: str) -> dict[str, Any]:
    async def go() -> dict[str, Any]:
        communicator = HttpCommunicator(
            config.asgi.application, "GET", path, headers=[(b"host", b"localhost")]
        )
        response: dict[str, Any] = await communicator.get_response(timeout=10)
        await db(connections.close_all)
        return response

    return asyncio.run(go())


@pytest.mark.django_db(transaction=True)
def test_asgi_serves_the_health_check() -> None:
    response = _get("/healthz")
    assert response["status"] == 200
    assert json.loads(response["body"]) == {"status": "ok"}


@pytest.mark.django_db(transaction=True)
def test_asgi_serves_the_admin_login() -> None:
    response = _get("/admin/login/")
    assert response["status"] == 200
    assert b"Django" in response["body"]


def test_the_web_process_refuses_wildcard_hosts() -> None:
    try:
        with (
            override_settings(DEBUG=False, ALLOWED_HOSTS=["*"]),
            pytest.raises(ImproperlyConfigured, match="ALLOWED_HOSTS"),
        ):
            importlib.reload(config.asgi)
    finally:
        importlib.reload(config.asgi)


def _settings(**env: str) -> subprocess.CompletedProcess[str]:
    """Import the settings in a fresh interpreter, with these environment variables."""
    code = (
        "import json, config.settings as s; "
        "d = s.DATABASES['default']; "
        "print(json.dumps({'age': d['CONN_MAX_AGE'], 'pool': d.get('OPTIONS', {}).get('pool')}))"
    )
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env={**os.environ, "DJANGO_SECRET_KEY": "test", **env},
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_web_process_pools_connections_when_asked() -> None:
    result = _settings(DB_POOL="true", WEB_DB_THREADS="3")
    assert result.returncode == 0, result.stderr
    database = json.loads(result.stdout)
    assert database["age"] == 0
    assert database["pool"]["max_size"] == 5


def test_the_bot_keeps_its_long_lived_connection() -> None:
    result = _settings(DB_POOL="false")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"age": 60, "pool": None}


def test_dev_login_is_refused_outside_debug() -> None:
    result = _settings(DEBUG="false", WEB_DEV_LOGIN="true")
    assert result.returncode != 0
    assert "WEB_DEV_LOGIN" in result.stderr


def test_the_bot_and_the_web_share_one_db_boundary() -> None:
    assert bot.db.db is league.asyncdb.db
    assert asyncio.run(db(sum, [1, 2, 3])) == 6
