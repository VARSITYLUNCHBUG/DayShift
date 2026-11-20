"""Pure match rules: legal transitions, the captain vote, timeout choices and a format dry-run.

Nothing here touches Django or Discord, so every rule is testable in isolation. All randomness
comes from `seeded_rng`, so a match's outcomes can be reproduced from its stored seed.
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from league.domain.draft_plan import build_plan, team_for_role
from league.domain.errors import InvalidAction
from league.domain.mode_schema import DraftMode, ModeValidationError


class Status:
    READY_CHECK = "ready_check"
    CAPTAIN_PHASE = "captain_phase"
    # The captains confirm they're here before the player draft starts.
    CAPTAIN_CHECKIN = "captain_checkin"
    PLAYER_DRAFT = "player_draft"
    COINFLIP = "coinflip"
    # Both captains look over the teams, swapping players if they like, before the hero draft.
    TEAM_CONFIRM = "team_confirm"
    CHAMPION_DRAFT = "champion_draft"
    LOBBY_CODE = "lobby_code"
    IN_PROGRESS = "in_progress"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    DISPUTED = "disputed"
    COMPLETED = "completed"
    VOIDED = "voided"
    # Scrims only: claiming a side, waiting for Start Draft after the coinflip, and done at GLHF.
    CAPTAIN_CLAIM = "captain_claim"
    READY_TO_DRAFT = "ready_to_draft"
    DRAFTED = "drafted"


TERMINAL = frozenset({Status.COMPLETED, Status.VOIDED, Status.DRAFTED})
LIVE = frozenset(
    {
        Status.READY_CHECK,
        Status.CAPTAIN_PHASE,
        Status.CAPTAIN_CHECKIN,
        Status.PLAYER_DRAFT,
        Status.COINFLIP,
        Status.TEAM_CONFIRM,
        Status.CHAMPION_DRAFT,
        Status.LOBBY_CODE,
        Status.IN_PROGRESS,
        Status.AWAITING_CONFIRMATION,
        Status.DISPUTED,
    }
)
# A scrim holds its channel while it's in one of these.
SCRIM_LIVE = frozenset(
    {Status.CAPTAIN_CLAIM, Status.COINFLIP, Status.READY_TO_DRAFT, Status.CHAMPION_DRAFT}
)
# Every status with a timer the poller runs, ranked or scrim.
TIMED = LIVE | SCRIM_LIVE
SIDE_LABELS = {"hk": "The Hidden King", "am": "The Archmother"}

_TRANSITIONS: dict[str, frozenset[str]] = {
    Status.READY_CHECK: frozenset({Status.CAPTAIN_PHASE, Status.VOIDED}),
    Status.CAPTAIN_PHASE: frozenset({Status.CAPTAIN_CHECKIN, Status.VOIDED}),
    Status.CAPTAIN_CHECKIN: frozenset({Status.PLAYER_DRAFT, Status.VOIDED}),
    Status.PLAYER_DRAFT: frozenset({Status.COINFLIP, Status.VOIDED}),
    Status.COINFLIP: frozenset({Status.TEAM_CONFIRM, Status.VOIDED}),
    Status.TEAM_CONFIRM: frozenset({Status.CHAMPION_DRAFT, Status.VOIDED}),
    Status.CHAMPION_DRAFT: frozenset({Status.LOBBY_CODE, Status.VOIDED}),
    Status.LOBBY_CODE: frozenset({Status.IN_PROGRESS, Status.VOIDED}),
    Status.IN_PROGRESS: frozenset({Status.AWAITING_CONFIRMATION, Status.DISPUTED, Status.VOIDED}),
    Status.AWAITING_CONFIRMATION: frozenset({Status.COMPLETED, Status.DISPUTED, Status.VOIDED}),
    Status.DISPUTED: frozenset({Status.COMPLETED, Status.VOIDED}),
    # A completed match can be voided or rescored only through the correction path.
    Status.COMPLETED: frozenset({Status.VOIDED}),
    Status.VOIDED: frozenset({Status.COMPLETED}),
}


_SCRIM_TRANSITIONS: dict[str, frozenset[str]] = {
    # /startdraft: both captains claimed, straight into the draft.
    Status.CAPTAIN_CLAIM: frozenset({Status.CHAMPION_DRAFT, Status.VOIDED}),
    # /captains_coinflip: both chose, then a captain presses Start Draft.
    Status.COINFLIP: frozenset({Status.READY_TO_DRAFT, Status.VOIDED}),
    Status.READY_TO_DRAFT: frozenset({Status.CHAMPION_DRAFT, Status.VOIDED}),
    Status.CHAMPION_DRAFT: frozenset({Status.DRAFTED, Status.VOIDED}),
}


def can_transition(current: str, target: str, kind: str = "ranked") -> bool:
    table = _SCRIM_TRANSITIONS if kind == "scrim" else _TRANSITIONS
    return target in table.get(current, frozenset())


def seeded_rng(seed: int, purpose: str) -> random.Random:
    """A separate stream per decision, so adding a decision later cannot shift earlier ones."""
    return random.Random(f"{seed}:{purpose}")


@dataclass(frozen=True, slots=True)
class CaptainCandidate:
    player_id: int
    rating: int
    games: int
    eligible: bool = True  # Meets the mode's captain rule, or staff allowed them.
    experience: int = 0  # Completed matches in this server, across seasons.


def rank_captains(
    votes: Mapping[int, int], candidates: Sequence[CaptainCandidate], seed: int
) -> list[int]:
    """Every candidate in captain order, best first.

    Eligible players come first. Among them, most votes first; ties go to higher rating, then
    more games, then a seeded shuffle, so a short vote is filled by rating. The ineligible follow,
    by the most completed matches, then rating.
    """
    rng = seeded_rng(seed, "captain-vote")
    ordered_input = sorted(candidates, key=lambda c: c.player_id)
    tiebreak = {c.player_id: rng.random() for c in ordered_input}

    def key(c: CaptainCandidate) -> tuple[bool, int, int, int, int, float]:
        votes_for = votes.get(c.player_id, 0) if c.eligible else 0
        experience = 0 if c.eligible else c.experience
        return (not c.eligible, -votes_for, -experience, -c.rating, -c.games, tiebreak[c.player_id])

    return [c.player_id for c in sorted(ordered_input, key=key)]


def tally_captain_votes(
    votes: Mapping[int, int], candidates: Sequence[CaptainCandidate], seed: int
) -> tuple[int, int]:
    """Return (team A captain, team B captain) from a captain vote: the top two of
    `rank_captains`. If fewer than two are eligible, the rest are filled by the most completed
    matches, then rating."""
    if len(candidates) < 2:
        raise ValueError("Need at least two candidates.")
    ranked = rank_captains(votes, candidates, seed)
    return ranked[0], ranked[1]


DRAFT_NAME_ADJECTIVES = (
    "Crimson", "Azure", "Golden", "Silver", "Shadow", "Blazing", "Frozen", "Thunder", "Savage",
    "Mystic", "Ancient", "Furious", "Silent", "Fierce", "Radiant", "Obsidian", "Emerald",
    "Scarlet", "Iron", "Ivory", "Wild", "Grim", "Noble", "Ghost", "Storm", "Feral", "Rogue",
    "Midnight", "Arcane", "Molten", "Verdant", "Crystal", "Vicious", "Hallowed", "Relentless",
    "Burning", "Glacial", "Venomous",
)  # fmt: skip
DRAFT_NAME_NOUNS = (
    "Eagle", "Wolf", "Dragon", "Viper", "Tiger", "Phoenix", "Raven", "Kraken", "Falcon", "Bear",
    "Hydra", "Panther", "Cobra", "Hawk", "Lion", "Jaguar", "Stag", "Fox", "Serpent", "Griffin",
    "Rhino", "Bison", "Stallion", "Hound", "Otter", "Warden", "Marauder", "Sentinel", "Berserker",
    "Reaver", "Juggernaut", "Specter", "Wyrm", "Basilisk", "Leviathan", "Chimera",
)  # fmt: skip


def draft_name(seed: int) -> str:
    """A name for the match's draft, such as "Crimson Wolf". The same seed gives the same name."""
    rng = seeded_rng(seed, "draft-name")
    return f"{rng.choice(DRAFT_NAME_ADJECTIVES)} {rng.choice(DRAFT_NAME_NOUNS)}"


