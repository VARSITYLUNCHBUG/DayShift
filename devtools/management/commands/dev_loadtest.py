from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from devtools import loadtest
from devtools.errors import ControlError


class Command(BaseCommand):
    help = (
        "Play many matches at once on the server, with chat flooding each match channel, to load "
        "Discord. Run the bot with DISCORD_REQUEST_LOG=1, then read its log with "
        "devtools/loadtest_report.py."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--matches", type=int, default=12, help="Matches at once.")
        parser.add_argument("--tick", type=float, default=2.0, help="Seconds between rounds.")
        parser.add_argument(
            "--moves", type=int, default=2, help="Moves each match makes in a round."
        )
        parser.add_argument(
            "--chat-rate",
            type=float,
            default=0.45,
            help="Chat messages a second in each match channel; 0 for none. Discord lets "
            "webhooks post about 30 a minute in a channel.",
        )
        parser.add_argument(
            "--chat-lines",
            type=int,
            default=9,
            help="Lines in each chat message. 9 at 0.45 a second is about what twelve players "
            "can post under a 3 second slowmode.",
        )
        parser.add_argument("--timeout", type=float, default=1800, help="Give up after this.")

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            result = loadtest.run(
                options["matches"],
                tick=options["tick"],
                moves_per_tick=options["moves"],
                chat_rate=options["chat_rate"],
                chat_lines=options["chat_lines"],
                timeout=options["timeout"],
                say=self.stdout.write,
            )
        except ControlError as exc:
            raise CommandError(exc.message) from exc
        self.stdout.write(
            f"{len(result.matches)} matches in {result.seconds:.0f}s, {result.moves} moves; "
            f"chat: {result.chat_sent} messages, {result.chat_limited} refused by Discord"
        )
        if result.unfinished:
            raise CommandError(f"Unfinished: {result.unfinished}")
