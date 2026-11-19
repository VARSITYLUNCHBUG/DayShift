from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from config.logging import set_process


class Command(BaseCommand):
    help = "Run the Discord bot: the gateway, the effect worker, the deadlines and the watchdog."
    requires_system_checks = "__all__"

    def handle(self, *args: Any, **options: Any) -> None:
        set_process(service="bot")
        from bot import client

        client.run()
