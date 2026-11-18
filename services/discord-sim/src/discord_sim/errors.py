"""Discord's JSON errors, with the real codes the bot branches on."""

from __future__ import annotations

from typing import Any


class DiscordError(Exception):
    """Raised anywhere in the sim; the API middleware turns it into Discord's error JSON."""

    def __init__(
        self, status: int, code: int, message: str, errors: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.errors = errors

    def body(self) -> dict[str, Any]:
        body: dict[str, Any] = {"message": self.message, "code": self.code}
        if self.errors:
            body["errors"] = self.errors
        return body


class ControlError(Exception):
    """A bad request to the /_sim control API. Plain `{"error": ...}` JSON, plus any details."""

    def __init__(self, status: int, error: str, **details: Any) -> None:
        super().__init__(error)
        self.status = status
        self.error = error
        self.details = details


def unauthorized() -> DiscordError:
    return DiscordError(401, 0, "401: Unauthorized")


def not_found_route() -> DiscordError:
    return DiscordError(404, 0, "404: Not Found")


def unknown_channel() -> DiscordError:
    return DiscordError(404, 10003, "Unknown Channel")


def unknown_guild() -> DiscordError:
    return DiscordError(404, 10004, "Unknown Guild")


def unknown_invite() -> DiscordError:
    return DiscordError(404, 10006, "Unknown Invite")


def unknown_member() -> DiscordError:
    return DiscordError(404, 10007, "Unknown Member")


def unknown_message() -> DiscordError:
    return DiscordError(404, 10008, "Unknown Message")


def unknown_overwrite() -> DiscordError:
    return DiscordError(404, 10009, "Unknown Overwrite")


def unknown_user() -> DiscordError:
    return DiscordError(404, 10013, "Unknown User")


def unknown_webhook() -> DiscordError:
    return DiscordError(404, 10015, "Unknown Webhook")


def unknown_interaction() -> DiscordError:
    return DiscordError(404, 10062, "Unknown interaction")


def not_in_voice() -> DiscordError:
    return DiscordError(400, 40032, "Target user is not connected to voice.")


def already_acknowledged() -> DiscordError:
    return DiscordError(400, 40060, "Interaction has already been acknowledged.")


def missing_access() -> DiscordError:
    return DiscordError(403, 50001, "Missing Access")


def edit_others_message() -> DiscordError:
    return DiscordError(403, 50005, "Cannot edit a message authored by another user")


def empty_message() -> DiscordError:
    return DiscordError(400, 50006, "Cannot send an empty message")


def cannot_dm() -> DiscordError:
    return DiscordError(403, 50007, "Cannot send messages to this user")


def invalid_recipient() -> DiscordError:
    return DiscordError(400, 50033, "Invalid Recipient(s)")


def invalid_json() -> DiscordError:
    return DiscordError(400, 50109, "The request body contains invalid JSON.")


def invalid_form(field_errors: dict[str, tuple[str, str]]) -> DiscordError:
    """50035 with Discord's nested `errors`. Keys are dotted paths such as `components.0.label`."""
    errors: dict[str, Any] = {}
    for path, (code, message) in field_errors.items():
        node = errors
        for part in path.split("."):
            node = node.setdefault(part, {})
        node.setdefault("_errors", []).append({"code": code, "message": message})
    return DiscordError(400, 50035, "Invalid Form Body", errors)
