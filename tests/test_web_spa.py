"""Serving the player web UI: its page on every path Django doesn't own, with the CSP nonce, and
its files, under ASGI."""

from __future__ import annotations

import asyncio
import importlib
import json
import re
import warnings
from collections.abc import Iterator
from pathlib import Path

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.db import connections
from django.http import HttpResponse
from django.test import AsyncRequestFactory, Client, RequestFactory, override_settings

import config.asgi
from league.asyncdb import db
from league.models import Champion, Community
from league.services import hero_art
from league.web import heroes, spa
from league.web.static import AsgiWhiteNoiseMiddleware
from tests.web_helpers import http_get

PAGE = (
    "<!doctype html><html><head><title>DayShift</title>"
    '<script type="module" crossorigin src="/static/web/assets/index-D5bLmEV3.js"></script>'
    "<style>body{margin:0}</style></head><body><div id=root></div>"
    "<script>window.boot=1</script></body></html>"
)


@pytest.fixture
def dist(tmp_path: Path) -> Iterator[Path]:
    (tmp_path / "index.html").write_text(PAGE, encoding="utf-8")
    with override_settings(WEB_DIST=tmp_path):
        yield tmp_path


def _nonce(response: HttpResponse) -> str:
    found = re.search(r"'nonce-([^']+)'", response["Content-Security-Policy"])
    assert found is not None
    return found[1]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "path", ["/", "/signin", "/signin?error=not-member", "/matches/4", "/players/2", "/queue"]
)
def test_web_ui_paths_get_the_page_with_a_csrf_cookie(dist: Path, path: str) -> None:
    response = Client().get(path)
    assert response.status_code == 200
    assert b"<div id=root></div>" in response.content
    assert response["Content-Type"] == "text/html; charset=utf-8"
    assert response["Cache-Control"] == "no-cache"
    assert "csrftoken" in response.cookies


@pytest.mark.django_db
def test_every_script_and_style_carries_the_responses_nonce(dist: Path) -> None:
    response = Client().get("/")
    nonce = _nonce(response)
    html = response.content.decode()
    tags = re.findall(r"<(?:script|style)\b[^>]*>", html, re.IGNORECASE)
    assert len(tags) == 3
    assert all(f'nonce="{nonce}"' in tag for tag in tags)
    assert f'<meta property="csp-nonce" nonce="{nonce}">' in html
    # A new nonce per response.
    assert _nonce(Client().get("/")) != nonce


def test_a_builds_nonce_placeholder_is_filled_in() -> None:
    html = (
        '<html><head><meta property="csp-nonce" nonce="__CSP_NONCE__">'
        '<script nonce="__CSP_NONCE__" src="/a.js"></script></head></html>'
    )
    out = spa.with_nonce(html, "abc")
    assert "__CSP_NONCE__" not in out
    assert out.count('nonce="abc"') == 2


@pytest.mark.django_db
@pytest.mark.parametrize(
    "path", ["/administrators", "/apis", "/authors", "/static-pages", "/healthzone", "/wss"]
)
def test_paths_that_only_start_like_django_ones_are_web_ui_pages(dist: Path, path: str) -> None:
    assert b"<div id=root></div>" in Client().get(path).content


@pytest.mark.django_db
def test_head_works_and_writes_dont(dist: Path) -> None:
    assert Client().head("/signin").status_code == 200
    assert Client().post("/signin").status_code == 405


@pytest.mark.django_db
def test_django_routes_are_unaffected(dist: Path) -> None:
    client = Client()
    health = client.get("/healthz")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}

    admin = client.get("/admin/login/")
    assert admin.status_code == 200
    assert b"Django" in admin.content

    # Without the slash, Django still adds it rather than serving the page.
    assert client.get("/admin").status_code == 301


@pytest.mark.django_db
@pytest.mark.parametrize(
    "path",
    [
        "/api/nope/",
        "/auth/nope/",
        "/static/nope.js",
        "/avatar/1/abc.png",
        "/ws/",
        "/admin/nope/",
        "/_control/nope/",
    ],
)
def test_unknown_django_paths_are_not_found_not_the_page(dist: Path, path: str) -> None:
    response = Client().get(path)
    assert response.status_code in {302, 404}
    assert b"<div id=root></div>" not in response.content


@pytest.mark.django_db
def test_a_missing_build_says_how_to_build_it(tmp_path: Path) -> None:
    with override_settings(WEB_DIST=tmp_path / "missing"):
        response = Client().get("/signin")
    assert response.status_code == 503
    assert response["Content-Type"] == "text/plain; charset=utf-8"
    assert b"run npm run build in services/web" in response.content


# --- Static files -----------------------------------------------------------------------------


def _middleware(root: Path) -> AsgiWhiteNoiseMiddleware:
    with override_settings(STATIC_ROOT=None, WHITENOISE_ROOT=root, WHITENOISE_AUTOREFRESH=False):
        return AsgiWhiteNoiseMiddleware(lambda request: HttpResponse("not static"))


# Closing a response sends request_finished, which checks the database connection.
@pytest.mark.django_db
def test_static_files_stream_asynchronously_under_asgi(tmp_path: Path) -> None:
    body = bytes(range(256)) * 1000  # Several blocks.
    (tmp_path / "big.bin").write_bytes(body)
    middleware = _middleware(tmp_path)
    response = middleware(AsyncRequestFactory().get("/big.bin"))
    assert response.status_code == 200
    assert response.is_async

    async def read() -> bytes:
        return b"".join([chunk async for chunk in response])

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert asyncio.run(read()) == body
    response.close()


