"""The control panel's vocabulary matches the control API it drives: the actions `act` takes, the
coinflip choices, the statuses `advance` stops at, the match script's keys, the lobby modes, and
the statuses the panel treats as over or open to swaps. A rename on either side fails here
rather than as a 400 in the panel."""

from __future__ import annotations

import re
from pathlib import Path

from devtools import autopilot, control
from league.domain.engine import RANKED_COINFLIP_CHOICES, TERMINAL
from league.services.swaps import SWAPPABLE

PANEL = Path(__file__).resolve().parents[1] / "services" / "control-panel" / "src"
CONTROL_TS = (PANEL / "api" / "control.ts").read_text(encoding="utf-8")
MATCH_TS = (PANEL / "lib" / "match.ts").read_text(encoding="utf-8")


def _strings(source: str, pattern: str) -> list[str]:
    """The string literals in the first block `pattern` matches."""
    found = re.search(pattern, source, re.DOTALL)
    assert found, f"Not found in the panel source: {pattern}"
    return re.findall(r'"([^"]*)"', found.group(1))


def test_the_actions_act_takes() -> None:
    panel = _strings(CONTROL_TS, r"export const ACTIONS = \[(.*?)\] as const")
    assert panel == list(autopilot.ACTIONS)


def test_the_coinflip_choices() -> None:
    panel = _strings(CONTROL_TS, r"export const COINFLIP_CHOICES = \[(.*?)\] as const")
    assert panel == list(RANKED_COINFLIP_CHOICES)


def test_the_statuses_advance_stops_at() -> None:
    panel = _strings(MATCH_TS, r"export const RANKED_FLOW = \[(.*?)\] as const")
    assert panel == list(autopilot.ORDER)


def test_terminal_and_swappable_statuses() -> None:
    terminal = _strings(MATCH_TS, r"export const TERMINAL = new Set\(\[(.*?)\]\)")
    swappable = _strings(MATCH_TS, r"export const SWAPPABLE = new Set\(\[(.*?)\]\)")
    assert set(terminal) == set(TERMINAL)
    assert set(swappable) == set(SWAPPABLE)


def test_the_match_script_keys() -> None:
    block = re.search(r"export interface MatchScript \{(.*?)\n\}", CONTROL_TS, re.DOTALL)
    assert block
    keys = re.findall(r"^\s+(\w+)\?:", block.group(1), re.MULTILINE)
    assert set(keys) == control.SCRIPT_KEYS


def test_the_lobby_modes() -> None:
    modes = _strings(CONTROL_TS, r"export type LobbyMode = (.*?);")
    assert modes == [control.CREATE, control.FAIL]
