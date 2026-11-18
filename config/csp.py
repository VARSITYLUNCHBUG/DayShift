"""The Content-Security-Policy header, built from `settings.CONTENT_SECURITY_POLICY`.

The policy is a dict of directive to sources, so a new page extends it in one place (say
`"connect-src": ["'self'", "wss://example.com"]`). `'nonce'` in a directive becomes this response's
nonce, `'nonce-<random>'`: an inline `<script>` or `<style>` carries it as
`nonce="{{ request.csp_nonce }}"`, and nothing else inline runs. A view that sets its own
Content-Security-Policy header keeps it.
"""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import cast

from asgiref.sync import iscoroutinefunction
from django.conf import settings
from django.http import HttpRequest, HttpResponseBase
from django.utils.decorators import sync_and_async_middleware

HEADER = "Content-Security-Policy"
NONCE = "'nonce'"

type SyncHandler = Callable[[HttpRequest], HttpResponseBase]
type AsyncHandler = Callable[[HttpRequest], Awaitable[HttpResponseBase]]


def header(policy: Mapping[str, Sequence[str]], nonce: str) -> str:
    """`default-src 'self'; script-src 'self' 'nonce-…'`: one directive per entry, in order."""
    parts = []
    for directive, sources in policy.items():
        values = [f"'nonce-{nonce}'" if source == NONCE else source for source in sources]
        parts.append(" ".join([directive, *values]))
    return "; ".join(parts)


def _before(request: HttpRequest) -> str:
    nonce = secrets.token_urlsafe(16)
    request.csp_nonce = nonce  # type: ignore[attr-defined]
    return nonce


def _after(response: HttpResponseBase, nonce: str) -> HttpResponseBase:
    if HEADER not in response:
        response[HEADER] = header(settings.CONTENT_SECURITY_POLICY, nonce)
    return response


@sync_and_async_middleware
def csp_middleware(get_response: SyncHandler | AsyncHandler) -> SyncHandler | AsyncHandler:
    if iscoroutinefunction(get_response):
        call_async = cast(AsyncHandler, get_response)

        async def middleware_async(request: HttpRequest) -> HttpResponseBase:
            nonce = _before(request)
            return _after(await call_async(request), nonce)

        return middleware_async

    call_sync = cast(SyncHandler, get_response)

    def middleware(request: HttpRequest) -> HttpResponseBase:
        nonce = _before(request)
        return _after(call_sync(request), nonce)

    return middleware
