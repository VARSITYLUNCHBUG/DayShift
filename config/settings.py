"""Django settings. Everything environment-specific comes from env vars (see .env.example)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader for local runs. Real environment variables always win."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


# DJANGO_DOTENV names another file, or `off` for none (the test suite's settings subprocesses).
_dotenv = os.environ.get("DJANGO_DOTENV", "")
if _dotenv.lower() not in {"off", "0", "false", "no"}:
    _load_dotenv(Path(_dotenv) if _dotenv else BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


DEBUG = env_bool("DEBUG")

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if not DEBUG:
        raise RuntimeError("DJANGO_SECRET_KEY must be set when DEBUG is off.")
    SECRET_KEY = "dev-only-insecure-key"

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Django 6 refuses ArrayField without it (postgres.E005).
    "django.contrib.postgres",
    "league",
]

MIDDLEWARE = [
    # /healthz and /readyz, before ALLOWED_HOSTS and the HTTPS redirect (config.health).
    "config.health.health_middleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "config.csp.csp_middleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# One Postgres login for everything. A handful of connections at most: the bot keeps one (all its
# database work runs on one thread, league.asyncdb), and web opens one per request in flight.
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgres://dayshift:change-me@127.0.0.1:55432/dayshift"
)
# Seconds a connection is kept for reuse. The bot keeps its own. The web process wants 0, which
# compose.yaml sets: under ASGI each request's synchronous work runs on a thread of its own, and a
# connection kept after the request would be stranded with that thread.
DB_CONN_MAX_AGE = int(os.environ.get("DB_CONN_MAX_AGE") or 60)
DATABASES: dict[str, Any] = {
    "default": dj_database_url.parse(
        DATABASE_URL, conn_max_age=DB_CONN_MAX_AGE, conn_health_checks=True
    ),
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LANGUAGE_CODE = "en-gb"
# Our date formats, which label every time UTC (config/formats/en_GB/formats.py).
FORMAT_MODULE_PATH = ["config.formats"]
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# web serves the static files itself, through WhiteNoise. collectstatic (in the image build)
# writes each file under a content hash, which WhiteNoise lets browsers cache for good, and a .gz
# copy it serves as is. Pages link the hashed names from its manifest; with DEBUG on, the plain
# ones. The test suite runs no collectstatic, so it has no manifest and links plain names.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        if "pytest" in sys.modules
        else "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}

# What pages may load (config.csp). Only this origin, nothing inline except with the response's
# nonce ("'nonce'"), never framed. Extend a directive here for a new source.
CONTENT_SECURITY_POLICY: dict[str, list[str]] = {
    "default-src": ["'self'"],
    "script-src": ["'self'", "'nonce'"],
    "style-src": ["'self'", "'nonce'"],
    "img-src": ["'self'", "data:"],
    "font-src": ["'self'"],
    "connect-src": ["'self'"],
    "object-src": ["'none'"],
    "base-uri": ["'none'"],
    "form-action": ["'self'"],
    "frame-ancestors": ["'none'"],
}

# Every player is a user: the bot makes one per Discord account, and admin logins are players too.
AUTH_USER_MODEL = "league.Player"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

if not DEBUG:
    SESSION_COOKIE_SECURE = env_bool("SECURE_COOKIES", True)
    CSRF_COOKIE_SECURE = env_bool("SECURE_COOKIES", True)
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"
    if env_bool("BEHIND_TLS_PROXY"):
        # The edge terminates TLS and says so in X-Forwarded-Proto. It also redirects to HTTPS
        # and sends HSTS itself; Django does both too, so they hold whatever proxy is in front.
        # The health and metrics probes answer before this redirect, over plain HTTP.
        SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
        SECURE_SSL_REDIRECT = True
        SECURE_HSTS_SECONDS = 63072000
        SECURE_HSTS_INCLUDE_SUBDOMAINS = True
        # Preloading is a commitment each operator makes for their own domain, not a default.
        SILENCED_SYSTEM_CHECKS = ["security.W021"]

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    # JSON lines, or plain text with LOG_FORMAT=text (config.logging).
    "formatters": {"default": {"()": "config.logging.formatter"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "default"}},
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        # Django's and uvicorn's own handlers would print a second, plain copy of their lines:
        # everything goes through the root handler above instead. The edge logs every request,
        # so uvicorn's access log is off.
        "django": {"handlers": []},
        "uvicorn": {"handlers": [], "propagate": True},
        "uvicorn.access": {"handlers": [], "propagate": False},
        "discord": {"level": "INFO"},
        "discord.http": {"level": "WARNING"},
        "django.db.backends": {"level": "WARNING"},
    },
}

# --- Bot ---------------------------------------------------------------------------------------
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN", "")
# A log line per Discord response, for load tests (devtools/loadtest_report.py). Noisy: leave off.
DISCORD_REQUEST_LOG = os.environ.get("DISCORD_REQUEST_LOG", "").lower() in {"1", "true", "yes"}
VOICE_CREATE_INTERVAL_SECONDS = max(
    0.0, float(os.environ.get("VOICE_CREATE_INTERVAL_SECONDS", "5"))
)
VOICE_ACTION_INTERVAL_SECONDS = max(
    0.0, float(os.environ.get("VOICE_ACTION_INTERVAL_SECONDS", "1"))
)
DISCORD_GUILD_ID = int(os.environ.get("DISCORD_GUILD_ID") or 0)
BOT_HEARTBEAT_FILE = Path(os.environ.get("BOT_HEARTBEAT_FILE", BASE_DIR / ".bot-heartbeat"))
DEADLOCK_API_BASE = os.environ.get("DEADLOCK_API_BASE", "https://api.deadlock-api.com")
# Where Discord's REST API and gateway are. Only a dev or test stack points them anywhere else
# (the Discord simulator). The bot token goes with every call, so that needs DEBUG on.
DISCORD_API_BASE = os.environ.get("DISCORD_API_BASE", "https://discord.com/api/v10").rstrip("/")
DISCORD_GATEWAY_URL = os.environ.get("DISCORD_GATEWAY_URL", "wss://gateway.discord.gg/")
if not DEBUG and (
    DISCORD_API_BASE != "https://discord.com/api/v10"
    or DISCORD_GATEWAY_URL != "wss://gateway.discord.gg/"
):
    raise RuntimeError("DISCORD_API_BASE and DISCORD_GATEWAY_URL only work with DEBUG on.")
# Optional. Raises deadlock-api's limits, such as lobby creation from 10 an hour to 100 per 30 min.
DEADLOCK_API_KEY = os.environ.get("DEADLOCK_API_KEY", "")
# Optional. The operator's channel: every error's full traceback, from every server, is posted
# there. Servers' own /seterrorchannel channels only ever get their own errors, summarised.
ERROR_LOG_CHANNEL_ID = int(os.environ.get("ERROR_LOG_CHANNEL_ID") or 0)
# Optional. Only needed to link Steam accounts by a custom profile URL (/id/name).
STEAM_WEB_API_KEY = os.environ.get("STEAM_WEB_API_KEY", "")

# --- Health ------------------------------------------------------------------------------------
# Optional. A dead man's switch (healthchecks.io or any service like it): the bot's watchdog pings
# it every minute, and pings URL/fail when the league isn't keeping up (league.services.health).
# A host that goes down stops the pings, which the service reports.
HEALTHCHECK_PING_URL = os.environ.get("HEALTHCHECK_PING_URL", "").strip()

# --- Local dev and simulator -------------------------------------------------------------------
# The dev control API (fake players, ratings, picks, phase control) under /_control/. Local only:
# it refuses to start without DEBUG.
DEV_CONTROL = env_bool("DEV_CONTROL")
if DEV_CONTROL and not DEBUG:
    raise RuntimeError("DEV_CONTROL only works with DEBUG on.")
if DEV_CONTROL:
    ROOT_URLCONF = "config.urls_dev"


def _checking() -> bool:
    """Under the test suite or the type checker, which cover devtools too."""
    import sys

    return "pytest" in sys.modules or "mypy" in sys.modules


# The app's models are needed to test and type-check it; its URLs only with DEV_CONTROL.
if DEV_CONTROL or _checking():
    INSTALLED_APPS += ["devtools"]
# The Discord simulator's control API, which the dev control API drives fake players through.
DISCORD_SIM_URL = os.environ.get("DISCORD_SIM_URL", "").rstrip("/")
if DISCORD_SIM_URL and not DEBUG:
    raise RuntimeError("DISCORD_SIM_URL only works with DEBUG on.")
# Against the simulator, lobbies come from its deadlock-api stand-in, never the real service.
if DISCORD_SIM_URL and "DEADLOCK_API_BASE" not in os.environ:
    DEADLOCK_API_BASE = f"{DISCORD_SIM_URL}/deadlock-api"