def pick_gif(seed: int, gifs: Sequence[str]) -> str | None:
    if not gifs:
        return None
    return seeded_rng(seed, "draft-gif").choice(list(gifs))


def first_pick_team(rating_a: int, rating_b: int, seed: int) -> str:
    """Which team, A or B, makes the first player pick: the lower-rated captain's. A tie is a
    seeded coin flip."""
    if rating_a == rating_b:
        return coin_flip_team(seed, "first-pick:")
    return "A" if rating_a < rating_b else "B"


def coin_flip_team(seed: int, purpose: str) -> str:
    return seeded_rng(seed, purpose).choice(["A", "B"])


# --- Captain coinflip -------------------------------------------------------------------------
# Scrims use Bebot's: the winner chooses First Pick, Last Pick or a side; the loser chooses from
# the other kind. Between them, both the sides and who bans and picks first are settled.

FIRST_PICK = "first_pick"
LAST_PICK = "last_pick"
HIDDEN_KING = "hidden_king"
ARCHMOTHER = "archmother"
ORDER_CHOICES = (FIRST_PICK, LAST_PICK)
SIDE_CHOICES = (HIDDEN_KING, ARCHMOTHER)
# Ranked matches: the winner only chooses a side. The Hidden King is always Pick 1, the team that
# bans and picks first. Scrims keep Bebot's two-captain coinflip.
RANKED_COINFLIP_CHOICES = (HIDDEN_KING, ARCHMOTHER)
COINFLIP_LABELS = {
    FIRST_PICK: "First Pick",
    LAST_PICK: "Last Pick",
    HIDDEN_KING: "Hidden King",
    ARCHMOTHER: "Archmother",
}
_SIDE_OF = {HIDDEN_KING: "hk", ARCHMOTHER: "am"}


