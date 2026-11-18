"""The database roles migrate sets up, through the entry points compose runs:
draftbot_app (config.app_role), which the app logs in as, and draftbot_monitor."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from django.db import connection

from league.models import Community

ROOT = Path(__file__).resolve().parent.parent
# Roles belong to the whole server, which parallel test workers share: one name per worker.
APP_ROLE = f"draftbot_app_test_{os.getpid()}"
MONITOR_ROLE = f"draftbot_monitor_main_{os.getpid()}"


def login(role: str, password: str) -> psycopg.Connection:
    params = connection.get_connection_params()
    return psycopg.connect(
        host=params.get("host"),
        port=params.get("port"),
        dbname=params["dbname"],
        user=role,
        password=password,
        connect_timeout=5,
        autocommit=True,
    )


def run_module(module: str, **env: str) -> subprocess.CompletedProcess[str]:
    """`python -m module`, as migrate runs it, against this worker's test database."""
    settings = connection.settings_dict
    url = (
        f"postgres://{settings['USER']}:{settings['PASSWORD']}@{settings['HOST'] or '127.0.0.1'}"
        f":{settings['PORT'] or 5432}/{settings['NAME']}"
    )
    cleared = {"DB_APP_PASSWORD", "DB_MONITOR_PASSWORD", "DB_PGBOUNCER", "DEV_CONTROL", "DEBUG"}
    base = {key: value for key, value in os.environ.items() if key not in cleared}
    return subprocess.run(
        [sys.executable, "-m", module],
        cwd=ROOT,
        env={
            **base,
            "DATABASE_URL": url,
            "DJANGO_SECRET_KEY": "test",
            "DJANGO_DOTENV": "off",
            **env,
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


def drop(role: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT 1 FROM pg_roles WHERE rolname = '{role}'")
        if cursor.fetchone():
            cursor.execute(f"DROP OWNED BY {role}")
            cursor.execute(f"DROP ROLE {role}")


@pytest.fixture
def app_role() -> Iterator[str]:
    yield APP_ROLE
    drop(APP_ROLE)


@pytest.fixture
def monitor_role() -> Iterator[str]:
    yield MONITOR_ROLE
    drop(MONITOR_ROLE)


@pytest.mark.django_db(transaction=True)
def test_migrates_app_role_reads_and_writes_tables_and_nothing_more(app_role: str) -> None:
    first = run_module("config.app_role", DB_APP_PASSWORD="first-password", DB_APP_ROLE=app_role)
    assert first.returncode == 0, first.stderr
    # Again, as every migrate does, with a rotated password: the old one stops working.
    second = run_module("config.app_role", DB_APP_PASSWORD="second-password", DB_APP_ROLE=app_role)
    assert second.returncode == 0, second.stderr
    assert "The app's role is ready" in second.stderr
    with pytest.raises(psycopg.OperationalError):
        login(app_role, "first-password").close()

    # A table a later migration creates, as the superuser that runs them.
    with connection.cursor() as cursor:
        cursor.execute("CREATE TABLE app_role_later (id bigserial PRIMARY KEY, note text)")
    table = Community._meta.db_table
    with login(app_role, "second-password") as app, app.cursor() as cursor:
        cursor.execute(
            "SELECT rolsuper, rolcreaterole, rolcreatedb FROM pg_roles WHERE rolname = current_user"
        )
        assert cursor.fetchone() == (False, False, False)
        cursor.execute(f"SELECT count(*) FROM {table}")
        cursor.execute("INSERT INTO app_role_later (note) VALUES ('x') RETURNING id")
        cursor.execute("UPDATE app_role_later SET note = 'y'")
        cursor.execute("DELETE FROM app_role_later")
        for statement in (
            "CREATE TABLE app_role_own (id int)",
            f"DROP TABLE {table}",
            f"ALTER TABLE {table} ADD COLUMN x int",
            "COPY (SELECT 1) TO PROGRAM 'id'",
            f"CREATE ROLE {app_role}_child",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cursor.execute(statement)
    with connection.cursor() as cursor:
        cursor.execute("DROP TABLE app_role_later")


def test_app_role_main_without_a_password_changes_nothing() -> None:
    """No `db` fixture: a query here would fail the test."""
    from config import app_role

    saved = os.environ.pop("DB_APP_PASSWORD", None)
    try:
        app_role.main()
    finally:
        if saved is not None:
            os.environ["DB_APP_PASSWORD"] = saved


def test_only_plain_role_names_are_accepted() -> None:
    from config import app_role

    with pytest.raises(ValueError, match="plain role name"):
        app_role.ensure("x", role="draftbot; DROP TABLE x")


@pytest.mark.django_db(transaction=True)
def test_the_monitoring_roles_entry_point_creates_a_role_that_logs_in(monitor_role: str) -> None:
    """What migrate and the deploy's rotation run, end to end."""
    result = run_module(
        "league.observability.monitoring_role",
        DB_MONITOR_PASSWORD="monitor-password",
        DB_MONITOR_ROLE=monitor_role,
    )
    assert result.returncode == 0, result.stderr
    assert "The monitoring role is ready" in result.stderr
    with login(monitor_role, "monitor-password") as monitor, monitor.cursor() as cursor:
        cursor.execute("SELECT pg_has_role(current_user, 'pg_monitor', 'MEMBER')")
        assert cursor.fetchone() == (True,)
