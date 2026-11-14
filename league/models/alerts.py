from __future__ import annotations

from django.db import models
from django.db.models import Q

from league.models.permissions import Area


class AlertKind(models.TextChoices):
    DISPUTE = "dispute", "Disputed result"
    EARLY_LEAVE = "early_leave", "Early leave"
    API_MISMATCH = "api_mismatch", "deadlock-api disagrees"
    API_ABANDON = "api_abandon", "deadlock-api shows an abandon"
    OCR_MISMATCH = "ocr_mismatch", "Scoreboard disagrees"
    AWARD_FREEZE = "award_freeze", "Award share frozen"
    LOBBY_FAILED = "lobby_failed", "Lobby couldn't be created"


class AlertStatus(models.TextChoices):
    OPEN = "open", "Open"
    RESOLVED = "resolved", "Resolved"
    DISMISSED = "dismissed", "Dismissed"


class StaffAlert(models.Model):
    """Something staff should look at, posted as a card in the staff channel.

    Each alert belongs to one area: the card pings the roles holding it, and any of them can act
    on it. A dispute is closed by its ruling; anything else is dismissed once it's dealt with.
    """

    community = models.ForeignKey("league.Community", on_delete=models.PROTECT, related_name="+")
    match = models.ForeignKey(
        "league.Match",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="staff_alerts",
    )
    kind = models.CharField(max_length=16, choices=AlertKind.choices)
    area = models.CharField(max_length=16, choices=Area.choices)
    text = models.TextField()
    status = models.CharField(max_length=10, choices=AlertStatus.choices, default=AlertStatus.OPEN)
    # The same finding raises one alert, however often it's found.
    dedupe_key = models.CharField(max_length=120, null=True, blank=True, unique=True)
    # Where the card is posted, once it is.
    channel_id = models.BigIntegerField(null=True, blank=True)
    message_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField()
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        "league.Player", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    outcome = models.CharField(max_length=200, blank=True)

    class Meta:
        db_table = "staff_alerts"
        ordering = ("-id",)
        indexes = [models.Index(fields=("community", "status"), name="staff_alert_open_idx")]
        constraints = [
            models.UniqueConstraint(
                fields=("match",),
                condition=Q(kind="dispute", status="open"),
                name="uniq_open_dispute_alert",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} ({self.status})"
