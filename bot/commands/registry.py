"""Every slash command the bot registers, in one place for the client and the tests."""

from __future__ import annotations

from typing import Any

from bot.commands import drafts, errors, permissions, pings, player, prio, setup, staff


def all_commands() -> tuple[Any, ...]:
    return (
        *player.COMMANDS,
        setup.setup_command,
        *permissions.GROUPS,
        *staff.GROUPS,
        *staff.COMMANDS,
        *drafts.COMMANDS,
        *prio.COMMANDS,
        *pings.COMMANDS,
        *errors.COMMANDS,
    )
