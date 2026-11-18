"""Settings the platform depends on: pgbouncer mode, startup guards, log format, deploy checks.

Each test imports the settings in a fresh interpreter, because they are read once at import.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# What a production .env sets (deploy/), with a secret Django's deploy check accepts.
PRODUCTION = {
    "DEBUG": "false",
    "DJANGO_SECRET_KEY": "p" * 20 + "9fQ2xLmT4vRb7NcK1sWd8HjZ3yUe6Ga5",
    "ALLOWED_HOSTS": "draft.example.com",
    "CSRF_TRUSTED_ORIGINS": "https://draft.example.com",
    "PUBLIC_URL": "https://draft.example.com",
    "BEHIND_TLS_PROXY": "true",
    "SECURE_COOKIES": "true",
    "DB_PGBOUNCER": "true",
    "DATABASE_URL": "postgres://draftbot_app:secret@pgbouncer:6432/draftbot",
    "DATABASE_DIRECT_URL": "postgres://draftbot_app:secret@db:5432/draftbot",
}
# Variables a developer's shell or the test runner may have set, which would change the result.
CLEARED = (
    "DEBUG",
    "DB_POOL",
    "DB_PGBOUNCER",
    "DATABASE_DIRECT_URL",
    "DEV_CONTROL",
    "WEB_DEV_LOGIN",
    "DISCORD_API_BASE",
    "DISCORD_GATEWAY_URL",
    "DISCORD_SIM_URL",
    "BEHIND_TLS_PROXY",
    "LOG_FORMAT",
    "DB_CONN_MAX_AGE",
    "METRICS_ADDR",
)


def run(code: str, **env: str) -> subprocess.CompletedProcess[str]:
    """Run `code` in a fresh interpreter in the repo, with these environment variables and
    without the developer's .env (DJANGO_DOTENV=off)."""
    base = {key: value for key, value in os.environ.items() if key not in CLEARED}
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env={**base, "DJANGO_SECRET_KEY": "test", "DJANGO_DOTENV": "off", **env},
        capture_output=True,
        text=True,
        check=False,
    )


def database(**env: str) -> dict[str, object]:
    code = (
        "import json, config.settings as s; d = s.DATABASES['default']; "
        "print(json.dumps({'cursors': d.get('DISABLE_SERVER_SIDE_CURSORS', False), "
        "'age': d['CONN_MAX_AGE'], 'checks': d['CONN_HEALTH_CHECKS'], "
        "'options': d.get('OPTIONS', {}), 'direct': s.DATABASE_DIRECT_URL}))"
    )
    result = run(code, **env)
    assert result.returncode == 0, result.stderr
    loaded: dict[str, object] = json.loads(result.stdout)
    return loaded


def test_behind_pgbouncer_nothing_outlives_a_transaction() -> None:
    url = "postgres://draftbot:x@pgbouncer:6432/draftbot"
    assert database(DB_PGBOUNCER="true", DATABASE_URL=url) == {
        "cursors": True,
        "age": 60,
        "checks": True,
        # No psycopg pool on top of pgbouncer, and no server-side binding.
        "options": {},
        "direct": url,
    }


def test_connections_are_kept_unless_db_conn_max_age_says_otherwise() -> None:
    """compose.yaml gives web 0: under ASGI each request's sync work has a thread of its own."""
    assert database(DEBUG="true")["age"] == 60
    assert database(DEBUG="true", DB_CONN_MAX_AGE="0")["age"] == 0


def test_the_direct_url_is_used_as_given() -> None:
    direct = "postgres://draftbot:x@db:5432/draftbot"
    assert database(DATABASE_DIRECT_URL=direct)["direct"] == direct


def test_two_poolers_are_refused() -> None:
    result = run("import config.settings", DB_PGBOUNCER="true", DB_POOL="true")
    assert result.returncode != 0
    assert "DB_POOL and DB_PGBOUNCER" in result.stderr


def test_a_stand_in_discord_is_refused_outside_debug() -> None:
    for name, value in (
        ("DISCORD_API_BASE", "http://discord-sim:8090/api/v10"),
        ("DISCORD_GATEWAY_URL", "ws://discord-sim:8090/gateway"),
    ):
        refused = run("import config.settings", DEBUG="false", **{name: value})
        assert refused.returncode != 0, name
        assert "only work with DEBUG on" in refused.stderr
        assert run("import config.settings", DEBUG="true", **{name: value}).returncode == 0


def test_real_discord_needs_no_debug() -> None:
    result = run(
        "import config.settings",
        DEBUG="false",
        DISCORD_API_BASE="https://discord.com/api/v10/",
        DISCORD_GATEWAY_URL="wss://gateway.discord.gg/",
    )
    assert result.returncode == 0, result.stderr


def test_the_direct_alias_skips_pgbouncer_and_gets_nothing_routed_to_it() -> None:
    """A LISTEN listener reads connections["direct"]: the db service itself, as a session of
    its own, while every model stays on `default`."""
    code = (
        "import json, django; django.setup(); from django.conf import settings; "
        "from django.db import router; from league.models import Community; "
        "d = settings.DATABASES; "
        "print(json.dumps({'hosts': [d['default']['HOST'], d['direct']['HOST']], "
        "'ports': [d['default']['PORT'], d['direct']['PORT']], "
        "'cursors': d['direct'].get('DISABLE_SERVER_SIDE_CURSORS', False), "
        "'mirror': d['direct']['TEST'].get('MIRROR'), "
        "'read': router.db_for_read(Community), 'write': router.db_for_write(Community), "
        "'migrate': router.allow_migrate('direct', 'league')}))"
    )
    result = run(code, **PRODUCTION)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "hosts": ["pgbouncer", "db"],
        "ports": [6432, 5432],
        "cursors": False,
        "mirror": "default",
        "read": "default",
        "write": "default",
        "migrate": False,
    }


def test_dotenv_can_be_turned_off_or_pointed_elsewhere(tmp_path: Path) -> None:
    dotenv = tmp_path / "other.env"
    dotenv.write_text("DRAFTBOT_DOTENV_PROBE=from-the-file\n", encoding="utf-8")
    code = "import os, config.settings; print(os.environ.get('DRAFTBOT_DOTENV_PROBE'))"
    pointed = run(code, DEBUG="true", DJANGO_DOTENV=str(dotenv))
    assert pointed.stdout.strip() == "from-the-file", pointed.stderr
    off = run(code, DEBUG="true")
    assert off.stdout.strip() == "None", off.stderr


def test_the_production_settings_pass_the_deploy_checks() -> None:
    code = (
        "import sys; from django.core.management import execute_from_command_line; "
        "execute_from_command_line(['manage.py', 'check', '--deploy', '--fail-level', 'WARNING'])"
    )
    result = run(code, DJANGO_SETTINGS_MODULE="config.settings", **PRODUCTION)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "no issues" in result.stdout
