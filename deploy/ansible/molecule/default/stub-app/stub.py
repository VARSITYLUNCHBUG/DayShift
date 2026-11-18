"""What the stand-in's web process and bot share: the database probe and the metrics page."""

from __future__ import annotations

import os
import socket
from urllib.parse import urlsplit


def database_reachable() -> bool:
    """Whether DATABASE_URL's host (pgbouncer in compose) accepts a TCP connection."""
    url = urlsplit(os.environ.get("DATABASE_URL", ""))
    try:
        with socket.create_connection((url.hostname or "", url.port or 5432), timeout=2):
            return True
    except OSError:
        return False


def metrics(service: str) -> bytes:
    """A Prometheus text page with one gauge, so the scrape target counts as up."""
    return (
        "# HELP draftbot_stub_up The Molecule stand-in is running.\n"
        "# TYPE draftbot_stub_up gauge\n"
        f'draftbot_stub_up{{service="{service}"}} 1\n'
    ).encode()
