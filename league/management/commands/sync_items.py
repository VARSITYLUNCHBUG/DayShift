from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from league.integrations.deadlock_api import ApiError
from league.services import items


class Command(BaseCommand):
    help = "Copy deadlock-api's shop items, for the item names on the web's postgame builds."

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            count = items.sync()
        except ApiError as exc:
            raise CommandError(f"Couldn't fetch the items: {exc}") from exc
        self.stdout.write(f"Stored {count} items.")
