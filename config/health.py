"""The web process's probes: `/healthz` (it is serving) and `/readyz` (and the database answers).

Answered before ALLOWED_HOSTS is checked and before the HTTPS redirect, so a container
healthcheck can ask 127.0.0.1 over plain HTTP whatever the public host is. `/readyz` queries
through the same connection settings as every request, so it proves the whole path to Postgres.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import cast

from asgiref.sync import iscoroutinefunction
from django.db import DatabaseError, connection
from django.http import HttpRequest, HttpResponseBase, JsonResponse
from django.utils.decorators import sync_and_async_middleware

from league.asyncdb import db

logger = logging.getLogger(__name__)

type SyncHandler = Callable[[HttpRequest], HttpResponseBase]
type AsyncHandler = Callable[[HttpRequest], Awaitable[HttpResponseBase]]


def healthz() -> JsonResponse:
    return JsonResponse({"status": "ok"})


def readyz() -> JsonResponse:
    """200 when Postgres answers a query, 503 when it doesn't."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except DatabaseError as error:
        logger.warning("Not ready: the database didn't answer", extra={"error": str(error)})
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ok"})


@sync_and_async_middleware
def health_middleware(get_response: SyncHandler | AsyncHandler) -> SyncHandler | AsyncHandler:
    if iscoroutinefunction(get_response):
        call_async = cast(AsyncHandler, get_response)

        async def middleware_async(request: HttpRequest) -> HttpResponseBase:
            if request.path == "/healthz":
                return healthz()
            if request.path == "/readyz":
                return await db(readyz)
            return await call_async(request)

        return middleware_async

    call_sync = cast(SyncHandler, get_response)

    def middleware(request: HttpRequest) -> HttpResponseBase:
        if request.path == "/healthz":
            return healthz()
        if request.path == "/readyz":
            return readyz()
        return call_sync(request)

    return middleware
