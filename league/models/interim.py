from __future__ import annotations

from django.db import models


class InterimRating(models.Model):
    """NeatQueue's points, carried over at the cutover and kept moving while the interim runs.

    The imported values are the facts. Everything else is a projection that
    `league.services.interim.rebuild` recreates from them and the season's completed matches, so
    a correction or a void can never leave the points out of step.
    """

    season = models.ForeignKey("league.Season", on_delete=models.PROTECT, related_name="+")
    player = models.ForeignKey("league.Player", on_delete=models.PROTECT, related_name="+")
    # From the NeatQueue export. Null: not in it, so the player started at the default.
    imported_points = models.IntegerField(null=True, blank=True)
    imported_wins = models.PositiveIntegerField(default=0)
    imported_losses = models.PositiveIntegerField(default=0)
    imported_at = models.DateTimeField(null=True, blank=True)
    # The projection: imported values plus every completed match this season, in order.
    points = models.IntegerField()
    wins = models.PositiveIntegerField(default=0)
    losses = models.PositiveIntegerField(default=0)
    games = models.PositiveIntegerField(default=0)  # Matches played here, not in NeatQueue.

    class Meta:
        db_table = "interim_ratings"
        constraints = [
            models.UniqueConstraint(fields=("season", "player"), name="uniq_interim_player"),
        ]
        indexes = [models.Index(fields=("season", "-points"), name="interim_board_idx")]

    def __str__(self) -> str:
        return f"{self.player_id}: {self.points}"


class InterimPointsChange(models.Model):
    """What one match did to one player's points. Rebuilt with the projection, never edited."""

    season = models.ForeignKey("league.Season", on_delete=models.PROTECT, related_name="+")
    match = models.ForeignKey("league.Match", on_delete=models.PROTECT, related_name="+")
    player = models.ForeignKey("league.Player", on_delete=models.PROTECT, related_name="+")
    before = models.IntegerField()
    after = models.IntegerField()

    class Meta:
        db_table = "interim_points_changes"
        ordering = ("id",)
        constraints = [
            models.UniqueConstraint(fields=("match", "player"), name="uniq_interim_change"),
        ]
        indexes = [models.Index(fields=("player", "-id"), name="interim_history_idx")]

    def __str__(self) -> str:
        return f"{self.player_id} {self.delta:+d} in {self.match_id}"

    @property
    def delta(self) -> int:
        return self.after - self.before
