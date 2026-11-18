from __future__ import annotations

import json
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from devtools import scenarios
from devtools.errors import ControlError


class Command(BaseCommand):
    help = "Run a preset scenario from devtools/scenarios/ through the dev control API."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("name", nargs="?", help="The scenario, such as full_match.")
        parser.add_argument("--list", action="store_true", help="List the scenarios.")
        parser.add_argument("--from", dest="start", type=int, default=0, help="First step.")
        parser.add_argument("--count", type=int, default=None, help="How many steps to run.")

    def handle(self, *args: Any, **options: Any) -> None:
        if options["list"] or not options["name"]:
            for scenario in scenarios.load_all():
                self.stdout.write(f"{scenario.name}: {scenario.description}")
            return
        try:
            scenario = scenarios.load(options["name"])
            result = scenarios.run(scenario.steps, start=options["start"], count=options["count"])
        except ControlError as exc:
            raise CommandError(exc.message) from exc
        for step in result["ran"]:
            self.stdout.write(
                f"[{step['index']}] {step['status']} {step['seconds']:6.2f}s {step['title']}"
            )
        if not result["ok"]:
            failed = result["ran"][-1]
            raise CommandError(f"Step {failed['index']} failed: {json.dumps(failed['response'])}")
        self.stdout.write(f"Done: {result['next']} of {result['total']} steps.")
