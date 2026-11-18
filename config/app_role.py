"""The database role web, bot and scheduler log in as: `draftbot_app`.

It may read and write the app's tables and use their sequences, and owns nothing: no DDL, no
superuser, so it can't COPY ... FROM PROGRAM, read the server's files or change other roles.
Postgres's bootstrap superuser (`draftbot`) stays migrate's and the operator's. migrate runs this
after the migrations, over its direct connection, so the role exists with the current password
and grants on a new database volume and on an existing one alike:

    python -m config.app_role

The password is `DB_APP_PASSWORD`. Without it nothing changes (a dev or test stack, where the app
logs in as the superuser). Tables a later migration creates are covered too: their owner's
default privileges grant them to this role. As with the monitoring role, Postgres is sent a
SCRAM-SHA-256 verifier computed here, never the password itself.
"""

from __future__ import annotations

import logging
import os
import re

from league.observability.monitoring_role import scram_verifier

logger = logging.getLogger(__name__)

ROLE = "draftbot_app"
TABLES = "SELECT, INSERT, UPDATE, DELETE"
SEQUENCES = "USAGE, SELECT, UPDATE"


def ensure(password: str, role: str = ROLE) -> None:
    """Create `role` if it's missing, then set its attributes, password and grants."""
    from django.db import connection, transaction

    if not re.fullmatch(r"[a-z_][a-z0-9_]*", role):
        raise ValueError(f"Not a plain role name: {role!r}")
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            f"""
            DO $$ BEGIN
                IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '{role}') THEN
                    CREATE ROLE {role};
                END IF;
            END $$
            """
        )
        cursor.execute(
            f"ALTER ROLE {role} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION"
            " NOBYPASSRLS INHERIT PASSWORD %s",
            [scram_verifier(password)],
        )
        cursor.execute(f"GRANT USAGE ON SCHEMA public TO {role}")
        cursor.execute(f"GRANT {TABLES} ON ALL TABLES IN SCHEMA public TO {role}")
        cursor.execute(f"GRANT {SEQUENCES} ON ALL SEQUENCES IN SCHEMA public TO {role}")
        # For whatever the migrations' role (this connection's) creates from now on.
        cursor.execute(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT {TABLES} ON TABLES TO {role}"
        )
        cursor.execute(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT {SEQUENCES} ON SEQUENCES TO {role}"
        )


def main() -> None:
    password = os.environ.get("DB_APP_PASSWORD", "")
    # Another name for the test suite only: compose's URLs name draftbot_app.
    role = os.environ.get("DB_APP_ROLE") or ROLE
    if not password:
        logger.info("No DB_APP_PASSWORD: the app's role is left as it is")
        return
    ensure(password, role)
    logger.info("The app's role is ready", extra={"role": role})


if __name__ == "__main__":
    import django

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    django.setup()
    from config.logging import set_process

    set_process(service="migrate")
    main()