def other_side(side: str) -> str:
    return "am" if side == "hk" else "hk"


def coinflip_options(winner_choice: str, *, ranked: bool = False) -> tuple[str, ...]:
    """What the chooser on turn can press. Ranked: the winner's two sides. Scrims: any of four
    for the winner, the other kind after."""
    if ranked:
        return () if winner_choice else RANKED_COINFLIP_CHOICES
    if not winner_choice:
        return (FIRST_PICK, LAST_PICK, HIDDEN_KING, ARCHMOTHER)
    return SIDE_CHOICES if winner_choice in ORDER_CHOICES else ORDER_CHOICES


def apply_ranked_coinflip(winner_team: str, choice: str) -> tuple[str, str]:
    """(Hidden King team, team that bans and picks first) from the ranked winner's side. The
    Hidden King always bans and picks first."""
    if choice not in RANKED_COINFLIP_CHOICES:
        raise ValueError(f"Not a ranked coinflip choice: {choice!r}")
    loser_team = "B" if winner_team == "A" else "A"
    hidden_king = winner_team if choice == HIDDEN_KING else loser_team
    return hidden_king, hidden_king


def settle_coinflip(winner_choice: str, loser_choice: str) -> tuple[str, str, str]:
    """Turn the two choices into (winner's side, loser's side, side that goes first), with
    sides as "hk" and "am". One captain chose an order and the other a side."""
    winner_side = _SIDE_OF.get(winner_choice)
    loser_side = _SIDE_OF.get(loser_choice)
    if winner_side is None:
        if loser_side is None:
            raise ValueError("One of the two choices must be a side.")
        winner_side = other_side(loser_side)
    if loser_side is None:
        loser_side = other_side(winner_side)
    chose_order = winner_choice if winner_choice in ORDER_CHOICES else loser_choice
    chooser_side = winner_side if winner_choice in ORDER_CHOICES else loser_side
    first = chooser_side if chose_order == FIRST_PICK else other_side(chooser_side)
    return winner_side, loser_side, first


def auto_coinflip_choice(seed: int, winner_choice: str, *, ranked: bool = False) -> str:
    """A captain who runs out of time gets a random choice, seeded like every timeout."""
    turn = "loser" if winner_choice else "winner"
    options = coinflip_options(winner_choice, ranked=ranked)
    return seeded_rng(seed, f"coinflip:{turn}").choice(options)


def apply_coinflip(winner_team: str, winner_choice: str, loser_choice: str) -> tuple[str, str]:
    """(Hidden King team, team that bans and picks first), for teams "A" and "B"."""
    loser_team = "B" if winner_team == "A" else "A"
    winner_side, _loser_side, first_side = settle_coinflip(winner_choice, loser_choice)
    hidden_king = winner_team if winner_side == "hk" else loser_team
    first_pick = winner_team if winner_side == first_side else loser_team
    return hidden_king, first_pick


@dataclass(frozen=True, slots=True)
class DraftablePlayer:
    player_id: int
    rating: int


def auto_player_pick(
    undrafted: Sequence[DraftablePlayer], rule: str, seed: int, step_index: int
) -> int:
    """The timeout pick: highest rated (lowest ID breaks ties, so it is reproducible) or random."""
    if not undrafted:
        raise InvalidAction("Nobody is left to draft.")
    if rule == "auto_random":
        ordered = sorted(p.player_id for p in undrafted)
        return seeded_rng(seed, f"auto-player:{step_index}").choice(ordered)
    return min(undrafted, key=lambda p: (-p.rating, p.player_id)).player_id


def auto_champion(available: Sequence[int], seed: int, step_index: int) -> int:
    if not available:
        raise InvalidAction("No champions are left.")
    return seeded_rng(seed, f"auto-champion:{step_index}").choice(sorted(available))


def dry_run(mode: DraftMode, champion_pool: Sequence[int]) -> None:
    """Walk the format's plan and check it can finish with this pool, assuming every ban lands.

    Raises ModeValidationError if it cannot.
    """
    pool = set(champion_pool) - set(mode.champion_draft.excluded_champion_ids)
    if len(pool) < mode.champions_consumed_max:
        raise ModeValidationError(
            [
                f"champion_draft.steps: needs {mode.champions_consumed_max} champions, "
                f"but only {len(pool)} are enabled and not excluded"
            ]
        )
    rosters = {"A": 1, "B": 1}
    picks = {"A": 0, "B": 0}
    for step in build_plan(mode):
        team = team_for_role(step.role, "A")
        if step.action == "player_pick":
            rosters[team] += 1
        elif step.action == "pick":
            picks[team] += 1
    if set(rosters.values()) != {mode.team_size} or set(picks.values()) != {mode.team_size}:
        raise ModeValidationError(
            [f"format does not produce {mode.team_size} players and champions per team"]
        )
