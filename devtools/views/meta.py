from __future__ import annotations

from devtools import api
from devtools.api import JSON, Body


@api.route("GET", "", "This list of routes")
def index(body: Body) -> JSON:
    return api.describe()
