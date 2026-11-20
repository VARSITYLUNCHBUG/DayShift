"""The player web UI's HTTP API: /api/..."""

from __future__ import annotations

from django.urls import URLPattern

app_name = "web_api"
urlpatterns: list[URLPattern] = []
