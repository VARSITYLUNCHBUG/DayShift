"""Keeps every model on `default`: the `direct` alias (config/settings.py) is only ever used by
name, for a session of its own, and never gets migrations."""

from __future__ import annotations

from typing import Any


class DefaultOnly:
    def db_for_read(self, model: type, **hints: Any) -> str:
        return "default"

    def db_for_write(self, model: type, **hints: Any) -> str:
        return "default"

    def allow_relation(self, obj1: Any, obj2: Any, **hints: Any) -> bool:
        return True

    def allow_migrate(self, db: str, app_label: str, **hints: Any) -> bool:
        return db == "default"
