"""The exporters' database role: created or updated by migrate, able to read statistics only."""

from __future__ import annotations

import base64
import hmac
import os
from collections.abc import Iterator

import psycopg
import pytest
from django.db import connection

from league.models import Community
from league.observability import monitoring_role

# Roles belong to the whole server, which parallel test workers share: one name per worker.
ROLE = f"draftbot_monitor_test_{os.getpid()}"


def login(password: str) -> psycopg.Connection:
    params = connection.get_connection_params()
    return psycopg.connect(
        host=params.get("host"),
        port=params.get("port"),
        dbname=params["dbname"],
        user=ROLE,
        password=password,
        connect_timeout=5,
    )


@pytest.fixture
def role() -> Iterator[str]:
    yield ROLE
    with connection.cursor() as cursor:
        cursor.execute(f"DROP ROLE IF EXISTS {ROLE}")


def test_the_verifier_signs_rfc_7677s_example_exchange() -> None:
    """With RFC 7677's password and salt, the ServerKey reproduces the RFC's server signature."""
    salt = "W22ZaJ0SNY7soEsUEjb6gQ=="
    verifier = monitoring_role.scram_verifier("pencil", salt=base64.b64decode(salt))
    head, keys = verifier.split("$", 1)[1].split("$")
    assert head == f"4096:{salt}"
    server_key = base64.b64decode(keys.split(":")[1])
    nonce = "rOprNGfwEbeRWgbNEkqO%hvYDpWUa2RaTCAfuxFIlj)hNlF$k0"
    auth_message = f"n=user,r=rOprNGfwEbeRWgbNEkqO,r={nonce},s={salt},i=4096,c=biws,r={nonce}"
    signature = hmac.new(server_key, auth_message.encode(), "sha256").digest()
    assert base64.b64encode(signature).decode() == "6rriTRBi23WpRR/wtup+mMhUZUn/dB5nLTJRsjl95G4="


@pytest.mark.django_db(transaction=True)
def test_ensure_creates_a_read_only_role_and_can_run_again(role: str) -> None:
    monitoring_role.ensure("first-password", role=role)
    # Again, as every migrate does, with a rotated password: the old one stops working.
    monitoring_role.ensure("second-password", role=role)

    with pytest.raises(psycopg.OperationalError):
        login("first-password").close()
    with login("second-password") as monitor, monitor.cursor() as cursor:
        cursor.execute(
            "SELECT rolsuper, rolcreaterole, rolcreatedb,"
            " pg_has_role(current_user, 'pg_monitor', 'MEMBER')"
            " FROM pg_roles WHERE rolname = current_user"
        )
        assert cursor.fetchone() == (False, False, False, True)
        # pg_monitor's statistics, such as every session's state...
        cursor.execute("SELECT count(*) FROM pg_stat_activity WHERE state IS NOT NULL")
        row = cursor.fetchone()
        assert row is not None and row[0] >= 1
        # ...but none of the app's tables.
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cursor.execute(f"SELECT * FROM {Community._meta.db_table}")


def test_main_without_a_password_changes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """No `db` fixture: a query here would fail the test."""
    monkeypatch.delenv("DB_MONITOR_PASSWORD", raising=False)
    monitoring_role.main()


def test_only_plain_role_names_are_accepted() -> None:
    with pytest.raises(ValueError, match="plain role name"):
        monitoring_role.ensure("x", role="draftbot; DROP TABLE x")
