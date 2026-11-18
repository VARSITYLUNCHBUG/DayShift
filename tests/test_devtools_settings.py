"""The dev block of the settings: what needs DEBUG, and where a dev stack's lobbies come from.

Each test imports the settings in a fresh interpreter, because they are read once at import.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Variables a developer's shell or the test runner may have set, which would change the result.
CLEARED = ("DEBUG", "DEV_CONTROL", "DISCORD_SIM_URL", "DEADLOCK_API_BASE")
SIM = "http://discord-sim:8090"
READ = (
    "import json, config.settings as s; "
    "print(json.dumps({'urls': s.ROOT_URLCONF, 'deadlock_api': s.DEADLOCK_API_BASE}))"
)


def run(code: str, **env: str) -> subprocess.CompletedProcess[str]:
    """Run `code` in a fresh interpreter in the repo, with these environment variables."""
    base = {key: value for key, value in os.environ.items() if key not in CLEARED}
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env={**base, "DJANGO_SECRET_KEY": "test", **env},
        capture_output=True,
        text=True,
        check=False,
    )


def read(**env: str) -> dict[str, str]:
    result = run(READ, **env)
    assert result.returncode == 0, result.stderr
    loaded: dict[str, str] = json.loads(result.stdout)
    return loaded


def test_the_dev_features_are_refused_outside_debug() -> None:
    for name, value, message in (
        ("DEV_CONTROL", "true", "DEV_CONTROL only works with DEBUG on"),
        ("DISCORD_SIM_URL", SIM, "DISCORD_SIM_URL only works with DEBUG on"),
    ):
        refused = run("import config.settings", DEBUG="false", **{name: value})
        assert refused.returncode != 0, name
        assert message in refused.stderr


def test_the_control_api_is_routed_only_with_dev_control() -> None:
    assert read(DEBUG="true")["urls"] == "config.urls"
    assert read(DEBUG="true", DEV_CONTROL="true")["urls"] == "config.urls_dev"


def test_against_the_simulator_lobbies_come_from_its_stand_in() -> None:
    assert read(DEBUG="false")["deadlock_api"] == "https://api.deadlock-api.com"
    assert read(DEBUG="true", DISCORD_SIM_URL=SIM + "/")["deadlock_api"] == SIM + "/deadlock-api"
    # One set on purpose is kept, the real service included.
    real = "https://api.deadlock-api.com"
    assert read(DEBUG="true", DISCORD_SIM_URL=SIM, DEADLOCK_API_BASE=real)["deadlock_api"] == real
