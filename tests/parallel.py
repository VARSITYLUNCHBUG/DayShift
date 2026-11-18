"""Suite-wide setup that keeps runs fast, and parallel runs (pytest-xdist) repeatable.

Loaded from `tests/conftest.py`. Run in parallel with `pytest -n auto` (xdist's load mode).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import pytest
from django.apps import apps
from django.db import connection
from django.db.models.signals import post_migrate
from hypothesis import settings
from pytest_django import DjangoDbBlocker

ON_XDIST_WORKER = bool(os.environ.get("PYTEST_XDIST_WORKER"))

# Workers would otherwise share one `.hypothesis/` folder and replay each other's saved failures,
# so a run would depend on what ran before it on that machine.
settings.register_profile("xdist", database=None)
if ON_XDIST_WORKER:
    settings.load_profile("xdist")


def _seed_presets(**_: Any) -> None:
    """Publish the presets into the test database, once it is migrated and after every flush.

    Seeding them once costs a test nothing, where publishing them per test cost 0.4 s each.
    Plain tests roll back to this state, and the flush that ends a transactional test is
    followed by this again.
    """
    from tests.conftest import publish_presets

    publish_presets()


post_migrate.connect(_seed_presets, sender=apps.get_app_config("league"))


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup: None, django_db_blocker: DjangoDbBlocker) -> Iterator[None]:
    """Drop the test database even when a test left a connection open on another thread.

    Async tests reach the database from worker threads, and a connection one of them keeps would
    stop the drop at the end of the run. Each xdist worker has its own database, so this only
    ever ends sessions of the worker's own run.
    """
    yield
    with django_db_blocker.unblock(), connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity"
            " WHERE datname = current_database() AND pid <> pg_backend_pid()"
        )


def pytest_configure(config: pytest.Config) -> None:
    """Hand out tests one at a time, unless `--maxschedchunk` says otherwise.

    By default xdist's load mode gives each worker a run of neighbouring tests to start with, so
    one worker would get every long test that `pytest_collection_modifyitems` put first.
    """
    if getattr(config.option, "maxschedchunk", 0) is None:
        config.option.maxschedchunk = 1


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """In a parallel run, start the long tests first so none of them is left for the end."""
    if ON_XDIST_WORKER:
        items.sort(key=lambda item: item.get_closest_marker("slow") is None)
