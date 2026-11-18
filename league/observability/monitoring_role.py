"""The database role the Postgres and pgbouncer exporters log in as: `draftbot_monitor`.

It can read Postgres's statistics (the built-in `pg_monitor` role) and nothing else: no tables, no
writes, no superuser. migrate runs this after the migrations, over its direct connection, so the
role exists and has the current password on a new database volume and on an existing one alike
(Postgres's init scripts only ever run on a new one):

    python -m league.observability.monitoring_role

The password is `DB_MONITOR_PASSWORD`. Without it nothing changes, so a stack without the
observability overlay has no such role. Postgres is sent a SCRAM-SHA-256 verifier computed here,
never the password itself, so it can't appear in a statement log.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import re

logger = logging.getLogger(__name__)

ROLE = "draftbot_monitor"
ITERATIONS = 4096  # Postgres's own default, scram_iterations.


def scram_verifier(password: str, *, salt: bytes | None = None) -> str:
    """The `SCRAM-SHA-256$…` secret Postgres stores for `password` (RFC 5802, RFC 7677)."""
    salt = salt if salt is not None else os.urandom(16)
    salted = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    client_key = hmac.new(salted, b"Client Key", "sha256").digest()
    stored_key = hashlib.sha256(client_key).digest()
    server_key = hmac.new(salted, b"Server Key", "sha256").digest()

    def b64(raw: bytes) -> str:
        return base64.b64encode(raw).decode()

    return f"SCRAM-SHA-256${ITERATIONS}:{b64(salt)}${b64(stored_key)}:{b64(server_key)}"


def ensure(password: str, role: str = ROLE) -> None:
    """Create `role` if it's missing, then set its attributes, password and pg_monitor."""
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
            " NOBYPASSRLS INHERIT CONNECTION LIMIT 5 PASSWORD %s",
            [scram_verifier(password)],
        )
        cursor.execute(f"GRANT pg_monitor TO {role}")


def main() -> None:
    password = os.environ.get("DB_MONITOR_PASSWORD", "")
    # Another name for the test suite only: the exporters and pgbouncer name draftbot_monitor.
    role = os.environ.get("DB_MONITOR_ROLE") or ROLE
    if not password:
        logger.info("No DB_MONITOR_PASSWORD: the monitoring role is left as it is")
        return
    ensure(password, role)
    logger.info("The monitoring role is ready", extra={"role": role})


if __name__ == "__main__":
    import django

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    django.setup()
    from config.logging import set_process

    set_process(service="migrate")
    main()
