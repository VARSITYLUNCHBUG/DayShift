"""The web process: Django over HTTP (the admin, the calibration dashboard and the player web UI),
and the players' websocket at /ws/.

uvicorn serves this. The bot never imports it.
"""

from __future__ import annotations

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# Set up Django before anything imports models.
django_application = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import AllowedHostsOriginValidator  # noqa: E402
from channels.sessions import SessionMiddlewareStack  # noqa: E402
from django.conf import settings  # noqa: E402
from django.core.exceptions import ImproperlyConfigured  # noqa: E402
from django.urls import path  # noqa: E402

from config.logging import set_process  # noqa: E402
from league.web.live.consumer import LiveConsumer  # noqa: E402

set_process(service="web")

# The websocket's only defence against another site opening it with a player's cookie is the
# Origin check against ALLOWED_HOSTS, and "*" lets every origin through.
if not settings.DEBUG and "*" in settings.ALLOWED_HOSTS:
    raise ImproperlyConfigured("The web process needs ALLOWED_HOSTS to name its hosts, not '*'.")

application = ProtocolTypeRouter(
    {
        "http": django_application,
        # The Origin check runs before the handshake is accepted, so a foreign page is refused
        # before the session is even read.
        "websocket": AllowedHostsOriginValidator(
            SessionMiddlewareStack(URLRouter([path("ws/", LiveConsumer.as_asgi())]))
        ),
    }
)
