"""Hero art for the web: which URL shows each hero.

The order is the repo's art pack (`league/services/hero_art.py`, served as static files), then
the champion's own `icon_url`, then nothing, and the page shows initials.
"""

from __future__ import annotations

from django.templatetags.static import static

from league.services import hero_art


def icon_url(slug: str, fallback: str) -> str | None:
    if slug in hero_art.available():
        return static(hero_art.STATIC_PATH.format(slug=slug))
    return fallback or None
