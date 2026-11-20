"""Community setup: the row for this Discord server, its first season and channel wiring."""

from __future__ import annotations

from django.db import transaction
from django.db.models import QuerySet

from league.domain.errors import InvalidAction
from league.models import Community, DraftModeVersion, RuntimeSettings, Season
from league.services.common import now

DEFAULT_MODE_SLUG = "draft_3ban"


def get(guild_id: int) -> Community | None:
    return Community.objects.select_related("active_mode").filter(discord_guild_id=guild_id).first()


@transaction.atomic
def ensure(guild_id: int, name: str) -> Community:
    community = Community.objects.filter(discord_guild_id=guild_id).first()
    if community is None:
        mode = DraftModeVersion.objects.filter(slug=DEFAULT_MODE_SLUG).order_by("-version").first()
        if mode is None:
            raise InvalidAction(
                "The bot isn't ready yet: it has no draft modes. Ask whoever hosts it."
            )
        community = Community.objects.create(
            discord_guild_id=guild_id, name=name[:100], active_mode=mode
        )
        RuntimeSettings.objects.create(community=community)
    if not Season.objects.filter(community=community, ended_at__isnull=True).exists():
        number = Season.objects.filter(community=community).count() + 1
        Season.objects.create(
            community=community, number=number, name=f"Season {number}", started_at=now()
        )
    return community


def save_wiring(community_id: int, **ids: int | list[int] | None) -> None:
    allowed = {
        "queue_channel_id",
        "queue_message_id",
        "waiting_room_channel_id",
        "results_channel_id",
        "archive_channel_id",
        "match_category_id",
        "error_channel_id",
        "staff_channel_id",
        "pug_role_id",
        "leaderboard_channel_id",
        "leaderboard_message_ids",
    }
    unknown = set(ids) - allowed
    if unknown:
        raise ValueError(f"Unknown wiring fields: {sorted(unknown)}")
    Community.objects.filter(pk=community_id).update(**ids)


def error_channel(guild_id: int) -> int | None:
    """Where this server's error summaries go (/seterrorchannel), if anywhere."""
    return (
        Community.objects.filter(discord_guild_id=guild_id)
        .values_list("error_channel_id", flat=True)
        .first()
    )


@transaction.atomic
@transaction.atomic
def start_next_season(community_id: int, params: dict[str, object] | None = None) -> Season:
    """The admin's and `manage.py start_season`'s way in: a new season, then the queue panel and
    the leaderboard redrawn for it."""
    from league.services import leaderboards
    from league.services.common import lock_community, render_queue

    community = lock_community(community_id)
    season = start_season(community, params)
    render_queue(community)
    leaderboards.request(community)
    return season


def start_season(community: Community, params: dict[str, object] | None = None) -> Season:
    """Close the open season and open the next. Ratings start fresh, with `params` over the
    OpenSkill defaults; they're fixed once the season rates a match."""
    from league.domain.openskill_v1 import DEFAULT_PARAMS

    unknown = set(params or {}) - set(DEFAULT_PARAMS)
    if unknown:
        raise InvalidAction(f"Unknown rating parameters: {', '.join(sorted(unknown))}.")
    moment = now()
    Season.objects.filter(community=community, ended_at__isnull=True).update(ended_at=moment)
    number = Season.objects.filter(community=community).count() + 1
    return Season.objects.create(
        community=community,
        number=number,
        name=f"Season {number}",
        rating_params=dict(params or {}),
        started_at=moment,
    )


def _synced_rows(guild_id: int | None) -> QuerySet[Community]:
    """The servers a command sync covers: one guild, or every server for a global sync."""
    rows = Community.objects.all()
    return rows if guild_id is None else rows.filter(discord_guild_id=guild_id)


def commands_synced(guild_id: int | None, fingerprint: str) -> bool:
    """Whether every server this sync covers already has exactly these commands. A server with
    no row yet (before /setup) hasn't, so it's synced."""
    values = list(_synced_rows(guild_id).values_list("commands_fingerprint", flat=True))
    return bool(values) and all(value == fingerprint for value in values)


def record_commands_synced(guild_id: int | None, fingerprint: str) -> None:
    _synced_rows(guild_id).update(commands_fingerprint=fingerprint)
