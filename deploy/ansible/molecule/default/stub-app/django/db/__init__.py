"""`django.db.connection`: one psycopg connection to DATABASE_URL, opened when first used.

Client-side parameter binding, as Django's psycopg backend does by default, so `%s` works in
statements such as ALTER ROLE that take no server-side parameters.
"""

from __future__ import annotations

import os

import psycopg

from django.db import transaction


class Connection:
    """The default database connection, as far as the role commands use it."""

    def __init__(self) -> None:
        self._conn: psycopg.Connection[tuple[object, ...]] | None = None

    def raw(self) -> psycopg.Connection[tuple[object, ...]]:
        """The psycopg connection, opened on first use."""
        if self._conn is None:
            self._conn = psycopg.connect(
                os.environ["DATABASE_URL"], cursor_factory=psycopg.ClientCursor
            )
        return self._conn

    def cursor(self) -> psycopg.Cursor[tuple[object, ...]]:
        """A cursor, used as a context manager."""
        return self.raw().cursor()


connection = Connection()

__all__ = ["connection", "transaction"]
