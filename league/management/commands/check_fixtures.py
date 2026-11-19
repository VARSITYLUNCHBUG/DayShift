"""Every model has seed data in fixtures/dev, or a written reason why it can't.

A new model fails this until it gets rows in a fixtures/dev file (loaded by `dev_seed`, so the
dev stack and its tests start with it) or an entry in EXEMPT saying where its rows come from.
The pre-commit hook and tests/test_fixtures.py run it.

    python manage.py check_fixtures
"""

from __future__ import annotations

import json
from typing import Any

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

FIXTURES = settings.BASE_DIR / "fixtures" / "dev"
APPS = ("league", "devtools")

_PRESETS = "load_presets writes it from presets/ on every migrate"
_SEEDED = "dev_seed derives it from the fixtures (see fixtures/dev/README.md)"
_PLAYED = "written as matches are played: the dev stack's autopilot and scenarios make it"
_LEDGER = "an append-only ledger row the rating code writes, never loaded"
_OUTBOX = "a queue of Discord work, written by the code as it runs"
_RUNTIME = "short-lived state of a live queue or match"
_DEVTOOLS = "dev control state the control API writes while you drive a match"

# Models whose rows don't belong in a fixture, and why. Keep it short: a model that is
# configuration, or that a dev stack needs from its first click, belongs in fixtures/dev instead.
EXEMPT: dict[str, str] = {
    "league.champion": _PRESETS,
    "league.draftmodeversion": _PRESETS,
    "league.playerrating": _SEEDED,
    "league.captainoverride": _SEEDED,
    "league.ratingrun": _LEDGER,
    "league.ratingevent": _LEDGER,
    "league.outboxeffect": _OUTBOX,
    "league.queueentry": _RUNTIME,
    "league.prioentry": _RUNTIME,
    "league.match": _PLAYED,
    "league.matchparticipant": _PLAYED,
    "league.matchresource": _PLAYED,
    "league.matchtransition": _PLAYED,
    "league.draftaction": _PLAYED,
    "league.captainvote": _PLAYED,
    "league.earlyleave": _PLAYED,
    "league.subrequest": _PLAYED,
    "league.suboffer": _PLAYED,
    "league.playerswap": _PLAYED,
    "league.resultsubmission": _PLAYED,
    "league.matchresult": _PLAYED,
    "league.matchaward": _PLAYED,
    "league.scoreboardread": _PLAYED,
    "league.playermatchstat": _PLAYED,
    "league.playeralias": _PLAYED,
    "league.apimatchcheck": _PLAYED,
    "league.staffalert": _PLAYED,
    "league.penalty": _PLAYED,
    "league.strikeadjustment": "a staff correction to a player's strikes, made from Discord",
    "league.interimrating": "the NeatQueue import, uploaded as a CSV in the admin",
    "league.interimpointschange": "rebuilt from the NeatQueue import on every result",
    "devtools.matchscript": _DEVTOOLS,
    "devtools.frozenmatch": _DEVTOOLS,
    "devtools.frozentimer": _DEVTOOLS,
    "devtools.devflag": _DEVTOOLS,
}


def fixture_models() -> set[str]:
    """The models fixtures/dev holds rows of, as `app.model` labels."""
    found: set[str] = set()
    for path in sorted(FIXTURES.glob("*.json")):
        rows: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
        found.update(str(row["model"]).lower() for row in rows)
    return found


def problems() -> list[str]:
    """What breaks the rule, one line each. Empty when every model is covered."""
    models = {
        model._meta.label_lower
        for app in APPS
        if apps.is_installed(app)
        for model in apps.get_app_config(app).get_models()
    }
    covered = fixture_models()
    found = [
        f"{label} has no rows in fixtures/dev. Add some (see fixtures/dev/README.md), or an EXEMPT"
        " entry in league/management/commands/check_fixtures.py saying where its rows come from."
        for label in sorted(models - covered - EXEMPT.keys())
    ]
    found += [
        f"{label} is exempt but has fixtures: drop it from EXEMPT."
        for label in sorted(covered & EXEMPT.keys())
    ]
    found += [
        f"EXEMPT names {label}, which isn't a model." for label in sorted(EXEMPT.keys() - models)
    ]
    found += [
        f"fixtures/dev has rows of {label}, which isn't a model."
        for label in sorted(covered - models)
    ]
    return found


class Command(BaseCommand):
    help = "Check that every model has rows in fixtures/dev, or a written reason it can't."
    requires_system_checks = ()

    def handle(self, *args: Any, **options: Any) -> None:
        if not apps.is_installed("devtools"):
            raise CommandError("Run with DEBUG=true DEV_CONTROL=true, so devtools' models count.")
        found = problems()
        if found:
            raise CommandError("\n".join(found))
        self.stdout.write(f"Every model is covered by fixtures/dev or EXEMPT ({len(EXEMPT)}).")
