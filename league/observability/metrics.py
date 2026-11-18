"""The web process's Prometheus metrics, and the middleware that records and serves them.

`metrics_middleware` runs outermost. It times every request under its URL pattern, never the raw
path, so the number of series stays bounded. It also answers `/metrics` itself, before
ALLOWED_HOSTS is checked, so Prometheus can scrape `web:8000` by its service name. A request that
came through the edge proxy (it carries X-Forwarded-For) gets a 404 there; the edge blocks the
path too.

uvicorn runs one worker process, so the plain single-process client is enough. With more workers,
each would report only its own requests and prometheus_client's multiprocess mode would be needed.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import cast

from asgiref.sync import iscoroutinefunction
from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseBase, HttpResponseNotFound
from django.utils.decorators import sync_and_async_middleware
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    GC_COLLECTOR,
    PLATFORM_COLLECTOR,
    PROCESS_COLLECTOR,
    CollectorRegistry,
    Counter,
    Histogram,
    disable_created_metrics,
    generate_latest,
)

from league.asyncdb import db
from league.observability.domain import DomainCollector

METRICS_PATH = "/metrics"
METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"})
# Answered by config.health's middleware, before any URL pattern is matched.
PROBES = frozenset({"/healthz", "/readyz"})

# Prometheus has no use for each series' `_created` twin.
disable_created_metrics()

# Its own registry rather than the client's global one, which holds whatever anything imported
# registers: the bot's metrics must never show up here, nor the league gauges there.
REGISTRY = CollectorRegistry()
for _collector in (PROCESS_COLLECTOR, PLATFORM_COLLECTOR, GC_COLLECTOR, DomainCollector()):
    REGISTRY.register(_collector)

REQUESTS = Counter(
    "draftbot_http_requests",
    "HTTP requests by method, route and status code.",
    ("method", "route", "status"),
    registry=REGISTRY,
)
LATENCY = Histogram(
    "draftbot_http_request_duration_seconds",
    "Time to the response, by method and route.",
    ("method", "route"),
    registry=REGISTRY,
)

type SyncHandler = Callable[[HttpRequest], HttpResponseBase]
type AsyncHandler = Callable[[HttpRequest], Awaitable[HttpResponseBase]]


def route_of(request: HttpRequest) -> str:
    """The URL pattern that served `request`, such as `/admin/<app_label>/`."""
    match = getattr(request, "resolver_match", None)
    if match is not None:
        return "/" + match.route
    if request.path in PROBES:
        return request.path
    if request.path.startswith(settings.STATIC_URL or "/static/"):
        return "static"
    return "unmatched"


def observe(request: HttpRequest, status: int, started: float) -> None:
    method = request.method if request.method in METHODS else "other"
    route = route_of(request)
    LATENCY.labels(method, route).observe(time.perf_counter() - started)
    REQUESTS.labels(method, route, str(status)).inc()


def metrics_view(request: HttpRequest) -> HttpResponse:
    """Prometheus's text format. Not for anything that came through the edge."""
    if request.method not in {"GET", "HEAD"} or "HTTP_X_FORWARDED_FOR" in request.META:
        return HttpResponseNotFound()
    return HttpResponse(generate_latest(REGISTRY), content_type=CONTENT_TYPE_LATEST)


@sync_and_async_middleware
def metrics_middleware(get_response: SyncHandler | AsyncHandler) -> SyncHandler | AsyncHandler:
    if iscoroutinefunction(get_response):
        call_async = cast(AsyncHandler, get_response)

        async def middleware_async(request: HttpRequest) -> HttpResponseBase:
            if request.path == METRICS_PATH:
                # The league gauges query the database, which async code can't do directly.
                return await db(metrics_view, request)
            started = time.perf_counter()
            response = await call_async(request)
            observe(request, response.status_code, started)
            return response

        return middleware_async

    call_sync = cast(SyncHandler, get_response)

    def middleware(request: HttpRequest) -> HttpResponseBase:
        if request.path == METRICS_PATH:
            return metrics_view(request)
        started = time.perf_counter()
        response = call_sync(request)
        observe(request, response.status_code, started)
        return response

    return middleware
