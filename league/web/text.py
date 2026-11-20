"""Service messages are written for Discord. The web shows them as plain text.

Discord renders `<t:...>` timestamps in the reader's own time zone; a plain string can't, so a
time becomes UTC ("20:15 UTC") and a relative one a phrase against now ("in 3 minutes"). Pages
that count down use the structured times in the snapshot, not this text.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime

from league.services import common

_TIMESTAMP = re.compile(r"<t:(-?\d+)(?::([tTdDfFR]))?>")
_USER = re.compile(r"<@!?(\d+)>")
_ROLE_OR_CHANNEL = re.compile(r"<(?:@&|#)\d+>")
_EMOJI = re.compile(r"<a?:\w+:\d+>")
# Paired markup only, so a lone asterisk or underscore in a name survives.
_PAIRED = (
    re.compile(r"\*\*(.+?)\*\*"),
    re.compile(r"__(.+?)__"),
    re.compile(r"~~(.+?)~~"),
    re.compile(r"\|\|(.+?)\|\|"),
    re.compile(r"\*(\S(?:.*?\S)?)\*"),
)
_SPACES = re.compile(r"[ \t]{2,}")
_SPACE_BEFORE_PUNCT = re.compile(r" +([.,:;!?)])")


def _relative(moment: datetime, now: datetime) -> str:
    seconds = (moment - now).total_seconds()
    if abs(seconds) < 60:
        return "in under a minute" if seconds > 0 else "just now"
    size, unit = next(
        (size, unit)
        for size, unit in ((86_400, "day"), (3600, "hour"), (60, "minute"))
        if abs(seconds) >= size
    )
    count = round(abs(seconds) / size)
    words = f"{count} {unit}{'' if count == 1 else 's'}"
    return f"in {words}" if seconds > 0 else f"{words} ago"


def _time(moment: datetime, style: str, now: datetime) -> str:
    if style == "R":
        return _relative(moment, now)
    if style == "t":
        return moment.strftime("%H:%M UTC")
    if style == "T":
        return moment.strftime("%H:%M:%S UTC")
    if style == "d":
        return f"{moment.day} {moment:%b %Y}"
    if style == "D":
        return f"{moment.day} {moment:%B %Y}"
    if style == "F":
        return f"{moment:%A} {moment.day} {moment:%B %Y, %H:%M} UTC"
    return f"{moment.day} {moment:%b %Y, %H:%M} UTC"  # "f", Discord's default.


def plain(text: str, *, now: datetime | None = None, names: Mapping[int, str] | None = None) -> str:
    """Discord markup to plain text. User mentions become names from `names` when given, and are
    dropped otherwise, as are role and channel mentions and custom emoji."""
    moment = now or common.now()

    def timestamp(match: re.Match[str]) -> str:
        when = datetime.fromtimestamp(int(match.group(1)), tz=UTC)
        return _time(when, match.group(2) or "f", moment)

    def user(match: re.Match[str]) -> str:
        return (names or {}).get(int(match.group(1)), "")

    out = _TIMESTAMP.sub(timestamp, text)
    out = _USER.sub(user, out)
    out = _ROLE_OR_CHANNEL.sub("", out)
    out = _EMOJI.sub("", out)
    for pattern in _PAIRED:
        out = pattern.sub(r"\1", out)
    out = out.replace("`", "")
    out = _SPACES.sub(" ", out)
    out = _SPACE_BEFORE_PUNCT.sub(r"\1", out)
    return "\n".join(line.strip() for line in out.splitlines()).strip()
