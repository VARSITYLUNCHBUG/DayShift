from __future__ import annotations

from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q


class QuickDraftStatus(models.TextChoices):
    CAPTAINS = "captains", "Waiting for captains"
    COINFLIP = "coinflip", "Captain coinflip"
    READY = "ready", "Ready to start"
    DRAFTING = "drafting", "Drafting"
    COMPLETED = "completed", "Completed"
    STOPPED = "stopped", "Stopped"


# Statuses that hold the channel: one of these per channel at a time.
QUICK_DRAFT_LIVE = ("captains", "coinflip", "ready", "drafting")


class Side(models.TextChoices):
    HIDDEN_KING = "hk", "The Hidden King"
    ARCHMOTHER = "am", "The Archmother"


class QuickDraft(models.Model):
    """Bebot's /startdraft: a hero ban and pick in any channel, outside the match flow.

    Two captains, the draft message with the hero grid below it, and nothing that touches
    ratings. Captains are plain Discord users, so a draft can run for people who never queued.
    It keeps the match flow's guarantees: one row lock per change, one action row per step,
    timers as rows the poller fires, and Discord changes through the outbox.
    """

    community = models.ForeignKey("league.Community", on_delete=models.PROTECT, related_name="+")
    mode_version = models.ForeignKey(
        "league.DraftModeVersion", on_delete=models.PROTECT, related_name="+"
    )
    channel_id = models.BigIntegerField()
    status = models.CharField(max_length=12, choices=QuickDraftStatus.choices)
    started_by_id = models.BigIntegerField()
    hk_captain_id = models.BigIntegerField(null=True, blank=True)
    hk_captain_name = models.CharField(max_length=100, blank=True)
    am_captain_id = models.BigIntegerField(null=True, blank=True)
    am_captain_name = models.CharField(max_length=100, blank=True)
    # The side in the mode's "first" role: it bans and picks first.
    first_side = models.CharField(max_length=2, choices=Side.choices, default=Side.HIDDEN_KING)
    # /captains_coinflip: the winner chooses first, then the loser chooses from what's left.
    coinflip_winner_id = models.BigIntegerField(null=True, blank=True)
    coinflip_winner_name = models.CharField(max_length=100, blank=True)
    coinflip_loser_id = models.BigIntegerField(null=True, blank=True)
    coinflip_loser_name = models.CharField(max_length=100, blank=True)
    winner_choice = models.CharField(max_length=12, blank=True)
    loser_choice = models.CharField(max_length=12, blank=True)
    step_index = models.PositiveSmallIntegerField(default=0)
    version = models.PositiveIntegerField(default=0)
    # The turn's timer while drafting; before that, when an unstarted draft gives up.
    deadline_at = models.DateTimeField(null=True, blank=True)
    rng_seed = models.BigIntegerField()
    champion_pool = ArrayField(models.PositiveIntegerField(), default=list)
    # The draft message, and the hero grid's messages below it, top to bottom. A grid slot keeps
    # its place, null once its message is gone, so clearing one can't shift the others.
    board_message_id = models.BigIntegerField(null=True, blank=True)
    grid_message_ids = ArrayField(models.BigIntegerField(null=True), default=list, blank=True)
    # Whether the bot could use the custom hero emojis in this channel when it started.
    custom_emojis = models.BooleanField(default=True)
    created_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "quick_drafts"
        ordering = ("-id",)
        constraints = [
            models.UniqueConstraint(
                fields=("channel_id",),
                condition=Q(status__in=QUICK_DRAFT_LIVE),
                name="uniq_live_quick_draft_per_channel",
            ),
        ]
        indexes = [
            models.Index(
                fields=("deadline_at",),
                condition=Q(deadline_at__isnull=False),
                name="quick_draft_deadline_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"Draft #{self.pk} ({self.status})"

    @property
    def lane(self) -> str:
        """The outbox lane all this draft's Discord work runs in, in order."""
        return f"quick_draft:{self.pk}"

    def captain_id(self, side: str) -> int | None:
        return self.hk_captain_id if side == Side.HIDDEN_KING else self.am_captain_id

    def captain_name(self, side: str) -> str:
        return self.hk_captain_name if side == Side.HIDDEN_KING else self.am_captain_name


class QuickDraftAction(models.Model):
    """One ban or pick. Append-only: the unique step stops a double click taking two turns."""

    draft = models.ForeignKey(QuickDraft, on_delete=models.PROTECT, related_name="actions")
    step_index = models.PositiveSmallIntegerField()
    action = models.CharField(max_length=4)
    side = models.CharField(max_length=2, choices=Side.choices)
    champion = models.ForeignKey("league.Champion", on_delete=models.PROTECT, related_name="+")
    actor_id = models.BigIntegerField(null=True, blank=True)  # None when the timer chose.
    source = models.CharField(max_length=8)  # "user" or "timeout".
    random_choice = models.BooleanField(default=False)
    interaction_id = models.BigIntegerField(null=True, blank=True, unique=True)
    created_at = models.DateTimeField()

    class Meta:
        db_table = "quick_draft_actions"
        ordering = ("draft", "step_index")
        constraints = [
            models.UniqueConstraint(fields=("draft", "step_index"), name="uniq_quick_draft_step"),
            models.UniqueConstraint(fields=("draft", "champion"), name="uniq_quick_draft_champion"),
        ]

    def __str__(self) -> str:
        return f"{self.draft_id}#{self.step_index} {self.action}"
