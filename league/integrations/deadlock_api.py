"""A small client for deadlock-api.com, the community API for Deadlock match data.

Every call is a blocking network request: run it off the event loop and outside any database
transaction (`asyncio.to_thread` from the bot). Nothing here touches the database.

deadlock-api is community-run and unofficial, so callers treat every failure as ordinary: a
lobby falls back to a captain entering a code, and a result check is retried or skipped.

Rate limits. Without an API key they are tight: a match deadlock-api has to fetch from Steam is
3 an hour per IP, and custom lobbies 10 an hour. A 429 says how long to wait (`next_request_in`
in its body, or Retry-After). Until then this client turns that kind of request away itself,
with no request sent, so a queue of retries can't keep the quota spent for ever (live, 20
November 2026: three matches retrying in turn kept each other out for hours).
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from django.conf import settings

TIMEOUT = httpx.Timeout(10.0, read=60.0)  # Lobby creation waits for Deadlock to make the party.
USER_AGENT = "DayShift (Deadlock inhouse bot)"

GAME_MODES = ("normal", "street_brawl")
SERVER_REGIONS = (
    "europe", "eu_amsterdam", "eu_poland", "eu_stockholm", "eu_helsinki", "eu_falkenstein",
    "eu_spain", "eu_east", "eu_london", "south_africa", "us_west", "us_east", "us_north_central",
    "us_south_central", "us_south_east", "us_south_west", "australia", "singapore", "japan",
    "hong_kong", "mp_hong_kong", "seoul", "chile", "peru", "argentina", "south_america",
)  # fmt: skip


class ApiError(Exception):
    """A request that didn't succeed. `status` is the HTTP status, or None for a network error."""

    def __init__(
        self,
        message: str,
        status: int | None = None,
        retry_after: int | None = None,
        *,
        held_back: bool = False,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after  # Seconds a 429 asks us to wait, when it says.
        # Not sent at all: an earlier 429 for this kind of request is still being waited out.
        self.held_back = held_back

    @property
    def rate_limited(self) -> bool:
        return self.status == 429


# Each kind of request has its own quota. A 429 on one holds back only that kind.
_KINDS = (
    ("bulk_metadata", re.compile(r"^/v1/matches/metadata$")),
    ("match_metadata", re.compile(r"^/v1/matches/\d+/metadata")),
    # A started lobby's match ID has a quota of its own (100 a second), apart from lobbies'.
    ("custom_match_id", re.compile(r"^/v1/matches/custom/[^/]+/match-id$")),
    ("custom_lobby", re.compile(r"^/v1/matches/custom/")),
)
# A 429 that doesn't say how long: wait this long before trying that kind again.
DEFAULT_WAIT_SECONDS = 60
_waits: dict[str, float] = {}  # Kind to the monotonic time its wait ends.
_waits_lock = threading.Lock()  # Calls run in worker threads (asyncio.to_thread).


def _kind(path: str) -> str:
    return next((name for name, pattern in _KINDS if pattern.match(path)), "other")


def wait_left(path: str) -> int:
    """Seconds until a request to `path` may be sent again, after a 429. 0: send it."""
    with _waits_lock:
        until = _waits.get(_kind(path), 0.0)
    return max(0, round(until - time.monotonic()))


def _hold_until(path: str, seconds: int) -> None:
    with _waits_lock:
        kind = _kind(path)
        _waits[kind] = max(_waits.get(kind, 0.0), time.monotonic() + seconds)


def forget_waits() -> None:
    """For tests: forget every 429."""
    with _waits_lock:
        _waits.clear()


def _headers() -> dict[str, str]:
    headers = {"User-Agent": USER_AGENT}
    if settings.DEADLOCK_API_KEY:
        headers["X-API-KEY"] = settings.DEADLOCK_API_KEY
    return headers


def _client() -> httpx.Client:
    return httpx.Client(base_url=settings.DEADLOCK_API_BASE, headers=_headers(), timeout=TIMEOUT)


def _request(method: str, path: str, **kwargs: Any) -> httpx.Response:
    if (left := wait_left(path)) > 0:
        raise ApiError(
            f"deadlock-api rate limit: waiting {left} s more before trying again",
            429,
            left,
            held_back=True,
        )
    try:
        with _client() as client:
            response = client.request(method, path, **kwargs)
    except httpx.HTTPError as exc:
        raise ApiError(f"deadlock-api unreachable: {type(exc).__name__}") from exc
    if response.status_code >= 400 and response.status_code != 404:
        detail = response.text[:200].strip()
        retry_after = _retry_after(response)
        if response.status_code == 429:
            _hold_until(path, retry_after or DEFAULT_WAIT_SECONDS)
        raise ApiError(
            f"deadlock-api {response.status_code}: {detail}", response.status_code, retry_after
        )
    return response


def _retry_after(response: httpx.Response) -> int | None:
    """How long a 429 asks us to wait, in seconds: `error.next_request_in` in deadlock-api's
    body, or else a Retry-After header in seconds (a date form is ignored)."""
    if response.status_code != 429:
        return None
    try:
        body = response.json()
    except (json.JSONDecodeError, ValueError):
        body = None
    error = body.get("error") if isinstance(body, dict) else None
    wait = error.get("next_request_in") if isinstance(error, dict) else None
    if isinstance(wait, int | float) and wait > 0:
        return int(wait) + 1  # Rounded up: a second early is another 429.
    raw = response.headers.get("retry-after", "").strip()
    return int(raw) if raw.isdigit() else None


# --- Matches ---------------------------------------------------------------------------------


def match_metadata(match_id: int) -> dict[str, Any] | None:
    """A finished match's metadata, or None when deadlock-api doesn't have it (yet). A match it
    hasn't stored yet is fetched from Steam, which is the 3-an-hour quota: try
    `bulk_match_metadata` first."""
    response = _request("GET", f"/v1/matches/{match_id}/metadata")
    if response.status_code == 404:
        return None
    data = response.json()
    return data if isinstance(data, dict) else None


BULK_PATH = "/v1/matches/metadata"
# Up to deadlock-api's limit on match_ids.
BULK_MAX = 1000
_BULK_PARAMS = {
    # Custom lobbies are private_lobby; the rest in case a match ID was mistyped as a public one.
    "match_mode": "private_lobby,unranked,ranked",
    "include_info": "true",
    "include_player_info": "true",
    "include_player_kda": "true",
    # The last sample of each stat: far cheaper than the time series.
    "include_player_final_stats": "true",
    "extra_player_columns": "mvp_rank",
}
_TEAMS = {"Team0": 0, "Team1": 1}
_GAME_MODES = {"Normal": 1}


def _mapped(names: dict[str, int], value: Any) -> Any:
    """The single-match form of a bulk value ("Team0" is 0), or the value as it came."""
    return names.get(value, value) if isinstance(value, str) else value


def bulk_match_metadata(match_ids: Iterable[int]) -> dict[int, dict[str, Any]]:
    """Metadata for every one of these matches deadlock-api has already stored, in one request
    and from its own database, never Steam: so it doesn't use the 3-an-hour quota. Matches it
    doesn't have are left out. Each value has `match_metadata`'s shape."""
    ids = sorted(set(match_ids))[:BULK_MAX]
    if not ids:
        return {}
    params = {**_BULK_PARAMS, "match_ids": ",".join(map(str, ids)), "limit": str(len(ids))}
    response = _request("GET", BULK_PATH, params=params)
    if response.status_code == 404:  # "No matches found".
        return {}
    rows = response.json()
    if not isinstance(rows, list):
        return {}
    found = {}
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("match_id"), int):
            found[row["match_id"]] = _from_bulk(row)
    return found


