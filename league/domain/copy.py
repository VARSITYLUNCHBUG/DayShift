"""What players read when they click: in Bebot's words where Bebot said it, the same everywhere.

The community knows these from Bebot, so the ranked flow and scrims share them. Staff-facing and
rarer messages stay where they're raised.
"""

from __future__ import annotations


def plural(count: int, word: str, many: str = "") -> str:
    """ "1 game", "3 games": the count and the word that fits it. `many` for irregular plurals."""
    return f"{count} {word if count == 1 else many or word + 's'}"


# Queue and ready check.
ALREADY_QUEUED = "You're already in queue!"
NOT_QUEUED = "You're not in queue!"
ALREADY_READY = "You're already ready!"

# Captains.
CANT_CAPTAIN_BOTH = "You can't captain both sides!"
CAPTAINS_CHOSEN = "Captain selection is already complete!"
ONLY_CAPTAINS_START = "Only the captains can start the draft."
SAME_PLAYER_COINFLIP = "You can't flip a coin between the same player!"


def has_captain(team: str) -> str:
    return f"{team} already has a captain!"


def already_captain(team: str) -> str:
    return f"You are already the captain of {team}!"


def now_captain(team: str) -> str:
    return f"You are now captain of {team}!"


def coinflip_only(who: str) -> str:
    """`who` is "winner" or "loser"."""
    return f"Only the coinflip {who} can make this choice!"


# Drafting.
SELECTION_BUSY = "Selection is already being processed."
STEP_TAKEN = "Too late: that step has already been taken."
PLAYER_TAKEN = "That player has already been picked."
NOT_TAKING_SELECTIONS = "Draft is no longer accepting selections."
NO_HEROES = "No available heroes to pick from."


def not_your_turn(action: str) -> str:
    """`action` is a plan step's: "ban", "pick", or "player_pick" for the player draft."""
    verb = "pick a player" if action == "player_pick" else action
    return f"It's not your turn to {verb}."


def hero_taken(name: str) -> str:
    return f"{name} has already been picked or banned."


# Scrim drafts.
DRAFT_STOPPED = "Draft stopped successfully."
NO_DRAFT_HERE = "No draft is currently in progress in this channel!"
DRAFT_RUNNING_HERE = "A draft is already running in this channel. Use /stopdraft first."
