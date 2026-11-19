from __future__ import annotations

from typing import Any, ClassVar

from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models


class PlayerManager(UserManager["Player"]):
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

    def create_superuser(  # type: ignore[override]
        self, username: str, email: str | None = None, password: str | None = None, **extra: Any
    ) -> Player:
        """`createsuperuser`: a new player with an admin login, or an admin login for the player
        who already has this Discord ID, so a host who has played keeps one identity."""
        if extra.get("discord_user_id") in (None, ""):
            raise ValueError("An admin login needs the Discord ID of the person it's for.")
        existing = self.filter(discord_user_id=extra["discord_user_id"]).first()
        if existing is None:
            return super().create_superuser(username, email, password, **extra)
        existing.username = username
        existing.email = self.normalize_email(email) or existing.email
        existing.is_staff = existing.is_superuser = True
        existing.set_password(password)
        existing.save()
        return existing


class Player(AbstractUser):
    """A person, known by their Discord account: everyone the bot has seen, and every admin login.

    The Discord account is required and one per player. Steam accounts are optional, and a player
    may link several (SteamAccount). Ratings and history are derived: see PlayerRating and
    RatingEvent. Players the bot makes have no password; an admin login gets one with
    `createsuperuser`, or from the admin."""

    discord_user_id = models.BigIntegerField(unique=True)
    display_name = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # `createsuperuser` asks for the Discord ID too.
    REQUIRED_FIELDS = ["discord_user_id"]

    objects: ClassVar[PlayerManager] = PlayerManager()  # type: ignore[assignment]

    class Meta:
        db_table = "players"

    def save(self, *args: Any, **kwargs: Any) -> None:
        # A player the bot makes has only a Discord account: a username from it, and no password.
        if not self.username:
            self.username = f"discord-{self.discord_user_id}"
        if not self.display_name:
            self.display_name = self.username[:100]
        if not self.password:
            self.set_unusable_password()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.display_name


class SteamAccount(models.Model):
    """A Steam account a player linked with /link. A player may have several; an account belongs
    to one player.

    A link is what the player says. It becomes verified when deadlock-api shows the account on
    the player's own team in one of their matches, which nobody can fake from Discord."""

    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="steam_accounts")
    # The 32-bit Steam account ID, as deadlock-api and match metadata use it.
    account_id = models.BigIntegerField(unique=True)
    steam_name = models.CharField(max_length=100, blank=True)
    linked_at = models.DateTimeField()
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "steam_accounts"
        ordering = ("linked_at", "pk")

    def __str__(self) -> str:
        return self.steam_name or str(self.account_id)
