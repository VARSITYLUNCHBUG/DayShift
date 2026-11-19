"""The settings module's own rules: startup guards, the dev block and the production checks.

Settings are read once at import, so each test loads `config/settings.py` again into a fresh
module, in this process, with only the environment variables it names. No subprocess, no .env.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import ModuleType
from unittest import mock

import pytest
from django.core import checks
from django.test import override_settings

SETTINGS = Path(__file__).resolve().parent.parent / "config" / "settings.py"
SIM = "http://discord-sim:8090"

# What a production .env sets (deploy/), with a secret Django's deploy check accepts.
PRODUCTION = {
    "DEBUG": "false",
    "DJANGO_SECRET_KEY": "p" * 20 + "9fQ2xLmT4vRb7NcK1sWd8HjZ3yUe6Ga5",
    "ALLOWED_HOSTS": "draft.example.com",
    "CSRF_TRUSTED_ORIGINS": "https://draft.example.com",
    "BEHIND_TLS_PROXY": "true",
    "SECURE_COOKIES": "true",
    "DATABASE_URL": "postgres://draftbot:secret@db:5432/draftbot",
}


def load(**env: str) -> ModuleType:
    """`config.settings` as these environment variables (and nothing else) would make it."""
    spec = importlib.util.spec_from_file_location("settings_under_test", SETTINGS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    environ = {"DJANGO_SECRET_KEY": "test", "DJANGO_DOTENV": "off", **env}
    with mock.patch.dict(os.environ, environ, clear=True):
        spec.loader.exec_module(module)
    return module


def test_connections_are_kept_unless_db_conn_max_age_says_otherwise() -> None:
    """compose.yaml gives web 0: under ASGI each request's sync work has a thread of its own."""
    assert load(DEBUG="true").DATABASES["default"]["CONN_MAX_AGE"] == 60
    assert load(DEBUG="true", DB_CONN_MAX_AGE="0").DATABASES["default"]["CONN_MAX_AGE"] == 0


def test_one_database_from_database_url() -> None:
    databases = load(**PRODUCTION).DATABASES
    assert list(databases) == ["default"]
    assert (databases["default"]["HOST"], databases["default"]["PORT"]) == ("db", 5432)


def test_a_secret_key_is_required_outside_debug() -> None:
    with pytest.raises(RuntimeError, match="DJANGO_SECRET_KEY"):
        load(DEBUG="false", DJANGO_SECRET_KEY="")
    assert load(DEBUG="true", DJANGO_SECRET_KEY="").SECRET_KEY == "dev-only-insecure-key"


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("DISCORD_API_BASE", f"{SIM}/api/v10"),
        ("DISCORD_GATEWAY_URL", "ws://discord-sim:8090/gateway"),
        ("DEV_CONTROL", "true"),
        ("DISCORD_SIM_URL", SIM),
    ],
)
def test_dev_and_stand_in_settings_need_debug(name: str, value: str) -> None:
    with pytest.raises(RuntimeError, match=r"only works? with DEBUG on"):
        load(DEBUG="false", **{name: value})
    load(DEBUG="true", **{name: value})


def test_real_discord_needs_no_debug() -> None:
    load(
        DEBUG="false",
        DISCORD_API_BASE="https://discord.com/api/v10/",
        DISCORD_GATEWAY_URL="wss://gateway.discord.gg/",
    )


def test_the_control_api_is_routed_only_with_dev_control() -> None:
    assert load(DEBUG="true").ROOT_URLCONF == "config.urls"
    assert load(DEBUG="true", DEV_CONTROL="true").ROOT_URLCONF == "config.urls_dev"


def test_against_the_simulator_lobbies_come_from_its_stand_in() -> None:
    assert load(DEBUG="false").DEADLOCK_API_BASE == "https://api.deadlock-api.com"
    assert load(DEBUG="true", DISCORD_SIM_URL=SIM + "/").DEADLOCK_API_BASE == SIM + "/deadlock-api"
    # One set on purpose is kept, the real service included.
    real = "https://api.deadlock-api.com"
    assert real == load(DEBUG="true", DISCORD_SIM_URL=SIM, DEADLOCK_API_BASE=real).DEADLOCK_API_BASE


def test_dotenv_can_be_pointed_elsewhere(tmp_path: Path) -> None:
    dotenv = tmp_path / "other.env"
    dotenv.write_text("HEALTHCHECK_PING_URL='https://ping.example.com/abc'\n", encoding="utf-8")
    assert load(DEBUG="true", DJANGO_DOTENV=str(dotenv)).HEALTHCHECK_PING_URL == (
        "https://ping.example.com/abc"
    )
    assert load(DEBUG="true").HEALTHCHECK_PING_URL == ""


# Everything Django's deployment checks read. INSTALLED_APPS and DATABASES stay as they are:
# overriding those would rebuild the app registry.
SECURITY = (
    "DEBUG",
    "SECRET_KEY",
    "ALLOWED_HOSTS",
    "MIDDLEWARE",
    "SESSION_COOKIE_SECURE",
    "CSRF_COOKIE_SECURE",
    "SECURE_CONTENT_TYPE_NOSNIFF",
    "SECURE_PROXY_SSL_HEADER",
    "SECURE_SSL_REDIRECT",
    "SECURE_HSTS_SECONDS",
    "SECURE_HSTS_INCLUDE_SUBDOMAINS",
    "X_FRAME_OPTIONS",
    "SILENCED_SYSTEM_CHECKS",
)


def test_the_production_settings_pass_the_deploy_checks() -> None:
    production = load(**PRODUCTION)
    values = {name: getattr(production, name) for name in SECURITY if hasattr(production, name)}
    with override_settings(**values):
        found = checks.run_checks(include_deployment_checks=True, tags=[checks.Tags.security])
        # Silencing reads the settings, so it is checked inside the override.
        loud = [c for c in found if c.level >= checks.WARNING and not c.is_silenced()]
    assert loud == []
