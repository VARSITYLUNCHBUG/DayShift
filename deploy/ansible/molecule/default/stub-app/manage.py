"""Stand-in for the app's manage.py: the commands the compose files run, and nothing else."""

from __future__ import annotations

import os
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from stub import metrics

HEARTBEAT = Path(os.environ.get("BOT_HEARTBEAT_FILE", "/tmp/bot-heartbeat"))


def serve_metrics(service: str) -> None:
    """Serve /metrics on METRICS_PORT in the background, like bot.metrics."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = metrics(service)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("METRICS_PORT") or 9108)), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()


def runbot(args: list[str]) -> None:
    """Touch the heartbeat file every few seconds until SIGTERM, like the bot's task loops."""
    role = args[args.index("--role") + 1] if "--role" in args else "all"
    print(f"stub runbot --role {role}", flush=True)
    serve_metrics(os.environ.get("SERVICE_NAME", role))
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    while True:
        HEARTBEAT.touch()
        time.sleep(5)


def bot_healthcheck() -> None:
    """Fail unless the heartbeat file is fresh."""
    try:
        age = time.time() - HEARTBEAT.stat().st_mtime
    except OSError:
        sys.exit("No heartbeat file.")
    if age > 60:
        sys.exit(f"Heartbeat is {age:.0f}s old.")


def main() -> None:
    command, args = sys.argv[1], sys.argv[2:]
    if command == "runbot":
        runbot(args)
    elif command == "bot_healthcheck":
        bot_healthcheck()
    elif command in {"migrate", "load_presets"}:
        print(f"stub {command}: nothing to do", flush=True)
    else:
        sys.exit(f"stub manage.py: unknown command {command}")


if __name__ == "__main__":
    main()
