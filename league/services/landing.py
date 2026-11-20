"""The landing page's call to action (`LandingItem`): what it shows now, made safe to draw.

Staff write a tagline in Markdown and an advert in HTML. Both are turned into HTML here and then
cleaned with an allow-list (nh3), so the page can insert them as they are: no scripts, styles,
frames or event attributes ever get through, and links can't run code. The page's CSP stops
anything that slipped past from loading or running anyway.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import nh3
from django.db.models import Q
from markdown_it import MarkdownIt

from league.domain import youtube
from league.models import LandingItem, LandingKind
from league.services import common

# Markdown with its raw HTML off: `<b>` in a tagline is shown as text, not made bold. A line
# break in the text is a line break on the page, so a headline can be set on two lines.
_MARKDOWN = MarkdownIt("commonmark", {"html": False, "breaks": True}).enable("strikethrough")

_LINK_RULES = {"a": {"href", "title"}}
HEADLINE_TAGS = {"br", "strong", "em", "del", "code", "a"}
TAGLINE_TAGS = HEADLINE_TAGS | {"p"}
ADVERT_TAGS = TAGLINE_TAGS | {
    "b", "i", "u", "s", "span", "h2", "h3", "h4", "ul", "ol", "li", "blockquote", "hr", "img",
}  # fmt: skip
_ADVERT_ATTRIBUTES = {**_LINK_RULES, "img": {"src", "alt", "width", "height"}}
_SCHEMES = {"https", "http", "mailto"}
_REL = "noopener noreferrer nofollow"


def _clean(html: str, tags: set[str]) -> str:
    return nh3.clean(
        html, tags=tags, attributes=_LINK_RULES, url_schemes=_SCHEMES, link_rel=_REL
    ).strip()


@dataclass(frozen=True, slots=True)
class Tagline:
    """A tagline, as the page sets it: its first paragraph is the headline, in the page's
    biggest type, and any after it the line under the headline."""

    headline_html: str  # Inline: emphasis, code, links and line breaks; no paragraphs.
    lead_html: str | None  # Paragraphs.


def tagline(markdown: str) -> Tagline | None:
    """A tagline's Markdown as clean HTML, split into its headline and the rest. None when
    nothing is left to show."""
    blocks = [block for block in re.split(r"\n\s*\n", markdown.strip()) if block.strip()]
    if not blocks:
        return None
    headline = _clean(_MARKDOWN.renderInline(blocks[0].strip()), HEADLINE_TAGS)
    if not headline:
        return None
    rest = _clean(_MARKDOWN.render("\n\n".join(blocks[1:])), TAGLINE_TAGS) if blocks[1:] else ""
    return Tagline(headline_html=headline, lead_html=rest or None)


def advert_html(html: str) -> str:
    """An advert's HTML, cleaned: text, lists, headings, links and images only."""
    return nh3.clean(
        html, tags=ADVERT_TAGS, attributes=_ADVERT_ATTRIBUTES, url_schemes=_SCHEMES, link_rel=_REL
    ).strip()


type AdvertKind = Literal["image", "html", "video", "youtube"]


@dataclass(frozen=True, slots=True)
class Advert:
    kind: AdvertKind
    alt: str
    link_url: str | None
    html: str | None = None  # "html": cleaned.
    src: str | None = None  # "image" and "video": the uploaded file's URL, on this site.
    youtube_id: str | None = None  # "youtube".


@dataclass(frozen=True, slots=True)
class Landing:
    tagline: Tagline | None
    advert: Advert | None


def _live(at: datetime) -> list[LandingItem]:
    return list(
        LandingItem.objects.filter(is_active=True)
        .filter(Q(starts_at__isnull=True) | Q(starts_at__lte=at))
        .filter(Q(ends_at__isnull=True) | Q(ends_at__gt=at))
    )


def _advert(item: LandingItem) -> Advert | None:
    link = item.link_url or None
    alt = item.alt_text.strip()
    if item.kind == LandingKind.IMAGE and item.image:
        return Advert("image", alt, link, src=item.image.url)
    if item.kind == LandingKind.HTML:
        html = advert_html(item.text)
        return Advert("html", alt, link, html=html) if html else None
    if item.kind == LandingKind.VIDEO and item.video:
        return Advert("video", alt, link, src=item.video.url)
    if item.kind == LandingKind.VIDEO and (found := youtube.video_id(item.youtube_url)):
        return Advert("youtube", alt, link, youtube_id=found)
    return None


def current() -> Landing:
    """The first live tagline and the first live advert, by `order` (newest first on a tie)."""
    items = _live(common.now())
    taglines = (tagline(i.text) for i in items if i.kind == LandingKind.TAGLINE)
    adverts = (_advert(i) for i in items if i.kind != LandingKind.TAGLINE)
    return Landing(
        tagline=next((line for line in taglines if line), None),
        advert=next((advert for advert in adverts if advert), None),
    )
