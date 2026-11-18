"""The fixture rule: every model has seed data in fixtures/dev, or a written reason it can't.

To add a model: give it rows in a fixtures/dev file (explicit pks and timestamps; dev_seed loads
the files in name order), or, for rows only the running code can make, an EXEMPT entry in
league/management/commands/check_fixtures.py.
"""

from __future__ import annotations

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import models

from league.management.commands import check_fixtures


def test_every_model_has_fixtures_or_a_reason() -> None:
    assert check_fixtures.problems() == []


def test_a_new_model_without_fixtures_is_refused() -> None:
    class Brand(models.Model):  # noqa: DJ008
        class Meta:
            app_label = "league"

    try:
        found = check_fixtures.problems()
        assert any(p.startswith("league.brand has no rows in fixtures/dev") for p in found)
        with pytest.raises(CommandError, match=r"league\.brand"):
            call_command("check_fixtures")
    finally:
        from django.apps import apps

        del apps.all_models["league"]["brand"]
        apps.clear_cache()


def test_the_fixtures_name_real_models() -> None:
    assert check_fixtures.fixture_models() >= {"league.community", "league.player"}
