from __future__ import annotations

from django.db import models
from django.db.models import Q


class SwapStatus(models.TextChoices):
    PENDING = "pending", "Waiting for the other captain"
    ACCEPTED = "accepted", "Swapped"
    DECLINED = "declined", "Declined"
    EXPIRED = "expired", "No answer"


class PlayerSwap(models.Model):
    """A captain offering one of their players for one of the other team's, after the player
    draft. The other captain accepts and the two change teams, or it lapses."""

    match = models.ForeignKey("league.Match", on_delete=models.PROTECT, related_name="swaps")
    requested_by = models.ForeignKey("league.Player", on_delete=models.PROTECT, related_name="+")
    # From the requesting captain's team, and from the other team.
    give = models.ForeignKey("league.Player", on_delete=models.PROTECT, related_name="+")
    take = models.ForeignKey("league.Player", on_delete=models.PROTECT, related_name="+")
    status = models.CharField(max_length=8, choices=SwapStatus.choices, default=SwapStatus.PENDING)
    deadline_at = models.DateTimeField()
    resolved_by = models.ForeignKey(
        "league.Player", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField()

    class Meta:
        db_table = "player_swaps"
        ordering = ("id",)
        constraints = [
            models.UniqueConstraint(
                fields=("match",),
                condition=Q(status="pending"),
                name="uniq_pending_swap",
            ),
        ]
        indexes = [
            models.Index(
                fields=("deadline_at",),
                condition=Q(status="pending"),
                name="swap_pending_idx",
            )
        ]

    def __str__(self) -> str:
        return f"{self.match_id}: {self.give_id} <-> {self.take_id} {self.status}"
