"""`django.db.transaction.atomic()`: one transaction, committed on success, rolled back on error."""

from __future__ import annotations

from contextlib import AbstractContextManager


def atomic() -> AbstractContextManager[object]:
    """The connection's transaction (psycopg starts one, and commits or rolls it back)."""
    from django.db import connection

    return connection.raw().transaction()
