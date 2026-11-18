#!/usr/local/bin/python
"""Stand-in for the web process: health probes, metrics, and Django's host check for the rest."""

from __future__ import annotations

import base64
import hashlib
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from stub import database_reachable, metrics

ALLOWED_HOSTS = {h.strip() for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h.strip()}
WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class Handler(BaseHTTPRequestHandler):
    """Answers like the app: probes and /metrics before the host check, then 400 or 200."""

    def _send(self, status: int, body: bytes, content_type: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Stub-Forwarded-Proto", self.headers.get("X-Forwarded-Proto", ""))
        self.send_header("X-Stub-Forwarded-For", self.headers.get("X-Forwarded-For", ""))
        self.end_headers()
        self.wfile.write(body)

    def _wants_websocket(self) -> bool:
        return (self.headers.get("Upgrade") or "").lower() == "websocket"

    def _upgrade(self) -> None:
        """Complete a websocket handshake under /ws/ (config/asgi.py's prefix), then hang up."""
        key = self.headers.get("Sec-WebSocket-Key", "") + WEBSOCKET_GUID
        accept = base64.b64encode(hashlib.sha1(key.encode()).digest()).decode()
        self.send_response(101)
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept)
        self.end_headers()
        self.close_connection = True

    def _reply(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        if self.path == "/healthz":
            self._send(200, b'{"status": "ok"}')
        elif self.path == "/readyz":
            ready = database_reachable()
            self._send(200 if ready else 503, b'{"status": "%s"}' % (b"ok" if ready else b"down"))
        elif self.path == "/metrics" and "X-Forwarded-For" not in self.headers:
            self._send(200, metrics("web"), "text/plain; version=0.0.4")
        elif self.path.startswith("/ws/") and self._wants_websocket():
            self._upgrade()
        elif (self.headers.get("Host") or "").split(":")[0] in ALLOWED_HOSTS:
            self._send(200, b'{"status": "ok"}')
        else:
            self._send(400, b"bad host", "text/plain")

    do_GET = _reply
    do_POST = _reply


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
