"""Sign-in and sign-out for the player web UI: /auth/..."""

from __future__ import annotations

from django.urls import path

from league.web.auth import views

app_name = "web_auth"
urlpatterns = [
    path("discord/", views.discord_start, name="discord"),
    path("discord/callback/", views.discord_callback, name="discord-callback"),
    path("steam/", views.steam_start, name="steam"),
    path("steam/callback/", views.steam_callback, name="steam-callback"),
    path("logout/", views.sign_out_view, name="logout"),
    path("session/", views.session_view, name="session"),
    path("dev/", views.dev_login, name="dev"),
]
