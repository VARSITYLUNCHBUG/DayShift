"""The one Django view in front of every control API route."""

from __future__ import annotations

import json
from urllib.parse import urlsplit

from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from devtools import api

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
LOOPBACK = frozenset({"localhost", "127.0.0.1", "::1"})


@csrf_exempt
def endpoint(request: HttpRequest, path: str) -> JsonResponse:
    if not same_site(request):
        status, body = api.error(
            403, "cross_origin", "Only this machine's pages may change dev state."
        )
        return JsonResponse(body, status=status)
    data = None
    if request.body:
        try:
            data = json.loads(request.body)
        except ValueError:
            status, body = api.error(400, "bad_request", "The body isn't valid JSON.")
            return JsonResponse(body, status=status)
    query = {key: request.GET[key] for key in request.GET}
    status, body = api.call(request.method or "GET", path, data, query)
    return JsonResponse(body, status=status)


def same_site(request: HttpRequest) -> bool:
    """Whether a state-changing call may come from where it says it came from.

    The API skips CSRF so that curl, tests and the panel can call it, but a plain-text POST from
    any web page is a "simple" request that needs no preflight, so a page the developer happens
    to visit could reset their database. Browsers send `Origin` with every non-GET request: only
    loopback pages (the control panel, its Vite server) and pages on the host being called get
    through. Clients that send no Origin (curl, httpx, the e2e suite) aren't browsers and pass."""
    if request.method in SAFE_METHODS:
        return True
    origin = request.headers.get("Origin")
    if origin is None:
        return True
    hostname = urlsplit(origin).hostname  # None for the opaque origin "null".
    if hostname is None:
        return False
    return hostname in LOOPBACK or hostname == urlsplit(f"//{request.get_host()}").hostname
