from __future__ import annotations

from django.db import models


class Area(models.TextChoices):
    """A set of staff commands. A server grants areas to roles with /permissions."""

    SETUP = "setup", "Setup"
    MATCH_CONTROL = "match_control", "Match control"
    DISPUTES = "disputes", "Disputes"
    RATINGS = "ratings", "Ratings"
    MODERATION = "moderation", "Moderation"
    COMMUNITY = "community", "Community"
    SCRIMS = "scrims", "Scrims"


# What each area covers, as /permissions list shows it.
AREA_SCOPE: dict[str, str] = {
    Area.SETUP: "/setup, error channel, /mode, /ocr, /roster, /deadlock settings and status",
    Area.MATCH_CONTROL: "live matches: /match status, void and sub; /queue_admin",
    Area.DISPUTES: "dispute rulings, /match rescore, names and early_leave, finished matches",
    Area.RATINGS: "/rating seed and adjust, /match awards, /ledger_check",
    Area.MODERATION: "/ban, /captain, /deadlock unlink",
    Area.COMMUNITY: "/removeprio and ping setup",
    Area.SCRIMS: "/startdraft, /captains_coinflip, /stopdraft",
}


class CommunityRoleGrant(models.Model):
    """One area granted to one Discord role. Members hold every area their roles are granted;
    the server owner and Administrators hold them all without a grant."""

    community = models.ForeignKey(
        "league.Community", on_delete=models.PROTECT, related_name="role_grants"
    )
    role_id = models.BigIntegerField()
    area = models.CharField(max_length=16, choices=Area.choices)
    granted_by_discord_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "community_role_grants"
        ordering = ("area", "role_id")
        constraints = [
            models.UniqueConstraint(
                fields=("community", "role_id", "area"), name="uniq_role_grant"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_area_display()} for role {self.role_id}"
