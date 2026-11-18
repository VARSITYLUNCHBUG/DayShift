from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from devtools import seed


class Command(BaseCommand):
    help = (
        "Load the dev fixtures (fixtures/dev/*.json) into an empty database, then wire the "
        "community to the Discord simulator and seed ratings. Safe to run repeatedly."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--reload", action="store_true", help="Load the fixtures even if data is there."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        report = seed.run(reload=options["reload"])
        loaded = "loaded" if report.fixtures_loaded else "already there"
        self.stdout.write(f"Fixtures: {loaded}")
        self.stdout.write(f"Fixture players: {report.players}")
        self.stdout.write(f"Ratings seeded: {report.ratings_seeded}")
        self.stdout.write(f"Captain overrides added: {report.captains_allowed}")
        where = "the simulator's" if report.sim else "the fixture's (no simulator reachable)"
        self.stdout.write(f"Guild: {report.guild_id}, {where}")
        if report.channels_created:
            self.stdout.write("Channels made: " + ", ".join(report.channels_created))
        if report.channels_wired:
            self.stdout.write("Channels and PUG role: wired")
        elif not report.sim:
            self.stdout.write("Channels: not wired. Start the simulator and run this again.")
        if not report.fixtures_loaded and not report.players:
            self.stdout.write("No fixture players: the data isn't the fixtures'. Try --reload.")
