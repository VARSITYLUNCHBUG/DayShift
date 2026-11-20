"""Expands a mode into one flat, continuously indexed list of single actions.

`draft_actions.step_index` and `matches.step_index` index into this list. The unique key on
(match, step_index) is what stops double clicks, so each entry is exactly one action.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from league.domain.mode_schema import DraftMode

Action = Literal["player_pick", "ban", "pick"]
Role = Literal["first", "second"]


@dataclass(frozen=True, slots=True)
class PlanStep:
    index: int
    action: Action
    role: Role
    seconds: int


def build_plan(mode: DraftMode) -> tuple[PlanStep, ...]:
    steps: list[PlanStep] = []
    for letter in mode.player_draft.order:
        role: Role = "first" if letter == "F" else "second"
        steps.append(PlanStep(len(steps), "player_pick", role, mode.player_draft.seconds))
    for step in mode.champion_draft.steps:
        seconds = step.seconds or mode.champion_draft.seconds
        for _ in range(step.count):
            steps.append(PlanStep(len(steps), step.action, step.team, seconds))
    return tuple(steps)


def player_draft_length(mode: DraftMode) -> int:
    return len(mode.player_draft.order)


# A captain's first pick opens the draft, with the whole lobby to read: it gets this many times
# the usual time. Every later pick, a double's second included, gets the usual.
FIRST_PICK_TIME_FACTOR = 2


def player_pick_seconds(mode: DraftMode, index: int) -> int:
    """How long the player draft's pick `index` has. Each pick starts its own clock."""
    order = mode.player_draft.order
    seconds = mode.player_draft.seconds
    first_of_captain = order.index(order[index]) == index
    return seconds * FIRST_PICK_TIME_FACTOR if first_of_captain else seconds


def champion_plan(mode: DraftMode) -> tuple[PlanStep, ...]:
    """Just the bans and picks, indexed from 0: what a scrim drafts."""
    champion_steps = build_plan(mode)[player_draft_length(mode) :]
    return tuple(
        PlanStep(index, step.action, step.role, step.seconds)
        for index, step in enumerate(champion_steps)
    )


def team_for_role(role: Role, first_team: str) -> str:
    """Map a mode's first/second role to a concrete team, A or B."""
    if first_team not in {"A", "B"}:
        raise ValueError(f"Unknown team {first_team!r}")
    if role == "first":
        return first_team
    return "B" if first_team == "A" else "A"
