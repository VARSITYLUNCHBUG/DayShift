"""A few Discord REST calls the web process makes with the bot's token.

The bot itself talks to Discord through discord.py; nothing under `league/` may import that, so
the web process (sign-in's membership check, and screenshot uploads) uses these instead. They go
to `settings.DISCORD_API_BASE`, which a dev stack points at the Discord simulator. Every call is
a blocking network request: run it outside any database transaction.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

import httpx
from django.conf import settings

TIMEOUT = httpx.Timeout(10.0)
USER_AGENT = "DiscordBot (dayshift, 1.0)"
# Discord sometimes asks for a short pause. Wait that long once; a longer ask means a real limit,
# and a player waiting on a web page is better told to try again.
MAX_RETRY_AFTER = 5.0
UNKNOWN_MEMBER = 10007
UNKNOWN_USER = 10013


class DiscordRestError(Exception):
    """A request that didn't succeed. `status` is the HTTP status, or None for a network error."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True, slots=True)
class Member:
    user_id: int
    username: str
    global_name: str
    nick: str
    avatar: str  # The user's avatar hash, blank for Discord's default avatar.
    role_ids: tuple[int, ...]

    @property
    def display_name(self) -> str:
        """What the server shows: nickname, then the account's display name, then username."""
        return self.nick or self.global_name or self.username


def api_base() -> str:
    return str(settings.DISCORD_API_BASE).rstrip("/")


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bot {settings.DISCORD_TOKEN}", "User-Agent": USER_AGENT}


def _client() -> httpx.Client:
    """Its own function so tests can stand in for Discord."""
    return httpx.Client(base_url=api_base(), headers=_headers(), timeout=TIMEOUT)


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _retry_after(response: httpx.Response) -> float:
    try:
        return float(response.json().get("retry_after"))
    except (ValueError, TypeError, AttributeError):
        return float(response.headers.get("Retry-After") or MAX_RETRY_AFTER + 1)


def _error_code(response: httpx.Response) -> int | None:
    try:
        code = response.json().get("code")
    except (ValueError, AttributeError):
        return None
    return code if isinstance(code, int) else None


def _request(method: str, path: str, **kwargs: Any) -> httpx.Response:
    response: httpx.Response | None = None
    for attempt in range(2):
        try:
            with _client() as client:
                response = client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise DiscordRestError(f"Discord unreachable: {type(exc).__name__}") from exc
        if response.status_code != 429:
            break
        wait = _retry_after(response)
        if attempt or wait > MAX_RETRY_AFTER:
            raise DiscordRestError(f"Discord rate limited {method} {path} ({wait:.1f}s)", 429)
        _sleep(max(wait, 0.0))
    assert response is not None
    if response.status_code >= 400 and response.status_code != 404:
        detail = response.text[:200].strip()
        raise DiscordRestError(f"Discord {response.status_code}: {detail}", response.status_code)
    return response


def _json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise DiscordRestError("Discord returned something that isn't JSON") from exc


def get_member(guild_id: int, user_id: int) -> Member | None:
    """A server member, or None when that user isn't in the server. Raises DiscordRestError
    when Discord can't say either way (down, rate limited, or no such server)."""
    response = _request("GET", f"/guilds/{guild_id}/members/{user_id}")
    if response.status_code == 404:
        if _error_code(response) in (UNKNOWN_MEMBER, UNKNOWN_USER):
            return None
        raise DiscordRestError(f"Discord 404: {response.text[:200].strip()}", 404)
    data = _json(response)
    if not isinstance(data, dict):
        raise DiscordRestError("Discord returned no member")
    user = data.get("user") or {}
    try:
        found = int(user.get("id") or user_id)
        roles = tuple(int(role) for role in data.get("roles") or ())
    except (TypeError, ValueError, AttributeError) as exc:
        raise DiscordRestError("Discord returned a member we can't read") from exc
    if found != user_id:
        raise DiscordRestError("Discord returned a different member")
    return Member(
        user_id=found,
        username=str(user.get("username") or ""),
        global_name=str(user.get("global_name") or ""),
        nick=str(data.get("nick") or ""),
        avatar=str(user.get("avatar") or ""),
        role_ids=roles,
    )


def post_file(channel_id: int, data: bytes, filename: str, content: str = "") -> dict[str, Any]:
    """Post one file to a channel. Returns the message, whose attachments carry the file's URL.

    The text never pings anyone, whatever names it carries."""
    payload = {
        "content": content,
        "attachments": [{"id": 0, "filename": filename}],
        "allowed_mentions": {"parse": []},
    }
    response = _request(
        "POST",
        f"/channels/{channel_id}/messages",
        data={"payload_json": json.dumps(payload)},
        files={"files[0]": (filename, data)},
    )
    if response.status_code == 404:
        raise DiscordRestError("Discord 404: that channel doesn't exist", 404)
    message = _json(response)
    if not isinstance(message, dict):
        raise DiscordRestError("Discord returned no message")
    return message
