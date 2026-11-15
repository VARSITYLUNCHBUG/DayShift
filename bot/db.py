"""The bot's name for the async-to-sync boundary, which lives in `league.asyncdb`."""

from __future__ import annotations

from league.asyncdb import db

__all__ = ["db"]
