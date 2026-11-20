"""What only the player web UI adds to a match: hero wishes, the match chats, and the postgame
data drawn from deadlock-api."""

from __future__ import annotations

from django.db import models

WISHES_PER_PLAYER = 3
CHAT_MAX_CHARS = 500


class HeroWish(models.Model):
    """A hero a player wants to play in this match, ranked 1 (best) to 3. Only the player's
    captain and teammates see them."""

    match = models.ForeignKey("league.Match", on_delete=models.CASCADE, related_name="wishes")
    player = models.ForeignKey("league.Player", on_delete=models.CASCADE, related_name="wishes")
    champion = models.ForeignKey("league.Champion", on_delete=models.CASCADE, related_name="+")
    rank = models.PositiveSmallIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "hero_wishes"
        ordering = ("match", "player", "rank")
        constraints = [
            models.UniqueConstraint(fields=("match", "player", "rank"), name="uniq_wish_rank"),
            models.UniqueConstraint(
                fields=("match", "player", "champion"), name="uniq_wish_champion"
            ),
            models.CheckConstraint(
                condition=models.Q(rank__gte=1, rank__lte=WISHES_PER_PLAYER),
                name="wish_rank_range",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.player_id} wants {self.champion_id} ({self.rank})"


class ChatScope(models.TextChoices):
    LOBBY = "lobby", "Lobby"  # All twelve, while the teams are being made.
    TEAM_A = "A", "Team A"
    TEAM_B = "B", "Team B"


class ChatMessage(models.Model):
    """One line in a match's lobby chat or a team's chat. Plain text; the web shows it as text."""

    match = models.ForeignKey("league.Match", on_delete=models.CASCADE, related_name="chat")
    scope = models.CharField(max_length=8, choices=ChatScope.choices)
    player = models.ForeignKey("league.Player", on_delete=models.CASCADE, related_name="+")
    body = models.CharField(max_length=CHAT_MAX_CHARS)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "chat_messages"
        ordering = ("match", "scope", "id")
        indexes = [models.Index(fields=("match", "scope", "id"), name="chat_match_scope")]

    def __str__(self) -> str:
        return f"{self.player_id} in {self.scope}: {self.body[:40]}"


class MatchPostgame(models.Model):
    """The postgame screens' data for a match: drawn from the deadlock-api metadata the bot
    already fetches (league/services/api_results.py), kept small and in the web's shape."""

    match = models.OneToOneField("league.Match", on_delete=models.CASCADE, related_name="postgame")
    deadlock_match_id = models.BigIntegerField()
    # Bumped when the shape of `data` changes, so old rows are rebuilt rather than misread.
    schema_version = models.PositiveSmallIntegerField()
    data = models.JSONField()
    built_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "match_postgames"

    def __str__(self) -> str:
        return f"Postgame for match {self.match_id}"


class DeadlockItem(models.Model):
    """deadlock-api's shop items, by item ID: the names for the postgame's builds, added when a
    postgame is served (league/services/items.py). Refreshed by `manage.py sync_items`, and by
    the bot after a match check once its copy is a day old."""

    id = models.BigIntegerField(primary_key=True)  # deadlock-api's item ID.
    name = models.CharField(max_length=100)
    slot = models.CharField(max_length=16, blank=True)  # "weapon", "vitality" or "spirit".
    tier = models.PositiveSmallIntegerField(null=True, blank=True)
    synced_at = models.DateTimeField()

    class Meta:
        db_table = "deadlock_items"

    def __str__(self) -> str:
        return self.name
