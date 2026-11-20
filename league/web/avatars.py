"""Discord avatars for the web UI, served from our own origin.

Discord's CDN URLs carry the user's Discord ID, so pages never see them: a player's avatar is
`/avatar/<player id>/<avatar hash>.png`, and this module fetches it from the CDN. A new avatar has
a new hash, so each URL's image never changes and browsers keep it.
"""

from __future__ import annotations

from collections import OrderedDict
from threading import Lock
from urllib.parse import urlsplit

import httpx
from django.conf import settings
from django.http import Http404, HttpRequest, HttpResponse
from django.views.decorators.http import require_safe

from league.models import Player
from league.web.auth.session import player_of

CDN = "https://cdn.discordapp.com"
DEFAULT_API_BASE = "https://discord.com/api/v10"
SIZES = (32, 64, 128, 256)
DEFAULT_SIZE = 128
MAX_BYTES = 1024 * 1024  # Discord's avatars at these sizes are tens of KB.
MAX_AGE = 7 * 24 * 60 * 60  # Seconds. The URL changes with the avatar.
CACHED = 512  # Images kept in memory per process.
TIMEOUT = httpx.Timeout(5.0)

_cache: OrderedDict[tuple[int, str, int], bytes] = OrderedDict()
_lock = Lock()


def avatar_url(player: Player, size: int = DEFAULT_SIZE) -> str | None:
    """The player's Discord avatar, or None so the page shows their initials instead."""
    if not player.discord_avatar:
        return None
    return f"/avatar/{player.pk}/{player.discord_avatar}.png?size={size}"


def cdn_base() -> str:
    """Discord's CDN, or the host of a stand-in Discord (the simulator) on a dev stack."""
    base = str(settings.DISCORD_API_BASE).rstrip("/")
    if base == DEFAULT_API_BASE:
        return CDN
    parts = urlsplit(base)
    return f"{parts.scheme}://{parts.netloc}"


def _client() -> httpx.Client:
    """Its own function so tests can stand in for Discord's CDN."""
    return httpx.Client(base_url=cdn_base(), timeout=TIMEOUT)


def _fetch(user_id: int, avatar: str, size: int) -> bytes | None:
    try:
        with _client() as client:
            response = client.get(f"/avatars/{user_id}/{avatar}.png", params={"size": size})
    except httpx.HTTPError:
        return None
    if response.status_code != 200 or not response.headers.get("content-type", "").startswith(
        "image/"
    ):
        return None
    if len(response.content) > MAX_BYTES:
        return None
    return response.content


def _image(player_id: int, user_id: int, avatar: str, size: int) -> bytes | None:
    key = (player_id, avatar, size)
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    data = _fetch(user_id, avatar, size)
    if data is not None:
        with _lock:
            _cache[key] = data
            while len(_cache) > CACHED:
                _cache.popitem(last=False)
    return data


def clear_cache() -> None:
    with _lock:
        _cache.clear()


@require_safe
def avatar(request: HttpRequest, player_id: int, avatar: str) -> HttpResponse:
    """Signed-in players only: avatars show on the pages behind sign-in. Only the player's
    current avatar is served, so this can't be used to fetch anything else from the CDN."""
    if player_of(request) is None:
        raise Http404
    user_id = (
        Player.objects.filter(pk=player_id, discord_avatar=avatar)
        .exclude(discord_avatar="")
        .values_list("discord_user_id", flat=True)
        .first()
    )
    if user_id is None:
        raise Http404
    try:
        size = int(request.GET.get("size", DEFAULT_SIZE))
    except ValueError:
        size = DEFAULT_SIZE
    if size not in SIZES:
        size = DEFAULT_SIZE
    data = _image(player_id, user_id, avatar, size)
    if data is None:
        raise Http404
    return HttpResponse(
        data,
        content_type="image/png",
        headers={
            "Cache-Control": f"private, max-age={MAX_AGE}, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )
