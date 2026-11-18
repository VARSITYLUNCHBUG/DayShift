"""Stand-in for config.logging: the role commands tag their log lines with the process's name."""

from __future__ import annotations


def set_process(**fields: str) -> None:
    """Nothing to tag: the stand-in's log lines are plain prints."""