def _from_bulk(row: dict[str, Any]) -> dict[str, Any]:
    """A bulk row in the single-match shape the result check reads: a `match_info` wrapper,
    teams as 0 and 1, the start as a Unix time, and the final stats as the last sample."""
    players = [
        {
            **player,
            "team": _mapped(_TEAMS, player.get("team")),
            "stats": [player.get("final_stats") or {}],
        }
        for player in row.get("players") or []
        if isinstance(player, dict)
    ]
    info = {key: value for key, value in row.items() if key != "players"}
    info["winning_team"] = _mapped(_TEAMS, row.get("winning_team"))
    info["game_mode"] = _mapped(_GAME_MODES, row.get("game_mode"))
    info["start_time"] = _unix(row.get("start_time"))
    info["players"] = players
    return {"match_info": info}


def _unix(value: Any) -> int | None:
    """The bulk endpoint's "2026-11-19 22:16:47", in UTC, as a Unix time."""
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        return None
    try:
        return int(datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC).timestamp())
    except ValueError:
        return None


# --- Custom lobbies --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CreatedLobby:
    party_id: str
    party_code: str


def create_custom_match(region: str = "", game_mode: str = "normal") -> CreatedLobby:
    """Have deadlock-api's bot host a custom lobby. It readies itself, spectates, and leaves 15
    minutes after creating it, whatever the lobby is doing."""
    body: dict[str, Any] = {"game_mode": game_mode, "is_publicly_visible": False}
    if region:
        body["server_region"] = region
    response = _request("POST", "/v1/matches/custom/create", json=body)
    if response.status_code == 404:
        raise ApiError("deadlock-api has no custom match endpoint", 404)
    data = response.json()
    party_id, code = str(data.get("party_id") or ""), str(data.get("party_code") or "")
    if not party_id or not code:
        raise ApiError("deadlock-api returned no party code")
    return CreatedLobby(party_id=party_id, party_code=code)


def start_custom_match(party_id: str) -> None:
    response = _request("POST", f"/v1/matches/custom/{party_id}/start")
    if response.status_code == 404:
        raise ApiError("That lobby no longer exists", 404)


def custom_match_id(party_id: str) -> int | None:
    """The Deadlock match ID of a started custom lobby, or None if it isn't known yet."""
    response = _request("GET", f"/v1/matches/custom/{party_id}/match-id")
    if response.status_code == 404:
        return None
    match_id = response.json().get("match_id")
    return int(match_id) if isinstance(match_id, int) and match_id > 0 else None


# --- Steam -----------------------------------------------------------------------------------


def steam_names(account_ids: list[int]) -> dict[int, str]:
    """Steam display names by 32-bit account ID. Unknown accounts are left out."""
    if not account_ids:
        return {}
    response = _request(
        "GET", "/v1/players/steam", params={"account_ids": ",".join(map(str, account_ids))}
    )
    if response.status_code == 404:
        return {}
    rows = response.json()
    if not isinstance(rows, list):
        return {}
    return {
        int(row["account_id"]): str(row.get("personaname") or "")
        for row in rows
        if isinstance(row, dict) and "account_id" in row
    }


def resolve_vanity(name: str) -> int | None:
    """A custom profile URL name to a SteamID64, through Steam's own API. Needs
    STEAM_WEB_API_KEY; without it, or for an unknown name, None."""
    if not settings.STEAM_WEB_API_KEY:
        return None
    try:
        response = httpx.get(
            "https://api.steampowered.com/ISteamUser/ResolveVanityURL/v1/",
            params={"key": settings.STEAM_WEB_API_KEY, "vanityurl": name},
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ApiError(f"Steam unreachable: {type(exc).__name__}") from exc
    body = response.json().get("response", {})
    if body.get("success") != 1:
        return None
    return int(body["steamid"])
