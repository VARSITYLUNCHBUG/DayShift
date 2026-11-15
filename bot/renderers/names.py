"""Names for the channels the bot creates for a match. Pure: no I/O.

One pattern for every match so its channels read alike and sort together in the channel list:
the text channel `match-12`, then voice `Match 12 · Lobby` and `Match 12 · Kestrel's Team`,
which is the team's name on the board.
"""

from __future__ import annotations

import re
import unicodedata

# Discord's limit for a channel name.
MAX_LENGTH = 100


def _clean(name: str) -> str:
    """A display name fit for a channel name: no control or formatting characters, single spaces."""
    kept = "".join(ch for ch in name if unicodedata.category(ch)[0] not in {"C"})
    return re.sub(r"\s+", " ", kept).strip()


def match_text(match_id: int) -> str:
    return f"match-{match_id}"


def lobby_voice(match_id: int) -> str:
    return f"Match {match_id} · Lobby"


def team_voice(match_id: int, captain: str) -> str:
    who = _clean(captain)
    name = f"Match {match_id} · {who}'s Team" if who else f"Match {match_id} · Team"
    return name[:MAX_LENGTH]
