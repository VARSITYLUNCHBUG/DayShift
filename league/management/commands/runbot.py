from __future__ import annotations

import os
from typing import Any, Literal, cast

from django.core.management.base import BaseCommand, CommandError, CommandParser

from config.logging import set_process

type Role = Literal["all", "gateway", "scheduler"]

# all: everything in one process, as before. gateway: the Discord connection, clicks and the
# effect worker. scheduler: deadlines and the daily prune, with no Discord connection at all.
ROLES: tuple[Role, ...] = ("all", "gateway", "scheduler")


def resolve_role(option: str | None) -> Role:
    """`--role`, else `BOT_ROLE`, else `all`."""
    role = option or os.environ.get("BOT_ROLE", "").strip() or "all"
    if role not in ROLES:
        raise CommandError(f"BOT_ROLE must be one of {', '.join(ROLES)}, not {role!r}.")
    return cast(Role, role)


class Command(BaseCommand):
    help = "Run the Discord bot, or one of its roles."
    requires_system_checks = "__all__"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--role", choices=ROLES, help="Which part of the bot to run (default: BOT_ROLE or all)."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        role = resolve_role(options["role"])
        set_process(service="bot", role=role)
        from bot import client

        if role == "scheduler":
            client.run_scheduler()
        else:
            client.run(role)
