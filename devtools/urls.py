from __future__ import annotations

from django.urls import re_path

from devtools.views.http import endpoint

app_name = "devtools"
urlpatterns = [re_path(r"^api/(?P<path>.*)$", endpoint, name="api")]
