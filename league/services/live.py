"""Tells the web process what changed, so open pages refresh.

Each topic names something a page shows: one match, one server's queue, or one player's own
state. `publish` sends a Postgres NOTIFY inside the caller's transaction, so it arrives only once
the change has committed, never for a change that rolled back, and once per topic per transaction
however often it's published. The web process LISTENs and reads the state again: the
notification carries nothing but the topic.

Publish where the change is made, not from `add_effect`: an effect is Discord work, and some
changes (a priority list hold, a Steam link) have none.
"""

from __future__ import annotations

from django.db import connection

CHANNEL = "dayshift_live"


def match_topic(match_id: int) -> str:
    return f"match:{match_id}"


def queue_topic(community_id: int) -> str:
    return f"queue:{community_id}"


def player_topic(player_id: int) -> str:
    return f"player:{player_id}"


def publish(*topics: str) -> None:
    unique = list(dict.fromkeys(topics))
    if not unique:
        return
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_notify(%s, topic) FROM unnest(%s::text[]) AS topic", [CHANNEL, unique]
        )
