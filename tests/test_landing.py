"""The landing page's call to action (league/services/landing.py): what staff write in the admin,
cleaned, and what the public endpoint sends."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from django.conf import settings as django_settings
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from league.domain import youtube
from league.models import LandingItem, LandingKind
from league.services import landing
from tests.conftest import Clock

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32
MP4 = b"\0\0\0\x18ftypmp42" + b"\0" * 32


@pytest.fixture(autouse=True)
def media(settings: Any, tmp_path: Path) -> Path:
    settings.MEDIA_ROOT = tmp_path
    return tmp_path


def _item(kind: str = LandingKind.TAGLINE, **fields: Any) -> LandingItem:
    defaults: dict[str, Any] = {"name": kind, "text": "**Twelve in.** Two captains."}
    item = LandingItem(kind=kind, **{**defaults, **fields})
    item.full_clean()
    item.save()
    return item


# --- Cleaning ---------------------------------------------------------------------------------


def test_a_tagline_is_a_headline_then_its_lead() -> None:
    found = landing.tagline(
        "Twelve in.\nTwo **captains**.\n\nSeason 3: [the rules](https://example.com).\n\nAnd more."
    )
    assert found == landing.Tagline(
        headline_html="Twelve in.<br>\nTwo <strong>captains</strong>.",
        lead_html=(
            '<p>Season 3: <a href="https://example.com" rel="noopener noreferrer nofollow">'
            "the rules</a>.</p>\n<p>And more.</p>"
        ),
    )
    alone = landing.tagline("*Just* a headline")
    assert alone == landing.Tagline(headline_html="<em>Just</em> a headline", lead_html=None)
    assert landing.tagline("  \n\n ") is None


@pytest.mark.parametrize(
    "markdown",
    [
        "<script>alert(1)</script>",
        "[x](javascript:alert(1))",
        '<img src=x onerror="alert(1)">',
        "<b onclick=alert(1)>hi</b>",
    ],
)
def test_a_tagline_never_carries_script(markdown: str) -> None:
    found = landing.tagline(f"{markdown}\n\n{markdown}")
    assert found is not None
    html = found.headline_html + (found.lead_html or "")
    # Raw HTML and a script link stay as text: no tag, attribute or link comes of them.
    assert "<script" not in html and "<img" not in html and "<b " not in html
    assert "<a" not in html and "href" not in html


def test_an_advert_keeps_its_layout_and_loses_everything_active() -> None:
    html = landing.advert_html(
        '<h2 style="color:red">Season 3</h2><p onclick="x()">Sign up <a href="javascript:x()">'
        'now</a></p><script>x()</script><iframe src="https://evil"></iframe>'
        '<img src="/media/a.png" onerror="x()" alt="A">'
    )
    assert html == (
        '<h2>Season 3</h2><p>Sign up <a rel="noopener noreferrer nofollow">now</a></p>'
        '<img src="/media/a.png" alt="A">'
    )


@pytest.mark.parametrize(
    ("url", "found"),
    [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=1", "dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://example.com/watch?v=dQw4w9WgXcQ", None),
        ("https://www.youtube.com/watch?v=short", None),
        ("javascript:alert(1)", None),
    ],
)
def test_youtube_links_give_their_video_id(url: str, found: str | None) -> None:
    assert youtube.video_id(url) == found


# --- What staff may save ----------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("fields", "problem"),
    [
        ({"kind": LandingKind.TAGLINE, "text": " "}, "text"),
        ({"kind": LandingKind.IMAGE, "alt_text": "A"}, "image"),
        ({"kind": LandingKind.IMAGE, "image": SimpleUploadedFile("a.png", b"<svg/>")}, "image"),
        ({"kind": LandingKind.IMAGE, "image": SimpleUploadedFile("a.png", PNG)}, "alt_text"),
        ({"kind": LandingKind.VIDEO, "alt_text": "A"}, "video"),
        ({"kind": LandingKind.VIDEO, "alt_text": "A", "youtube_url": "https://example.com"}, "youtube_url"),  # noqa: E501
        ({"kind": LandingKind.VIDEO, "alt_text": "A", "video": SimpleUploadedFile("a.mp4", PNG)}, "video"),  # noqa: E501
    ],
)
def test_an_item_that_cant_be_shown_is_refused(fields: dict[str, Any], problem: str) -> None:
    item = LandingItem(name="x", **fields)
    with pytest.raises(ValidationError) as caught:
        item.full_clean()
    assert problem in caught.value.message_dict


@pytest.mark.django_db
def test_an_item_ends_after_it_starts(clock: Clock) -> None:
    now = landing.common.now()
    item = LandingItem(name="x", kind=LandingKind.TAGLINE, text="hi", starts_at=now, ends_at=now)
    with pytest.raises(ValidationError, match="end after it starts"):
        item.full_clean()


# --- What the page shows ----------------------------------------------------------------------


@pytest.mark.django_db
def test_with_nothing_live_the_page_uses_its_own_words(clock: Clock) -> None:
    _item(is_active=False)
    _item(starts_at=landing.common.now() + timedelta(hours=1))
    _item(ends_at=landing.common.now())
    assert landing.current() == landing.Landing(tagline=None, advert=None)


@pytest.mark.django_db
def test_the_first_live_tagline_and_advert_win(clock: Clock) -> None:
    _item(text="Second", order=2)
    _item(text="First", order=1)
    _item(LandingKind.HTML, text="<p>Advert</p>", order=5)
    image = _item(
        LandingKind.IMAGE, image=SimpleUploadedFile("a.png", PNG), alt_text="Season 3", order=1
    )
    now = landing.current()
    assert now.tagline == landing.Tagline(headline_html="First", lead_html=None)
    assert now.advert is not None and now.advert.kind == "image"
    assert now.advert.src == image.image.url and now.advert.src.startswith("/media/landing/")
    assert now.advert.alt == "Season 3"


@pytest.mark.django_db
def test_a_youtube_advert_sends_only_its_id(clock: Clock) -> None:
    _item(LandingKind.VIDEO, youtube_url="https://youtu.be/dQw4w9WgXcQ", alt_text="Trailer")
    advert = landing.current().advert
    assert advert == landing.Advert("youtube", "Trailer", None, youtube_id="dQw4w9WgXcQ")


@pytest.mark.django_db
def test_the_endpoint_is_public_and_shared_caches_may_keep_it(clock: Clock) -> None:
    _item(text="Hello *you*")
    _item(LandingKind.VIDEO, video=SimpleUploadedFile("a.mp4", MP4), alt_text="Clip")
    response = Client().get("/api/landing/")
    assert response.status_code == 200
    assert response["Cache-Control"] == "public, max-age=60"
    body = response.json()
    assert body["headline_html"] == "Hello <em>you</em>" and body["lead_html"] is None
    assert body["advert"]["kind"] == "video" and body["advert"]["src"].endswith(".mp4")
    assert body["advert"]["html"] is None and body["advert"]["youtube_id"] is None


@pytest.mark.django_db
def test_an_items_files_go_with_it(media: Path) -> None:
    item = _item(LandingKind.IMAGE, image=SimpleUploadedFile("a.png", PNG), alt_text="A")
    first = media / item.image.name
    assert first.exists()
    item.image = SimpleUploadedFile("b.png", PNG)
    item.save()
    assert not first.exists() and (media / item.image.name).exists()
    LandingItem.objects.all().delete()  # The admin's bulk delete.
    assert not list((media / "landing").iterdir())


def test_the_policy_lets_the_advert_play() -> None:
    policy = django_settings.CONTENT_SECURITY_POLICY
    assert policy["media-src"] == ["'self'"]
    assert policy["frame-src"] == ["https://www.youtube-nocookie.com"]


@pytest.mark.django_db
def test_the_session_says_where_ko_fi_is(settings: Any) -> None:
    settings.KOFI_URL = "https://ko-fi.com/dayshift"
    assert Client().get("/api/session/").json()["kofi_url"] == "https://ko-fi.com/dayshift"
    settings.KOFI_URL = ""
    assert Client().get("/api/session/").json()["kofi_url"] is None
