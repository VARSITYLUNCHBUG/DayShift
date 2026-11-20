"""Hero card art, kept in the repo as an art pack: `league/static/hero-art/<slug>.webp`.

The web serves the pack as static files, so nothing is fetched while it runs. When heroes are
added or their art changes, `manage.py update_hero_art` refreshes the pack from deadlock-api's
copy of the game's assets, and the new files are committed. A hero without a file shows its
initials.
"""

from __future__ import annotations

import functools
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from django.conf import settings

from league.domain.images import detect_image
from league.models import Champion

logger = logging.getLogger(__name__)

ART_DIR = Path(__file__).resolve().parent.parent / "static" / "hero-art"
STATIC_PATH = "hero-art/{slug}.webp"  # Under STATIC_URL.
HEROES_PATH = "/v1/assets/heroes"
IMAGE_KEY = "icon_hero_card_webp"  # The hero's card, as the game's hero picker shows it.
TIMEOUT = 20.0  # Seconds, per request.
MAX_ART_BYTES = 2 * 1024 * 1024  # A card is tens of KB.


class ArtError(Exception):
    """deadlock-api couldn't give us this art. The message says why."""


@dataclass(slots=True)
class UpdateReport:
    written: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)  # deadlock-api has no card for them.
    failed: list[tuple[str, str]] = field(default_factory=list)  # (hero, why)


def art_file(slug: str) -> Path:
    return ART_DIR / f"{slug}.webp"


@functools.cache
def available() -> frozenset[str]:
    """The slugs the pack has art for. Read once per process: the pack ships with the code."""
    return (
        frozenset(path.stem for path in ART_DIR.glob("*.webp")) if ART_DIR.is_dir() else frozenset()
    )


def _client() -> httpx.Client:
    """Tests swap this for one on an `httpx.MockTransport`."""
    return httpx.Client(base_url=settings.DEADLOCK_API_BASE, timeout=TIMEOUT, follow_redirects=True)


def _heroes(client: httpx.Client) -> dict[int, dict[str, Any]]:
    try:
        response = client.get(HEROES_PATH, params={"only_active": "true"})
    except httpx.HTTPError as exc:
        raise ArtError(f"deadlock-api unreachable: {type(exc).__name__}") from exc
    if response.status_code != 200:
        raise ArtError(f"deadlock-api answered {response.status_code}")
    try:
        data: Any = response.json()
    except ValueError as exc:
        raise ArtError("deadlock-api answered with something other than JSON") from exc
    if not isinstance(data, list):
        raise ArtError("deadlock-api's hero list wasn't a list")
    return {hero["id"]: hero for hero in data if isinstance(hero, dict) and "id" in hero}


def _card_url(hero: dict[str, Any] | None) -> str | None:
    images = hero.get("images") if hero else None
    url = images.get(IMAGE_KEY) if isinstance(images, dict) else None
    return url if isinstance(url, str) and url else None


def download(client: httpx.Client, url: str) -> bytes:
    """The card's bytes. Refuses anything that isn't https, is too big, or isn't a WebP."""
    if not url.startswith("https://"):
        raise ArtError("not an https URL")
    try:
        response = client.get(url)
    except httpx.HTTPError as exc:
        raise ArtError(f"image unreachable: {type(exc).__name__}") from exc
    if response.status_code != 200:
        raise ArtError(f"image answered {response.status_code}")
    if len(response.content) > MAX_ART_BYTES:
        raise ArtError(f"image too big ({len(response.content)} bytes)")
    if detect_image(response.content) != "webp":
        raise ArtError("not a WebP image")
    return response.content


def update() -> UpdateReport:
    """Write every enabled hero's card into the pack. Files that haven't changed are left
    alone, and a hero deadlock-api can't give keeps the file it had.

    Raises ArtError when the hero list itself can't be had."""
    directory = ART_DIR
    directory.mkdir(parents=True, exist_ok=True)
    report = UpdateReport()
    with _client() as client:
        by_id = _heroes(client)
        for champion in Champion.objects.filter(is_enabled=True).order_by("name"):
            url = _card_url(by_id.get(champion.pk))
            if url is None:
                report.missing.append(champion.name)
                continue
            try:
                data = download(client, url)
            except ArtError as exc:
                report.failed.append((champion.name, str(exc)))
                continue
            path = directory / f"{champion.slug}.webp"
            if path.is_file() and path.read_bytes() == data:
                report.unchanged.append(champion.name)
                continue
            path.write_bytes(data)
            report.written.append(champion.name)
    available.cache_clear()
    return report
