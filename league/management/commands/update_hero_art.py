from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from league.services import hero_art


class Command(BaseCommand):
    help = (
        "Refresh the hero art pack (league/static/hero-art/) from deadlock-api, for committing. "
        "Run it by hand when heroes are added or their art changes; the web never fetches art."
    )

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            report = hero_art.update()
        except hero_art.ArtError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            f"Hero art: {len(report.written)} written, {len(report.unchanged)} unchanged, "
            f"{len(report.missing)} with no card on deadlock-api, {len(report.failed)} failed."
        )
        if report.missing:
            self.stdout.write("No card: " + ", ".join(report.missing))
        for name, why in report.failed:
            self.stdout.write(f"  {name}: {why}")
        if report.written:
            self.stdout.write(f"Commit the new files in {hero_art.ART_DIR}.")
