"""The player web UI's one page. React Router owns every path under it, so Django answers each of
them with the built index.html (`npm run build` in services/web writes it to `WEB_DIST`).

The site's CSP (`config.csp`) runs no inline script or style without the response's nonce, so
the page gets it: on every `<script>` and `<style>` tag, in place of Vite's `html.cspNonce`
placeholder if the build used one, and in a `<meta property="csp-nonce">` for styles the app
adds at runtime.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.urls import URLPattern, re_path
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_safe

MISSING_BUILD = (
    "The player web UI isn't built yet: run npm run build in services/web, "
    "or use the Vite dev server.\n"
)
# What a build may carry where the nonce goes (Vite's `html: { cspNonce: PLACEHOLDER }`).
PLACEHOLDER = "__CSP_NONCE__"
# Paths that belong to Django, never to the page: a first segment of exactly one of these.
DJANGO_PREFIXES = (
    "admin",
    "auth",
    "api",
    "ws",
    "static",
    "avatar",
    "_control",
    "healthz",
    "readyz",
)

_TAG = re.compile(r"<(script|style)\b(?![^>]*\bnonce=)", re.IGNORECASE)
_HEAD = re.compile(r"<head\b[^>]*>", re.IGNORECASE)
_META = re.compile(r"<meta\b[^>]*\bproperty=[\"']csp-nonce[\"']", re.IGNORECASE)


def with_nonce(html: str, nonce: str) -> str:
    """The page with this response's nonce wherever the CSP looks for it."""
    out = html.replace(PLACEHOLDER, nonce)
    out = _TAG.sub(lambda found: f'<{found[1]} nonce="{nonce}"', out)
    if not _META.search(out):
        out = _HEAD.sub(
            lambda found: f'{found[0]}<meta property="csp-nonce" nonce="{nonce}">', out, count=1
        )
    return out


@require_safe
@ensure_csrf_cookie
def spa(request: HttpRequest) -> HttpResponse:
    """The page sets the CSRF cookie, so the frontend's first POST carries it."""
    index = Path(settings.WEB_DIST) / "index.html"
    try:
        # Read per request: it's small, and a rebuild shows up without a restart.
        html = index.read_text(encoding="utf-8")
    except FileNotFoundError:
        return HttpResponse(MISSING_BUILD, status=503, content_type="text/plain; charset=utf-8")
    nonce: str = getattr(request, "csp_nonce", "")
    response = HttpResponse(
        with_nonce(html, nonce) if nonce else html, content_type="text/html; charset=utf-8"
    )
    # The page names the current build's hashed assets, so it's checked on every visit.
    response["Cache-Control"] = "no-cache"
    return response


def urlpatterns() -> list[URLPattern]:
    """The catch-all, for the end of the root URLconf: every path Django doesn't own."""
    skip = "|".join(re.escape(prefix) for prefix in DJANGO_PREFIXES)
    return [re_path(rf"^(?!(?:{skip})(?:/|$)).*$", spa, name="spa")]
