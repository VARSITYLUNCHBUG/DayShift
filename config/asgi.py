"""The web process: the Django admin and the calibration dashboard, served by uvicorn.

The bot never imports it.
"""

from __future__ import annotations

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_asgi_application()

from config.logging import set_process  # noqa: E402

set_process(service="web")
