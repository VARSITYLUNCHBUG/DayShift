"""The player web UI's server side: sign-in, the HTTP API and the files it serves. The websocket
(league/web/live) is routed in config/asgi.py."""

from __future__ import annotations

from django.urls import include, path

urlpatterns = [
    path("auth/", include("league.web.auth.urls")),
    path("api/", include("league.web.api.urls")),
]
