"""Names for the channels the bot creates for a match. Pure: no I/O.

One pattern for every match so its channels read alike and sort together in the channel list:
the text channel `match-12`, then each team's voice, `Match 12 · Kestrel's Team`, which is the
team's name on the board.
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


def team_label(captain: str) -> str:
    """The team's name on the board, `Kestrel's Team`, or `Team` with no captain yet."""
    who = _clean(captain)
    return f"{who}'s Team"[:MAX_LENGTH] if who else "Team"


def team_voice(match_id: int, captain: str) -> str:
    return f"Match {match_id} · {team_label(captain)}"[:MAX_LENGTH]


def pooled_voice(number: int) -> str:
    """A server's reusable team voice channel. Its name never changes: Discord allows a channel
    only two renames in ten minutes. The match and team it's serving show in its voice status."""
    return f"Team Voice {number}"
