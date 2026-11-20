"""The player web UI's HTTP API: /api/..."""

from __future__ import annotations

from django.urls import URLPattern, path

from league.web.api import report, views
from league.web.auth.views import session_view

app_name = "web_api"
urlpatterns: list[URLPattern] = [
    # The same view as /auth/session/: who is signed in, and the CSRF cookie.
    path("session/", session_view, name="session"),
    path("matches/", views.matches, name="matches"),
    path("matches/<int:match_id>/", views.match, name="match"),
    path("matches/<int:match_id>/postgame/", views.match_postgame, name="postgame"),
    path("matches/<int:match_id>/report/", report.report, name="report"),
    path("ladder/", views.ladder, name="ladder"),
    path("seasons/", views.seasons, name="seasons"),
    path("me/", views.me, name="me"),
    path("me/share.png", views.share_png, name="share"),
    path("me/steam/<int:account_pk>/unlink/", views.steam_unlink, name="steam-unlink"),
    path("players/search/", views.player_search, name="player-search"),
    path("tools/random-draft/", views.random_draft, name="random-draft"),
]
