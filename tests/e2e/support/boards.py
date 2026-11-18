"""What the bot posted in the simulated guild: match boards and result posts."""

from __future__ import annotations

import re

from support.api import JSON, ControlApi, SimApi, text_of, wait_for

# The board's title per status (bot/renderers/board.py STATUS_TITLES). The champion draft has
# Bebot's title instead, "🏆 Draft #<match>: <name> 🏆".
BOARD_TITLES = {
    "ready_check": "Ready check",
    "captain_phase": "Captain vote",
    "captain_checkin": "Captains check in",
    "player_draft": "Player draft",
    "coinflip": "Captain coinflip",
    "lobby_code": "Lobby code",
    "in_progress": "Game on",
    "awaiting_confirmation": "Confirm the result",
    "disputed": "Disputed: waiting for staff",
}

# A result post's rating line: "> **+54** | __1954__ | <@1100000000000000123>", padded with
# figure spaces (bot/renderers/results.py).
RATING_LINE = re.compile(r"\*\*([+-]\d+)\*\* \| \u2007*__(\d+)__ \| <@(\d+)>")


def board_heading(match_id: int, status: str) -> str:
    if status == "champion_draft":
        return f"## 🏆 Draft #{match_id}"
    return f"## Match #{match_id}: {BOARD_TITLES[status]}"


def board(sim: SimApi, channel_id: str, match_id: int) -> JSON | None:
    """The match's board: the newest message in its channel with a board heading."""
    prefixes = (f"## Match #{match_id}:", f"## 🏆 Draft #{match_id}")
    for message in sim.messages(channel_id):
        if text_of(message).startswith(prefixes):
            return message
    return None


def wait_board(sim: SimApi, control: ControlApi, match_id: int) -> tuple[JSON, JSON]:
    """The match and its board, once the board shows the match's current status.

    The bot renders boards from its outbox a moment after each change, and moves a match on by
    itself in places (deadlock-api settles the lobby), so this reads both until they agree.
    """

    def agreed() -> tuple[JSON, JSON] | None:
        match = control.match(match_id)
        shown = board(sim, match["text_channel_id"], match_id)
        if shown and text_of(shown).startswith(board_heading(match_id, match["status"])):
            return match, shown
        return None

    return wait_for(agreed, f"the board of match {match_id} to show its status")


def result_post(sim: SimApi, results_channel: str, match_id: int) -> JSON:
    """The bot's post of a finished match in #results."""

    def find() -> JSON | None:
        for message in sim.messages(results_channel):
            if re.match(rf"## Match #{match_id}: .+ won\n", text_of(message)):
                return message
        return None

    return wait_for(find, f"the result of match {match_id} in #results")


def rating_lines(post: JSON) -> dict[str, tuple[int, int]]:
    """Discord user id to (rating change, new rating), from a result post."""
    return {
        uid: (int(delta), int(rating)) for delta, rating, uid in RATING_LINE.findall(text_of(post))
    }
