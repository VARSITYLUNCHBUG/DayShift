"""What the control API remembers between calls. None of it is league state: a reset drops it."""

from __future__ import annotations

from django.db import models


class DevProfile(models.Model):
    """A fake player's dev-only settings: champion preferences and what the simulator was told."""

    player = models.OneToOneField(
        "league.Player", on_delete=models.CASCADE, related_name="dev_profile"
    )
    prefer = models.JSONField(default=list, blank=True)  # Champion ids, best first.
    ban = models.JSONField(default=list, blank=True)
    dm_open = models.BooleanField(null=True)
    # The shown rating dev_seed gives them through the ledger, once per season.
    seed_rating = models.PositiveIntegerField(null=True, blank=True)
    # The Discord ID is a simulator user's, rather than one from the local range.
    sim_user = models.BooleanField(default=False)
    # Deleted, but the append-only ledger still refers to them.
    retired = models.BooleanField(default=False)

    class Meta:
        db_table = "devtools_profiles"

    def __str__(self) -> str:
        return f"Dev profile of {self.player_id}"


class MatchScript(models.Model):
    """How the autopilot should play a match, over its defaults (see README, the script)."""

    match = models.OneToOneField("league.Match", on_delete=models.CASCADE, related_name="+")
    body = models.JSONField(default=dict)

    class Meta:
        db_table = "devtools_match_scripts"

    def __str__(self) -> str:
        return f"Script for match {self.match_id}"


class FrozenMatch(models.Model):
    """A match whose timers are frozen: the deadlines are pushed out and the time left saved."""

    match = models.OneToOneField("league.Match", on_delete=models.CASCADE, related_name="+")
    frozen_at = models.DateTimeField()

    class Meta:
        db_table = "devtools_frozen_matches"

    def __str__(self) -> str:
        return f"Match {self.match_id} frozen"


class FrozenTimer(models.Model):
    """One parked deadline: a field of a match, sub request, sub offer or early-leave report.

    `pushed_to` is the far-off value written in its place. A field holding anything else has been
    set afresh by an action since, so it is parked again with its new time left.
    """

    frozen = models.ForeignKey(FrozenMatch, on_delete=models.CASCADE, related_name="timers")
    model = models.CharField(max_length=32)
    object_id = models.BigIntegerField()
    field = models.CharField(max_length=32)
    remaining_seconds = models.FloatField()
    pushed_to = models.DateTimeField()

    class Meta:
        db_table = "devtools_frozen_timers"
        constraints = (
            models.UniqueConstraint(
                fields=("model", "object_id", "field"), name="uniq_devtools_frozen_timer"
            ),
        )

    def __str__(self) -> str:
        return f"{self.model} {self.object_id}.{self.field}: {self.remaining_seconds:.0f}s"


class DevFlag(models.Model):
    """A named switch, such as every timer being paused."""

    key = models.CharField(max_length=32, primary_key=True)
    value = models.JSONField(default=dict)

    class Meta:
        db_table = "devtools_flags"

    def __str__(self) -> str:
        return self.key
