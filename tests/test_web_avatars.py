"""Avatars served from our own origin, so pages never see a Discord ID."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from django.test import Client

from league.models import Player
from league.web import avatars
from league.web.auth.session import SESSION_KEY
from tests.conftest import make_player

pytestmark = pytest.mark.django_db

PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 64


class Cdn:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.status = 200
        self.content_type = "image/png"
        self.body = PNG
        self.down = False

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.down:
            raise httpx.ConnectError("down", request=request)
        return httpx.Response(
            self.status, content=self.body, headers={"content-type": self.content_type}
        )


@pytest.fixture
def cdn(monkeypatch: pytest.MonkeyPatch, settings: Any) -> Iterator[Cdn]:
    settings.DISCORD_API_BASE = "https://discord.com/api/v10"
    fake = Cdn()
    monkeypatch.setattr(
        avatars,
        "_client",
        lambda: httpx.Client(
            base_url=avatars.cdn_base(), transport=httpx.MockTransport(fake.handle)
        ),
    )
    avatars.clear_cache()
    yield fake
    avatars.clear_cache()


def player_with_avatar(n: int = 1, avatar: str = "abc123") -> Player:
    player = make_player(n)
    Player.objects.filter(pk=player.pk).update(discord_avatar=avatar)
    player.refresh_from_db()
    return player


def signed_in(viewer: Player | None = None) -> Client:
    client = Client()
    session = client.session
    session[SESSION_KEY] = (viewer or make_player(99)).pk
    session.save()
    return client


def test_the_url_has_no_discord_id() -> None:
    player = player_with_avatar()
    url = avatars.avatar_url(player, 64)
    assert url == f"/avatar/{player.pk}/abc123.png?size=64"
    assert str(player.discord_user_id) not in (url or "")
    assert avatars.avatar_url(player) == f"/avatar/{player.pk}/abc123.png?size=128"


def test_no_hash_means_initials() -> None:
    assert avatars.avatar_url(make_player(1)) is None


def test_serves_the_cdn_image_and_keeps_it(cdn: Cdn) -> None:
    player = player_with_avatar()
    client = signed_in()
    for _ in range(2):
        response = client.get(f"/avatar/{player.pk}/abc123.png?size=64")
        assert response.status_code == 200
        assert response.content == PNG
        assert response["Content-Type"] == "image/png"
        assert response["Cache-Control"] == f"private, max-age={avatars.MAX_AGE}, immutable"
        assert response["X-Content-Type-Options"] == "nosniff"
    assert len(cdn.requests) == 1
    request = cdn.requests[0]
    assert request.url.host == "cdn.discordapp.com"
    assert request.url.path == f"/avatars/{player.discord_user_id}/abc123.png"
    assert request.url.params["size"] == "64"


def test_an_animated_hash_is_served_as_png(cdn: Cdn) -> None:
    player = player_with_avatar(avatar="a_0123abcd")
    assert signed_in().get(f"/avatar/{player.pk}/a_0123abcd.png").status_code == 200
    assert cdn.requests[0].url.path == f"/avatars/{player.discord_user_id}/a_0123abcd.png"


def test_sizes_are_cached_apart(cdn: Cdn) -> None:
    player = player_with_avatar()
    client = signed_in()
    client.get(f"/avatar/{player.pk}/abc123.png?size=64")
    client.get(f"/avatar/{player.pk}/abc123.png?size=256")
    assert [r.url.params["size"] for r in cdn.requests] == ["64", "256"]


@pytest.mark.parametrize("size", ["9999", "abc", "-1", ""])
def test_an_odd_size_gets_the_usual_one(cdn: Cdn, size: str) -> None:
    player = player_with_avatar()
    assert signed_in().get(f"/avatar/{player.pk}/abc123.png?size={size}").status_code == 200
    assert cdn.requests[0].url.params["size"] == str(avatars.DEFAULT_SIZE)


def test_signed_out_gets_nothing(cdn: Cdn) -> None:
    player = player_with_avatar()
    assert Client().get(f"/avatar/{player.pk}/abc123.png").status_code == 404
    assert cdn.requests == []


def test_an_inactive_viewer_gets_nothing(cdn: Cdn) -> None:
    player = player_with_avatar()
    viewer = make_player(50)
    Player.objects.filter(pk=viewer.pk).update(is_active=False)
    assert signed_in(viewer).get(f"/avatar/{player.pk}/abc123.png").status_code == 404
    assert cdn.requests == []


def test_only_the_current_avatar(cdn: Cdn) -> None:
    player = player_with_avatar()
    client = signed_in()
    assert client.get(f"/avatar/{player.pk}/old999.png").status_code == 404
    assert client.get(f"/avatar/{player.pk + 1000}/abc123.png").status_code == 404
    assert cdn.requests == []


def test_a_changed_avatar_stops_the_old_url(cdn: Cdn) -> None:
    player = player_with_avatar()
    client = signed_in()
    assert client.get(f"/avatar/{player.pk}/abc123.png").status_code == 200
    Player.objects.filter(pk=player.pk).update(discord_avatar="new456")
    assert client.get(f"/avatar/{player.pk}/abc123.png").status_code == 404


def test_a_player_without_an_avatar_has_no_url_to_fetch(cdn: Cdn) -> None:
    player = make_player(1)
    client = signed_in()
    # The route needs a non-empty hash, and a blank stored one matches nothing.
    assert client.get(f"/avatar/{player.pk}/.png").status_code == 404
    assert cdn.requests == []


@pytest.mark.parametrize("path", ["../x", "abc%2F..%2Fx", "abc.def"])
def test_only_a_plain_hash_reaches_the_route(cdn: Cdn, path: str) -> None:
    player = player_with_avatar()
    assert signed_in().get(f"/avatar/{player.pk}/{path}.png").status_code == 404
    assert cdn.requests == []


def test_only_get_and_head(cdn: Cdn) -> None:
    player = player_with_avatar()
    client = signed_in()
    assert client.head(f"/avatar/{player.pk}/abc123.png").status_code == 200
    assert client.post(f"/avatar/{player.pk}/abc123.png").status_code == 405


@pytest.mark.parametrize(
    ("status", "content_type", "body"),
    [
        (404, "image/png", PNG),
        (200, "text/html", PNG),
        (200, "image/png", b"x" * (avatars.MAX_BYTES + 1)),
    ],
    ids=["miss", "not-an-image", "too-big"],
)
def test_a_cdn_miss_is_a_miss(cdn: Cdn, status: int, content_type: str, body: bytes) -> None:
    cdn.status, cdn.content_type, cdn.body = status, content_type, body
    player = player_with_avatar()
    client = signed_in()
    assert client.get(f"/avatar/{player.pk}/abc123.png").status_code == 404
    # A miss isn't kept: the next request tries again.
    client.get(f"/avatar/{player.pk}/abc123.png")
    assert len(cdn.requests) == 2


def test_the_cdn_down_is_a_miss(cdn: Cdn) -> None:
    cdn.down = True
    player = player_with_avatar()
    assert signed_in().get(f"/avatar/{player.pk}/abc123.png").status_code == 404


def test_the_cache_keeps_only_the_newest(cdn: Cdn, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(avatars, "CACHED", 2)
    players = [player_with_avatar(n) for n in (1, 2, 3)]
    client = signed_in()
    for player in players:
        client.get(f"/avatar/{player.pk}/abc123.png")
    client.get(f"/avatar/{players[0].pk}/abc123.png")  # Evicted, so fetched again.
    client.get(f"/avatar/{players[2].pk}/abc123.png")  # Still kept.
    assert len(cdn.requests) == 4


def test_a_stand_in_discord_serves_avatars_too(settings: Any) -> None:
    settings.DISCORD_API_BASE = "http://sim.test:8080/api/v10"
    assert avatars.cdn_base() == "http://sim.test:8080"
    settings.DISCORD_API_BASE = "https://discord.com/api/v10"
    assert avatars.cdn_base() == "https://cdn.discordapp.com"
