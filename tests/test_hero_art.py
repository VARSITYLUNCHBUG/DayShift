"""Hero card art: the art pack in the repo, refreshing it from deadlock-api, and which URL each
hero gets."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
from django.core.management import CommandError, call_command

from league.models import Champion, Community
from league.services import hero_art
from league.web import heroes

pytestmark = pytest.mark.django_db

WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 "
PNG = b"\x89PNG\r\n\x1a\n" + b"card" * 10
BUCKET = "https://assets-bucket.example"


def card(name: str, version: int = 1) -> bytes:
    return WEBP + f"{name}:{version}".encode()


@dataclass
class Api:
    """deadlock-api on a mock transport: the hero list and the card files it points at."""

    version: int = 1
    no_card: set[int] = field(default_factory=set)  # Hero IDs listed without a card.
    bodies: dict[int, bytes] = field(default_factory=dict)  # Overrides, by hero ID.
    list_status: int = 200
    requests: list[httpx.Request] = field(default_factory=list)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == hero_art.HEROES_PATH:
            if self.list_status != 200:
                return httpx.Response(self.list_status)
            return httpx.Response(200, json=self.heroes())
        hero_id = int(request.url.path.rsplit("/", 1)[-1].removesuffix("_card.webp"))
        champion = Champion.objects.get(pk=hero_id)
        return httpx.Response(
            200, content=self.bodies.get(hero_id, card(champion.name, self.version))
        )

    def heroes(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for champion in Champion.objects.all():
            images = (
                {}
                if champion.pk in self.no_card
                else {
                    hero_art.IMAGE_KEY: f"{BUCKET}/heroes/{champion.pk}_card.webp",
                }
            )
            rows.append({"id": champion.pk, "name": champion.name, "images": images})
        return rows


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch, league: Community) -> Api:
    fake = Api()
    monkeypatch.setattr(
        hero_art,
        "_client",
        lambda: httpx.Client(
            base_url="https://api.example", transport=httpx.MockTransport(fake.handle)
        ),
    )
    return fake


@pytest.fixture
def pack(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """The pack, moved somewhere it can be written."""
    monkeypatch.setattr(hero_art, "ART_DIR", tmp_path / "hero-art")
    hero_art.available.cache_clear()
    yield hero_art.ART_DIR
    hero_art.available.cache_clear()


def enabled() -> list[Champion]:
    return list(Champion.objects.filter(is_enabled=True).order_by("name"))


# --- The pack in the repo ---------------------------------------------------------------------


def test_the_pack_has_every_preset_hero(league: Community) -> None:
    """The committed pack covers the champion presets: add a hero, run update_hero_art."""
    missing = [c.name for c in enabled() if c.slug not in hero_art.available()]
    assert missing == []
    for champion in enabled():
        data = hero_art.art_file(champion.slug).read_bytes()
        assert data[:4] == b"RIFF" and data[8:12] == b"WEBP"
        assert len(data) < hero_art.MAX_ART_BYTES


# --- Refreshing it ----------------------------------------------------------------------------


def test_update_writes_every_enabled_heros_card(api: Api, pack: Path) -> None:
    report = hero_art.update()
    assert sorted(report.written) == sorted(c.name for c in enabled())
    for champion in enabled():
        assert hero_art.art_file(champion.slug).read_bytes() == card(champion.name)
    listing = api.requests[0]
    assert listing.url.path == hero_art.HEROES_PATH and listing.url.params["only_active"] == "true"


def test_update_leaves_unchanged_files_alone(api: Api, pack: Path) -> None:
    hero_art.update()
    assert hero_art.update().written == []
    api.version = 2
    report = hero_art.update()
    assert len(report.written) == len(enabled()) and report.unchanged == []


def test_a_hero_without_a_card_is_reported(api: Api, pack: Path) -> None:
    abrams = Champion.objects.get(name="Abrams")
    api.no_card.add(abrams.pk)
    report = hero_art.update()
    assert report.missing == ["Abrams"]
    assert not hero_art.art_file(abrams.slug).exists()


@pytest.mark.parametrize("body", [PNG, b"<html>nope</html>"])
def test_only_webp_cards_go_in(api: Api, pack: Path, body: bytes) -> None:
    abrams = Champion.objects.get(name="Abrams")
    api.bodies[abrams.pk] = body
    report = hero_art.update()
    assert report.failed == [("Abrams", "not a WebP image")]
    assert not hero_art.art_file(abrams.slug).exists()


def test_a_failure_keeps_the_file_already_there(api: Api, pack: Path) -> None:
    hero_art.update()
    abrams = Champion.objects.get(name="Abrams")
    api.version = 2
    api.bodies[abrams.pk] = b"x" * (hero_art.MAX_ART_BYTES + 1)
    report = hero_art.update()
    assert report.failed and report.failed[0][0] == "Abrams"
    assert hero_art.art_file(abrams.slug).read_bytes() == card("Abrams", 1)


def test_cards_must_be_https(api: Api) -> None:
    with pytest.raises(hero_art.ArtError, match="https"), hero_art._client() as client:
        hero_art.download(client, "http://assets.example/card.webp")


def test_the_command_fails_when_deadlock_api_wont_answer(api: Api, pack: Path) -> None:
    api.list_status = 503
    with pytest.raises(CommandError, match="503"):
        call_command("update_hero_art")


def test_the_command_says_what_it_did(
    api: Api, pack: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    call_command("update_hero_art")
    out = capsys.readouterr().out
    assert f"Hero art: {len(enabled())} written, 0 unchanged" in out
    assert "Commit the new files" in out


# --- Which URL --------------------------------------------------------------------------------


def test_icon_urls_prefer_the_pack_then_the_champions_own(
    league: Community, monkeypatch: pytest.MonkeyPatch
) -> None:
    abrams = Champion.objects.get(name="Abrams")
    monkeypatch.setattr(hero_art, "available", lambda: frozenset({abrams.slug}))
    assert heroes.icon_url(abrams.slug, "") == f"/static/hero-art/{abrams.slug}.webp"
    assert (
        heroes.icon_url("geist", "https://cdn.example/geist.png") == "https://cdn.example/geist.png"
    )
    assert heroes.icon_url("seven", "") is None  # The page shows initials.
