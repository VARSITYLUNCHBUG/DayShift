from __future__ import annotations

import copy

from django.db import models

DEFAULT_PENALTY_POLICY = {
    # Cooldown minutes by rung. A clean record uses the first rung; each strike a player already
    # carries, from any kind of offence, moves them one rung up. Starting values are judgement.
    "ladders": {
        "missed_ready": [5, 15, 60, 180, 720],
        "dodge": [60, 360, 1440, 4320, 10080],
        "leaver": [120, 720, 2880, 10080],
        "false_report": [1440, 4320, 10080],
    },
    # Strikes each kind of offence adds. A staff "manual" cooldown adds none.
    "strikes": {"missed_ready": 1, "dodge": 2, "leaver": 3, "false_report": 3, "manual": 0},
    # Clean completed matches that work off one strike.
    "games_per_strike": 3,
    # One strike also comes off for each this many days without an offence.
    "decay_days": 14,
    "max_strikes": 10,
}

OCR_MODES = (
    ("off", "Off"),
    ("shadow", "Stats only"),
    ("on", "On: stats, MVP and key players, and cross-checks"),
)


def default_penalty_policy() -> dict[str, object]:
    return copy.deepcopy(DEFAULT_PENALTY_POLICY)


def effective_penalty_policy(stored: dict[str, object] | None) -> dict[str, object]:
    """The stored policy over the defaults, one level deep, so a server that saved an older
    policy still gets keys added since. Values a server has set are never replaced."""
    merged = default_penalty_policy()
    for key, value in (stored or {}).items():
        default = merged.get(key)
        if isinstance(default, dict) and isinstance(value, dict):
            merged[key] = {**default, **value}
        else:
            merged[key] = value
    return merged


class Community(models.Model):
    """One Discord server and its wiring. Rules that govern a match live in the mode version."""

    discord_guild_id = models.BigIntegerField(unique=True)
    name = models.CharField(max_length=100)
    active_mode = models.ForeignKey(
        "league.DraftModeVersion", on_delete=models.PROTECT, related_name="+"
    )
    queue_channel_id = models.BigIntegerField(null=True, blank=True)
    queue_message_id = models.BigIntegerField(null=True, blank=True)
    waiting_room_channel_id = models.BigIntegerField(null=True, blank=True)
    results_channel_id = models.BigIntegerField(null=True, blank=True)
    archive_channel_id = models.BigIntegerField(null=True, blank=True)
    match_category_id = models.BigIntegerField(null=True, blank=True)
    # Staff alert cards: disputes and everything else staff should look at (/setup).
    staff_channel_id = models.BigIntegerField(null=True, blank=True)
    # This server's error summaries are posted here (/seterrorchannel).
    error_channel_id = models.BigIntegerField(null=True, blank=True)
    penalty_policy = models.JSONField(default=default_penalty_policy)

    class Meta:
        db_table = "communities"
        verbose_name_plural = "communities"

    def __str__(self) -> str:
        return self.name


class RuntimeSettings(models.Model):
    """One server's switches. They take effect at once, with no restart: change them in the
    admin, or with the staff commands that set them (/ocr mode, /deadlock settings).

    Read them through `league.services.runtime.of`, which creates the row on first use."""

    community = models.OneToOneField(Community, on_delete=models.CASCADE, related_name="runtime")
    max_concurrent_matches = models.PositiveSmallIntegerField(
        default=12, help_text="Ranked matches that can run at once. The queue waits beyond this."
    )
    auto_captain = models.BooleanField(
        default=False,
        help_text="On: captains are picked automatically, by experience and then rating. "
        "Off: players vote for captains. Scrims are unaffected.",
    )
    open_match_voice = models.BooleanField(
        default=False,
        help_text="Let anyone in the server join a match's voice channels, not only its players.",
    )
    match_channel_close_minutes = models.PositiveSmallIntegerField(
        default=3, help_text="Minutes a match's text channel stays open after the match ends."
    )
    score_ocr = models.CharField(
        max_length=8,
        choices=OCR_MODES,
        default="off",
        help_text="Reading report screenshots. Needs the reader installed on the bot's host.",
    )
    auto_lobby = models.BooleanField(
        default=False, help_text="Have deadlock-api's bot create each match's custom lobby."
    )
    lobby_region = models.CharField(
        max_length=24, blank=True, help_text="Region for automatic lobbies. Empty: automatic."
    )
    api_results = models.BooleanField(
        default=True, help_text="Check reported results against Deadlock's match history."
    )

    class Meta:
        db_table = "runtime_settings"
        verbose_name = "runtime settings"
        verbose_name_plural = "runtime settings"

    def __str__(self) -> str:
        return f"Settings for {self.community}"
