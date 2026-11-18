from __future__ import annotations

import sys
import time
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand

MAX_AGE_SECONDS = 60


class Command(BaseCommand):
    help = "Exit non-zero if the bot's task loops have stopped updating the heartbeat file."

    def handle(self, *args: Any, **options: Any) -> None:
        # Every role writes the same file: each runs in its own container. To run two roles side by
        # side on one machine, give each its own BOT_HEARTBEAT_FILE.
        path = settings.BOT_HEARTBEAT_FILE
        try:
            age = time.time() - path.stat().st_mtime
        except OSError:
            self.stderr.write(f"No heartbeat file at {path}.")
            sys.exit(1)
        if age > MAX_AGE_SECONDS:
            self.stderr.write(f"Heartbeat is {age:.0f}s old.")
            sys.exit(1)
