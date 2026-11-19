from __future__ import annotations

from django.db import models
from django.db.models import Q


class PlayerManager(models.Manager["Player"]):
    def from_discord(self, discord_user_id: int, display_name: str) -> Player:
        """The player with this Discord ID, made on first sight, and renamed if they were."""
        name = display_name[:100]
        player, created = self.get_or_create(
            discord_user_id=discord_user_id, defaults={"display_name": name}
        )
        if not created and name and player.display_name != name:
            player.display_name = name
            player.save(update_fields=["display_name", "updated_at"])
        return player


class Player(models.Model):
    """A Discord identity. Ratings and history are derived: see PlayerRating and RatingEvent."""

    discord_user_id = models.BigIntegerField(unique=True)
    display_name = models.CharField(max_length=100)
    # Optional. The 32-bit Steam account ID, as deadlock-api and match metadata use it.
    steam_account_id = models.BigIntegerField(null=True, blank=True)
    steam_name = models.CharField(max_length=100, blank=True)
    steam_linked_at = models.DateTimeField(null=True, blank=True)
    # Set once that account turned up, on the player's own team, in one of their matches.
    steam_verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = PlayerManager()

    class Meta:
        db_table = "players"
        constraints = [
            models.UniqueConstraint(
                fields=("steam_account_id",),
                condition=Q(steam_account_id__isnull=False),
                name="uniq_player_steam_account",
            ),
        ]

    def __str__(self) -> str:
        return self.display_name
