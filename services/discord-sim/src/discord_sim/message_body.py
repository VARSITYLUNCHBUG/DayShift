"""The body of a message create or edit, as JSON or multipart, and Discord's checks on it."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from discord_sim import components
from discord_sim.errors import invalid_form

MISSING: Any = object()


@dataclass
class UploadedFile:
    """One `files[N]` part of a multipart request."""

    index: int
    filename: str
    content_type: str | None
    data: bytes


@dataclass
class MessageBody:
    """Fields present in the request. MISSING means the request left the field out."""

    content: Any = MISSING
    components: Any = MISSING
    embeds: Any = MISSING
    flags: Any = MISSING
    attachments: Any = MISSING
    allowed_mentions: Any = MISSING
    tts: bool = False
    files: list[UploadedFile] = field(default_factory=list)

    @classmethod
    def parse(cls, data: dict[str, Any], files: list[UploadedFile] | None = None) -> MessageBody:
        body = cls(files=files or [])
        for name in ("content", "components", "embeds", "flags", "attachments", "allowed_mentions"):
            if name in data:
                setattr(body, name, data[name])
        body.tts = bool(data.get("tts", False))
        if body.content is None:
            body.content = ""
        for name in ("components", "embeds", "attachments"):
            if getattr(body, name) is None:
                setattr(body, name, [])
        if body.flags is None:
            body.flags = 0
        return body

    def validate(self, *, v2: bool) -> None:
        """Discord's checks: the content limit, no content or embeds with V2, component limits."""
        problems: dict[str, tuple[str, str]] = {}
        content = self.content if self.content is not MISSING else ""
        if not isinstance(content, str):
            problems["content"] = ("BASE_TYPE_STRING", "Must be a string.")
            content = ""
        if len(content) > 2000:
            problems["content"] = ("BASE_TYPE_MAX_LENGTH", "Must be 2000 or fewer in length.")
        if v2 and content:
            problems["content"] = (
                "MESSAGE_CANNOT_USE_LEGACY_FIELDS_WITH_COMPONENTS_V2",
                "The 'content' field cannot be used when using MessageFlags.IS_COMPONENTS_V2",
            )
        if v2 and self.embeds not in (MISSING, []):
            problems["embeds"] = (
                "MESSAGE_CANNOT_USE_LEGACY_FIELDS_WITH_COMPONENTS_V2",
                "The 'embeds' field cannot be used when using MessageFlags.IS_COMPONENTS_V2",
            )
        if self.components is not MISSING and not isinstance(self.components, list):
            problems["components"] = ("BASE_TYPE_ARRAY", "Must be an array.")
        if problems:
            raise invalid_form(problems)
        if self.components not in (MISSING, []):
            components.validate(self.components, v2=v2)

    def is_empty(self) -> bool:
        return not (
            (self.content not in (MISSING, ""))
            or self.components not in (MISSING, [])
            or self.embeds not in (MISSING, [])
            or self.files
        )
