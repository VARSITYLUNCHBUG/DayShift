"""The web process's routes. /healthz, /readyz (config.health) and /metrics
(league.observability) are answered by middleware before these."""

from __future__ import annotations

from django.contrib import admin
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import path

from league.web.views import calibration_dashboard

urlpatterns = [
    # Before the admin's own URLs, so it isn't read as an app label.
    path("admin/calibration/", calibration_dashboard, name="calibration"),
    path("admin/", admin.site.urls),
    # The edge serves /static/ in every stack. With DEBUG on, web serves it too, from the apps'
    # own folders, for whatever talks to web directly: the dev stack's port, the test stack, a
    # frontend dev server's proxy. Empty with DEBUG off.
    *staticfiles_urlpatterns(),
]
