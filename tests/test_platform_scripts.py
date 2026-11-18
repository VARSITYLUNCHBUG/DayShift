"""The dev scripts' argument handling, and that clean_containers only ever names what it is asked
to. Each .sh has a .bat twin: on Windows both are run, so the two can't drift apart unnoticed."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ("test", "fixture_to_test", "clean_containers")
SH = shutil.which("sh")
WINDOWS = os.name == "nt"


def run(script: str, *args: str, shell: str) -> subprocess.CompletedProcess[str]:
    if shell == "sh":
        command = [SH or "sh", str(ROOT / "scripts" / f"{script}.sh"), *args]
    else:
        command = ["cmd", "/c", str(ROOT / "scripts" / f"{script}.bat"), *args]
    return subprocess.run(
        command, cwd=ROOT, capture_output=True, text=True, check=False, timeout=120
    )


SHELLS = [
    pytest.param("sh", marks=pytest.mark.skipif(SH is None, reason="no sh")),
    pytest.param("bat", marks=pytest.mark.skipif(not WINDOWS, reason="cmd.exe only")),
]


@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("script", SCRIPTS)
def test_help_exits_zero_and_shows_the_usage(script: str, shell: str) -> None:
    result = run(script, "--help", shell=shell)
    assert result.returncode == 0, result.stderr
    assert "Usage: scripts" in result.stdout


@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("script", SCRIPTS)
def test_an_unknown_argument_exits_two_with_the_usage(script: str, shell: str) -> None:
    result = run(script, "--no-such-flag", shell=shell)
    assert result.returncode == 2
    assert "--no-such-flag" in result.stderr
    assert "Usage: scripts" in result.stderr


@pytest.mark.parametrize("shell", SHELLS)
def test_local_is_refused_for_the_e2e_suite(shell: str) -> None:
    result = run("test", "e2e", "--local", shell=shell)
    assert result.returncode == 2
    assert "--local only applies to the unit suite" in result.stderr


def _docker_running() -> bool:
    if shutil.which("docker") is None:
        return False
    return subprocess.run(["docker", "info"], capture_output=True, check=False).returncode == 0


@pytest.mark.skipif(not _docker_running(), reason="needs a running Docker")
@pytest.mark.parametrize("shell", SHELLS)
def test_a_dry_run_names_only_the_projects_asked_for(shell: str) -> None:
    project = f"draftbot-scripts-test-{os.getpid()}"
    result = run("clean_containers", "--project", project, "--local-pg", "--dry-run", shell=shell)
    assert result.returncode == 0, result.stderr
    projects = [line for line in result.stdout.splitlines() if line.startswith("Project ")]
    assert projects == [f"Project {project}:", f"Project {project}-local:"]
    assert "Dry run: nothing was removed." in result.stdout
    # The default projects and the output folders are left out of a --project run.
    assert "draftbot-dev" not in result.stdout and "Output folders" not in result.stdout
