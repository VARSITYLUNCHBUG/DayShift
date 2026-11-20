"""Discord OAuth2 with the `identify` scope: who the player is on Discord, nothing more.

Membership, nickname and avatar come from the bot's view of the server afterwards
(`discord_rest.get_member`), so the player never grants us their server list.

Every URL follows `settings.DISCORD_API_BASE`, so a dev stack can point it at a stand-in.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx
from django.conf import settings

DEFAULT_API_BASE = "https://discord.com/api/v10"
AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
TOKEN_URL = "https://discord.com/api/oauth2/token"
TIMEOUT = httpx.Timeout(10.0)
CALLBACK_PATH = "/auth/discord/callback/"


class OAuthError(Exception):
    """Discord didn't give us the user. The message is for the log, never shown to players."""


def _api_base() -> str:
    return str(settings.DISCORD_API_BASE).rstrip("/")


def _is_discord() -> bool:
    return _api_base() == DEFAULT_API_BASE


def authorize_endpoint() -> str:
    if _is_discord():
        return AUTHORIZE_URL
    parts = urlsplit(_api_base())
    return f"{parts.scheme}://{parts.netloc}/oauth2/authorize"


def token_endpoint() -> str:
    return TOKEN_URL if _is_discord() else f"{_api_base()}/oauth2/token"


def me_endpoint() -> str:
    return f"{_api_base()}/users/@me"


def redirect_uri() -> str:
    return settings.PUBLIC_URL + CALLBACK_PATH


def authorize_url(state: str) -> str:
    query = {
        "response_type": "code",
        "client_id": settings.DISCORD_CLIENT_ID,
        "scope": "identify",
        "state": state,
        "redirect_uri": redirect_uri(),
        # Someone who already agreed goes straight back instead of seeing the consent screen again.
        "prompt": "none",
    }
    return f"{authorize_endpoint()}?{urlencode(query)}"


def _client() -> httpx.Client:
    """Its own function so tests can stand in for Discord."""
    return httpx.Client(timeout=TIMEOUT)


def fetch_user_id(code: str) -> int:
    """Swap the callback's code for a token and read the user's ID with it. The token is
    dropped straight away: nothing else needs it."""
    try:
        with _client() as client:
            token = client.post(
                token_endpoint(),
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri(),
                },
                auth=(settings.DISCORD_CLIENT_ID, settings.DISCORD_CLIENT_SECRET),
            )
            if token.status_code != 200:
                raise OAuthError(f"token exchange {token.status_code}: {_error_of(token)}")
            body = token.json()
            access = body.get("access_token") if isinstance(body, dict) else None
            if not isinstance(access, str) or not access:
                raise OAuthError("token exchange returned no access token")
            me = client.get(me_endpoint(), headers={"Authorization": f"Bearer {access}"})
            if me.status_code != 200:
                raise OAuthError(f"/users/@me {me.status_code}")
            user = me.json()
            user_id = user.get("id") if isinstance(user, dict) else None
    except httpx.HTTPError as exc:
        raise OAuthError(f"Discord unreachable: {type(exc).__name__}") from exc
    except ValueError as exc:
        raise OAuthError("Discord returned something that isn't JSON") from exc
    if not isinstance(user_id, str) or not user_id.isdigit():
        raise OAuthError("/users/@me returned no user ID")
    return int(user_id)


def _error_of(response: httpx.Response) -> str:
    """Discord's error name only: the body of a failed exchange could echo the code."""
    try:
        body: Any = response.json()
    except ValueError:
        return "not JSON"
    return str(body.get("error", ""))[:50] if isinstance(body, dict) else ""
