"""Uploaded image and video checks: report screenshots and the landing page's advert. Upload
filters check only the extension, so check the bytes."""

from __future__ import annotations

import hashlib

# Discord's default per-file upload limit, documented on 3 September 2026.
MAX_IMAGE_BYTES = 20 * 1024 * 1024


def detect_image(data: bytes) -> str | None:
    """Return the file extension if these bytes are an image we accept."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "webp"
    return None


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# The landing page's advert (league/models/landing.py): staff uploads, served from our origin.
MAX_ADVERT_IMAGE_BYTES = 5 * 1024 * 1024
# Under the edge's 21 MB request limit (infra/caddy/Caddyfile). A longer video goes on YouTube.
MAX_ADVERT_VIDEO_BYTES = 20 * 1024 * 1024


def detect_advert_image(data: bytes) -> str | None:
    """An advert image's extension: a screenshot's kinds, or an animated GIF. Never SVG, which
    can carry script."""
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    return detect_image(data)


def detect_video(data: bytes) -> str | None:
    """A video's extension, from its first bytes: MP4 (an ISO `ftyp` box) or WebM (EBML)."""
    if data[4:8] == b"ftyp":
        return "mp4"
    if data.startswith(b"\x1a\x45\xdf\xa3"):
        return "webm"
    return None
