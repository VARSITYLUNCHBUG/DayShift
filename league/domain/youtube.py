"""YouTube links, for the landing page's advert: the video's ID, from any of the usual links."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtube-nocookie.com",
          "www.youtube-nocookie.com"}  # fmt: skip


def video_id(url: str) -> str | None:
    """The 11-character video ID of a youtube.com watch, shorts, embed or live link, or a
    youtu.be one. None for anything else."""
    parts = urlsplit(url.strip())
    if parts.scheme not in {"http", "https"}:
        return None
    host = (parts.hostname or "").lower()
    path = [piece for piece in parts.path.split("/") if piece]
    found: str | None = None
    if host == "youtu.be" and path:
        found = path[0]
    elif host in _HOSTS:
        if path[:1] == ["watch"]:
            found = (parse_qs(parts.query).get("v") or [""])[0]
        elif len(path) >= 2 and path[0] in {"shorts", "embed", "live"}:
            found = path[1]
    return found if found and _ID.match(found) else None
