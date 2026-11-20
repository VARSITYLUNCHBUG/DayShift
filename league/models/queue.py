from __future__ import annotations

from django.db import models


class QueueEntry(models.Model):
    """A player waiting right now. Rows are deleted on leave or pop.

    FIFO order is `joined_at`. A cancelled lobby re-inserts ready players with their original
    `joined_at`, which puts them ahead of later joiners without any priority column.

    The idle timeout (`RuntimeSettings.queue_idle_minutes`) runs from `active_at`, not
    `joined_at`, so checking in never costs anyone their place.
    """

    community = models.ForeignKey("league.Community", on_delete=models.PROTECT, related_name="+")
    player = models.ForeignKey("league.Player", on_delete=models.PROTECT, related_name="+")
    joined_at = models.DateTimeField()
    # When they last showed they're still here: joining, or Keep me in on the check-in DM.
    active_at = models.DateTimeField()
    # When the "Still queueing?" check-in went out. Cleared by Keep me in.
    warned_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "queue_entries"
        verbose_name_plural = "queue entries"
        ordering = ("joined_at", "id")
        constraints = [
            models.UniqueConstraint(fields=("community", "player"), name="uniq_queue_player"),
        ]
        indexes = [models.Index(fields=("community", "joined_at"), name="queue_fifo_idx")]

    def __str__(self) -> str:
        return f"{self.player_id} since {self.joined_at:%H:%M:%S}"
