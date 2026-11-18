"""The URLs with the dev control API in front (DEV_CONTROL). Never used in production."""

from __future__ import annotations

from django.urls import include, path

from config.urls import urlpatterns as base_urlpatterns

# First, so no catch-all route of the web UI can shadow it.
urlpatterns = [path("_control/", include("devtools.urls")), *base_urlpatterns]
