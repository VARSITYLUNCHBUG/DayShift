"""Steam sign-in over OpenID 2.0, the only sign-in Steam offers.

Steam's answer comes back through the player's browser, so every part of it is checked before
it's believed: it must be for the request we started (state and return_to), from Steam's
endpoint, about one identity (claimed_id == identity), signed over every field we read, fresh
and never seen before (the nonce), and Steam itself must confirm the signature
(`check_authentication`). Only then is the SteamID in `claimed_id` the player's.

Used nonces are remembered in Django's cache. The web runs as one process (uvicorn with one
worker) and the default cache is per process, which is enough; more web processes would need a
shared cache here.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

OP_ENDPOINT = "https://steamcommunity.com/openid/login"
NS = "http://specs.openid.net/auth/2.0"
IDENTIFIER_SELECT = "http://specs.openid.net/auth/2.0/identifier_select"
CLAIMED_ID = re.compile(r"^https://steamcommunity\.com/openid/id/(\d{17})$")
CALLBACK_PATH = "/auth/steam/callback/"
SIGNED_FIELDS = (
    "op_endpoint",
    "claimed_id",
    "identity",
    "return_to",
    "response_nonce",
    "assoc_handle",
)
NONCE_MAX_AGE = timedelta(minutes=5)
# Longer than a nonce stays fresh, so a remembered one is never forgotten while it could pass.
NONCE_MEMORY_SECONDS = 600
TIMEOUT = httpx.Timeout(10.0)
PERSONA_TIMEOUT = httpx.Timeout(3.0)
SUMMARIES_URL = "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/"

logger = logging.getLogger("league.web.auth")


class Cancelled(Exception):
    """The player backed out on Steam."""


class Invalid(Exception):
    """Steam's answer didn't check out. The message is for the log."""


class Unreachable(Exception):
    """Steam didn't answer the signature check."""


def return_to(state: str) -> str:
    return f"{settings.PUBLIC_URL}{CALLBACK_PATH}?{urlencode({'state': state})}"


def login_url(return_to_url: str) -> str:
    query = {
        "openid.ns": NS,
        "openid.mode": "checkid_setup",
        "openid.return_to": return_to_url,
        "openid.realm": settings.PUBLIC_URL,
        "openid.identity": IDENTIFIER_SELECT,
        "openid.claimed_id": IDENTIFIER_SELECT,
    }
    return f"{OP_ENDPOINT}?{urlencode(query)}"


def _client() -> httpx.Client:
    """Its own function so tests can stand in for Steam."""
    return httpx.Client(timeout=TIMEOUT)


def _nonce_time(nonce: str) -> datetime:
    try:
        return datetime.strptime(nonce[:20], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise Invalid("response_nonce has no timestamp") from exc


def verify(params: Mapping[str, str], expected_return_to: str) -> int:
    """The SteamID64 Steam vouches for, from the callback's query parameters."""
    mode = params.get("openid.mode", "")
    if mode == "cancel":
        raise Cancelled
    if params.get("openid.ns") != NS:
        raise Invalid("wrong openid.ns")
    if mode != "id_res":
        raise Invalid(f"openid.mode is {mode[:20]!r}")
    if params.get("openid.op_endpoint") != OP_ENDPOINT:
        raise Invalid("wrong op_endpoint")
    if params.get("openid.return_to") != expected_return_to:
        raise Invalid("return_to doesn't match the request")
    claimed = params.get("openid.claimed_id", "")
    if claimed != params.get("openid.identity"):
        raise Invalid("claimed_id and identity differ")
    found = CLAIMED_ID.match(claimed)
    if found is None:
        raise Invalid("claimed_id isn't a Steam ID")
    signed = set(params.get("openid.signed", "").split(","))
    missing = [field for field in SIGNED_FIELDS if field not in signed]
    if missing or not params.get("openid.sig") or not params.get("openid.assoc_handle"):
        raise Invalid(f"unsigned fields: {','.join(missing) or 'sig'}")
    nonce = params.get("openid.response_nonce", "")
    if abs(timezone.now() - _nonce_time(nonce)) > NONCE_MAX_AGE:
        raise Invalid("stale response_nonce")
    # Remember it before asking Steam, so two racing replays can't both get through.
    key = "steam-openid-nonce:" + hashlib.sha256(nonce.encode()).hexdigest()
    if not cache.add(key, True, timeout=NONCE_MEMORY_SECONDS):
        raise Invalid("replayed response_nonce")
    _check_authentication(params)
    return int(found[1])


def _check_authentication(params: Mapping[str, str]) -> None:
    body = {key: value for key, value in params.items() if key.startswith("openid.")}
    body["openid.mode"] = "check_authentication"
    try:
        with _client() as client:
            response = client.post(OP_ENDPOINT, data=body)
    except httpx.HTTPError as exc:
        raise Unreachable(f"Steam unreachable: {type(exc).__name__}") from exc
    if response.status_code != 200:
        raise Unreachable(f"check_authentication {response.status_code}")
    answer = dict(line.split(":", 1) for line in response.text.splitlines() if ":" in line)
    if answer.get("is_valid", "").strip() != "true":
        raise Invalid("check_authentication said is_valid:false")


def persona_name(steam64: int) -> str:
    """The account's Steam display name, or "" without STEAM_WEB_API_KEY or on any failure.
    Sign-in never waits long for it or fails over it."""
    if not settings.STEAM_WEB_API_KEY:
        return ""
    try:
        with _client() as client:
            response = client.get(
                SUMMARIES_URL,
                params={"key": settings.STEAM_WEB_API_KEY, "steamids": str(steam64)},
                timeout=PERSONA_TIMEOUT,
            )
        response.raise_for_status()
        players = response.json().get("response", {}).get("players") or []
        name = players[0].get("personaname") if players else ""
    except (httpx.HTTPError, ValueError, AttributeError, IndexError, TypeError) as exc:
        logger.info("Steam name lookup failed", extra={"why": type(exc).__name__})
        return ""
    return str(name or "")[:100]