@pytest.mark.django_db
def test_static_files_stay_synchronous_under_wsgi(tmp_path: Path) -> None:
    (tmp_path / "small.txt").write_bytes(b"hello")
    response = _middleware(tmp_path)(RequestFactory().get("/small.txt"))
    assert not response.is_async
    assert b"".join(response) == b"hello"
    response.close()


def test_only_hashed_assets_are_cached_forever(tmp_path: Path) -> None:
    middleware = _middleware(tmp_path)
    assert middleware.immutable_file_test("", "/static/web/assets/index-D5bLmEV3.js")
    assert not middleware.immutable_file_test("", "/static/web/index.html")
    assert not middleware.immutable_file_test("", "/static/admin/css/base.css")


@pytest.mark.django_db
def test_debug_finds_files_in_a_prefixed_static_dir(tmp_path: Path) -> None:
    """DEBUG serves straight from the finders. The web UI's build sits under a prefix ("web"),
    which Django's finder compares using the platform's separator: on Windows the forward-slash
    URL path never matched it."""
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app-abc123.js").write_bytes(b"console.log(1)")
    with override_settings(
        DEBUG=True,
        STATIC_ROOT=None,
        STATICFILES_DIRS=[("web", tmp_path)],
        WHITENOISE_AUTOREFRESH=True,
        WHITENOISE_USE_FINDERS=True,
    ):
        middleware = AsgiWhiteNoiseMiddleware(lambda request: HttpResponse(status=404))
        response = middleware(RequestFactory().get("/static/web/assets/app-abc123.js"))
        assert response.status_code == 200
        assert b"".join(response) == b"console.log(1)"
        response.close()


@pytest.mark.django_db
def test_the_hero_art_pack_is_served_as_static_files(league: Community) -> None:
    abrams = Champion.objects.get(name="Abrams")
    with override_settings(DEBUG=True, WHITENOISE_AUTOREFRESH=True, WHITENOISE_USE_FINDERS=True):
        middleware = AsgiWhiteNoiseMiddleware(lambda request: HttpResponse(status=404))
        url = heroes.icon_url(abrams.slug, "")
        assert url == f"/static/hero-art/{abrams.slug}.webp"
        response = middleware(RequestFactory().get(url))
        assert response.status_code == 200
        assert response["Content-Type"] == "image/webp"
        assert b"".join(response) == hero_art.art_file(abrams.slug).read_bytes()
        response.close()


def test_collectstatic_keeps_the_builds_names_and_css_urls(tmp_path: Path) -> None:
    """The image's collectstatic hashes every file and rewrites CSS url()s. The page names the
    build's own files, so they must still be there under those names, and the build's CSS must
    still point at fonts that exist."""
    build = tmp_path / "dist"
    (build / "assets").mkdir(parents=True)
    (build / "index.html").write_text(PAGE, encoding="utf-8")
    (build / "assets" / "index-D5bLmEV3.js").write_text("import './chunk-AbC12.js'")
    (build / "assets" / "chunk-AbC12.js").write_text("export {}")
    (build / "assets" / "figtree-Xy9.woff2").write_bytes(b"font")
    (build / "assets" / "index-Qw3.css").write_text(
        "@font-face{src:url(/static/web/assets/figtree-Xy9.woff2) format('woff2')}"
        "@font-face{src:url(./figtree-Xy9.woff2)}"
        '.a{background:url("data:image/svg+xml,%3Csvg%3E")}'
    )
    out = tmp_path / "collected"
    storages = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }
    with override_settings(STATIC_ROOT=out, STATICFILES_DIRS=[("web", build)], STORAGES=storages):
        call_command("collectstatic", "--noinput", verbosity=0)
    assets = out / "web" / "assets"
    for name in ("index-D5bLmEV3.js", "chunk-AbC12.js", "index-Qw3.css", "figtree-Xy9.woff2"):
        assert (assets / name).is_file(), name
    manifest = json.loads((out / "staticfiles.json").read_text(encoding="utf-8"))["paths"]
    for css in (assets / "index-Qw3.css", out / manifest["web/assets/index-Qw3.css"]):
        for url in re.findall(r"url\(([^)\"']+)\)", css.read_text(encoding="utf-8")):
            target = (
                out / url.removeprefix("/static/")
                if url.startswith("/static/")
                else css.parent / url
            )
            assert target.resolve().is_file(), (css.name, url)


# --- The ASGI app -----------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_asgi_serves_http_through_django() -> None:
    async def go() -> tuple[dict[str, object], dict[str, object]]:
        try:
            return await http_get(config.asgi.application, "/healthz"), await http_get(
                config.asgi.application, "/admin/login/"
            )
        finally:
            await db(connections.close_all)

    health, admin = asyncio.run(go())
    assert health["status"] == 200
    assert json.loads(health["body"]) == {"status": "ok"}  # type: ignore[arg-type]
    assert admin["status"] == 200 and b"Django" in admin["body"]  # type: ignore[operator]


def test_the_web_process_refuses_wildcard_hosts() -> None:
    try:
        with (
            override_settings(DEBUG=False, ALLOWED_HOSTS=["*"]),
            pytest.raises(ImproperlyConfigured, match="ALLOWED_HOSTS"),
        ):
            importlib.reload(config.asgi)
    finally:
        importlib.reload(config.asgi)
