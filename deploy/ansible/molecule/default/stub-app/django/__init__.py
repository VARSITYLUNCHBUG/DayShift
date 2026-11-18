"""Stand-in for the slice of Django the app's database role commands use, over psycopg.

prepare.yml copies the real league/observability/monitoring_role.py and config/app_role.py into
the stand-in image, so the migrate job runs the app's own code to create draftbot_monitor and
draftbot_app (and verify.yml's rotation tests check that code, not a copy). Those modules need
only `django.setup()`, `django.db.connection.cursor()` and `django.db.transaction.atomic()`.
"""

from __future__ import annotations


def setup() -> None:
    """Nothing to set up: the connection reads DATABASE_URL when it is first used."""
