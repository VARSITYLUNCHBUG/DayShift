"""Errors the control API answers with, beyond the league's own DomainError."""

from __future__ import annotations


class ControlError(Exception):
    status = 400
    code = "bad_request"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class BadRequest(ControlError):
    pass


class NotFound(ControlError):
    status = 404
    code = "not_found"


class Conflict(ControlError):
    """The request is fine, but the league isn't in a state where it can be done."""

    status = 409
    code = "invalid_action"


class SimError(ControlError):
    status = 502
    code = "sim_error"

    def __init__(self, message: str, sim_status: int | None = None) -> None:
        super().__init__(message)
        self.sim_status = sim_status  # The simulator's own status, None if it wasn't reached.


class BotTimeout(ControlError):
    status = 504
    code = "timeout"


class BotBusy(ControlError):
    """The bot or the scheduler kept the league tables busy, so a reset couldn't start."""

    status = 503
    code = "busy"


class BotOffline(SimError):
    """The simulator has no bot connected to its gateway, so nobody can press anything."""

    status = 503
    code = "bot_offline"
