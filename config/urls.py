"""The web process's routes. /healthz and /readyz (config.health) are answered by middleware
before these."""

from __future__ import annotations

from django.contrib import admin
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import path

from league.web.views import calibration_dashboard

urlpatterns = [
    # Before the admin's own URLs, so it isn't read as an app label.
    path("admin/calibration/", calibration_dashboard, name="calibration"),
    path("admin/", admin.site.urls),
    # WhiteNoise serves /static/ from the image's collected files. With DEBUG on, this serves the
    # apps' own folders too, so a change shows without collectstatic. Empty with DEBUG off.
    *staticfiles_urlpatterns(),
]
