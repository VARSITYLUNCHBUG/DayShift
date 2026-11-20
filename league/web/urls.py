"""The player web UI's server side: sign-in, the HTTP API and the files it serves. The websocket
(league/web/live) is routed in config/asgi.py."""

from __future__ import annotations

from django.urls import include, path

from league.web import avatars

urlpatterns = [
    path("auth/", include("league.web.auth.urls")),
    path("api/", include("league.web.api.urls")),
    # Discord avatars from our own origin, so pages never see a Discord ID.
    path("avatar/<int:player_id>/<slug:avatar>.png", avatars.avatar, name="avatar"),
]
