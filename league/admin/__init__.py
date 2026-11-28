"""Django admin: the host's console. Server configuration lives here (runtime settings, the
active mode, champions, the NeatQueue import, seasons); Discord keeps the player, match and
moderation commands. Saving goes through the same services the bot uses, so the queue panel and
leaderboard redraw. History tables are read-only by design."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

import httpx
from django import forms
from django.contrib import admin, messages
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.contrib.auth.admin import UserAdmin
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import URLPattern, path, reverse
from django.utils.html import format_html_join
from django.utils.safestring import SafeString, mark_safe

from league.domain.copy import plural
from league.domain.errors import DomainError, InvalidAction
from league.domain.mode_schema import ModeValidationError
from league.integrations import deadlock_api
from league.models import (
    ApiMatchCheck,
    CaptainOverride,
    CaptainVote,
    Champion,
    ChannelPing,
    Community,
    CommunityRoleGrant,
    DraftAction,
    DraftModeVersion,
    EarlyLeave,
    InterimRating,
    Match,
    MatchAward,
    MatchParticipant,
    MatchResource,
    MatchResult,
    MatchTransition,
    OutboxEffect,
    Penalty,
    Player,
    PlayerAlias,
    PlayerMatchStat,
    PlayerRating,
    PlayerSwap,
    PrioEntry,
    QueueEntry,
    RatingEvent,
    RatingRun,
    ResultSubmission,
    RuntimeSettings,
    ScoreboardRead,
    Season,
    StaffAlert,
    SteamAccount,
    StrikeAdjustment,
)
from league.services import (
    api_results,
    champions,
    effects,
    integrity,
    interim,
    modes,
    ocr,
    runtime,
)
from league.services import community as community_service

# The header's "View site" link goes to the staff calibration dashboard.
admin.site.site_url = "/admin/calibration/"


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False


def _lines(lines: Iterable[str]) -> SafeString:
    return format_html_join(mark_safe("<br>"), "{}", ((line,) for line in lines))


def _context(model_admin: admin.ModelAdmin, request: HttpRequest, title: str) -> dict[str, Any]:
    return {
        **model_admin.admin_site.each_context(request),
        "title": title,
        "opts": model_admin.model._meta,
    }


def _changelist(model_admin: admin.ModelAdmin) -> str:
    meta = model_admin.model._meta
    return reverse(f"admin:{meta.app_label}_{meta.model_name}_changelist")


class ReadOnlyInline(admin.TabularInline):
    extra = 0
    can_delete = False

    def has_add_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False


@admin.register(Champion)
class ChampionAdmin(admin.ModelAdmin):
    list_display = ("name", "id", "unicode_emoji", "is_enabled", "updated_at")
    list_editable = ("is_enabled",)
    list_filter = ("is_enabled",)
    search_fields = ("name", "aliases")
    prepopulated_fields = {"slug": ("name",)}  # noqa: RUF012

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False  # Past drafts refer to these rows. Disable a champion instead.

    def get_urls(self) -> list[URLPattern]:
        sync = path(
            "sync/", self.admin_site.admin_view(self.sync_view), name="league_champion_sync"
        )
        return [sync, *super().get_urls()]

    def sync_view(self, request: HttpRequest) -> HttpResponse:
        """Compare the roster with the Deadlock API. Apply compares again, so it never applies
        a stale comparison."""
        if not (self.has_add_permission(request) and self.has_change_permission(request)):
            raise PermissionDenied
        try:
            remote = champions.fetch_remote()  # Network: outside any transaction.
        except httpx.HTTPError as exc:
            messages.error(request, f"Couldn't reach the Deadlock API: {exc}")
            return HttpResponseRedirect(_changelist(self))
        roster = champions.diff(remote)
        if request.method == "POST":
            if roster.is_empty:
                messages.info(request, "The roster is already up to date.")
            else:
                champions.apply_diff(roster)
                messages.success(
                    request, "Roster updated. New lobbies use it; live matches don't change."
                )
            return HttpResponseRedirect(_changelist(self))
        context = _context(self, request, "Sync champions with the Deadlock API")
        context["diff"] = roster
        return TemplateResponse(request, "admin/league/champion/sync.html", context)


class DraftModeForm(forms.ModelForm):
    class Meta:
        model = DraftModeVersion
        fields = ("body",)

    def clean_body(self) -> Any:
        body = self.cleaned_data["body"]
        try:
            modes.validate_body(body)
        except ModeValidationError as exc:
            raise ValidationError(exc.problems) from exc
        return body


@admin.register(DraftModeVersion)
class DraftModeVersionAdmin(admin.ModelAdmin):
    """Saving always publishes a new version. Past versions stay exactly as matches saw them."""

    form = DraftModeForm
    list_display = ("slug", "version", "name", "created_at", "created_by")
    list_filter = ("slug",)
    readonly_fields = ("slug", "version", "name", "content_hash", "created_at", "created_by")
    fields = ("slug", "version", "name", "body", "content_hash", "created_at", "created_by")

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def save_model(
        self, request: HttpRequest, obj: DraftModeVersion, form: Any, change: bool
    ) -> None:
        before = obj.version if change else None
        published = modes.publish(form.cleaned_data["body"], created_by=request.user)
        # Point the admin's redirect at the new row; the old row is left untouched.
        obj.pk = published.pk
        obj.slug = published.slug
        obj.version = published.version
        obj._state.adding = False
        if before is not None and published.version == before:
            note = f"Nothing changed: {published.slug} v{published.version} already says this."
        else:
            note = (
                f"Saved as {published.slug} v{published.version}. Choose it as a server's active "
                "mode to use it; matches already running keep the version they started with."
            )
        request._mode_note = note  # type: ignore[attr-defined]

    def message_user(self, request: HttpRequest, message: Any, *args: Any, **kwargs: Any) -> None:
        """Django's "was changed successfully" reads wrong for a save that makes a new version."""
        note = getattr(request, "_mode_note", None)
        super().message_user(request, note or message, *args, **kwargs)

    def response_change(self, request: HttpRequest, obj: DraftModeVersion) -> HttpResponse:
        """ "Save and continue editing" opens the version the save made, not the one it came
        from (Django would go back to the same page)."""
        response = super().response_change(request, obj)
        if "_continue" in request.POST:
            return HttpResponseRedirect(
                reverse("admin:league_draftmodeversion_change", args=[obj.pk])
            )
        return response


class RoleGrantInline(admin.TabularInline):
    """Staff areas by Discord role, as /permissions grants them."""

    model = CommunityRoleGrant
    extra = 0
    fields = ("role_id", "area", "granted_by_discord_id", "created_at")
    readonly_fields = ("granted_by_discord_id", "created_at")


class RuntimeSettingsForm(forms.ModelForm):
    """Checks what this install can't run, and offers deadlock-api's regions."""

    lobby_region = forms.ChoiceField(
        required=False, help_text="Where deadlock-api creates each custom lobby."
    )

    class Meta:
        model = RuntimeSettings
        fields = (
            "max_concurrent_matches",
            "queue_idle_minutes",
            "queue_warn_minutes",
            "auto_captain",
            "open_match_voice",
            "match_channel_close_minutes",
            "match_chat_slowmode_seconds",
            "score_ocr",
            "lobby_region",
            "api_results",
            "interim_points",
            "interim_start_points",
            "interim_k_factor",
        )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        regions = list(deadlock_api.SERVER_REGIONS)
        current = self.instance.lobby_region if self.instance.pk else ""
        if current and current not in regions:
            regions.append(current)  # Kept so an old value doesn't block saving other fields.
        field = self.fields["lobby_region"]
        assert isinstance(field, forms.ChoiceField)
        field.choices = [("", "Automatic"), *((region, region) for region in regions)]

    def clean_score_ocr(self) -> str:
        mode = str(self.cleaned_data["score_ocr"])
        if "score_ocr" in self.changed_data:
            try:
                ocr.validate_mode(mode)
            except InvalidAction as exc:
                raise ValidationError(exc.message) from exc
        return mode


def _after_settings_saved(form: forms.BaseForm) -> None:
    instance = getattr(form, "instance", None)
    if isinstance(instance, RuntimeSettings) and instance.pk and form.changed_data:
        runtime.after_change(instance, frozenset(form.changed_data))


class RuntimeSettingsInline(admin.StackedInline):
    """The server's switches. Saving applies them at once."""

    model = RuntimeSettings
    form = RuntimeSettingsForm
    can_delete = False
    extra = 0
    max_num = 1


@admin.register(RuntimeSettings)
class RuntimeSettingsAdmin(admin.ModelAdmin):
    list_display = (
        "community",
        "auto_captain",
        "open_match_voice",
        "match_channel_close_minutes",
        "max_concurrent_matches",
        "queue_idle_minutes",
        "score_ocr",
        "api_results",
        "interim_points",
    )
    list_editable = ("auto_captain", "open_match_voice", "match_channel_close_minutes")
    form = RuntimeSettingsForm
    readonly_fields = ("community",)

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False  # One row per server, made with it.

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def save_model(
        self, request: HttpRequest, obj: RuntimeSettings, form: Any, change: bool
    ) -> None:
        super().save_model(request, obj, form, change)
        _after_settings_saved(form)


# Channel, message and role IDs the bot made or was given in /setup. Editing them here would
# point the bot at the wrong place, so they're shown, not edited.
WIRING_FIELDS = (
    "discord_guild_id",
    "pug_role_id",
    "queue_channel_id",
    "queue_message_id",
    "waiting_room_channel_id",
    "results_channel_id",
    "leaderboard_channel_id",
    "leaderboard_message_ids",
    "archive_channel_id",
    "staff_channel_id",
    "error_channel_id",
    "match_category_id",
)


class CommunityForm(forms.ModelForm):
    class Meta:
        model = Community
        fields = ("name", "active_mode", "penalty_policy")
        help_texts = {  # noqa: RUF012
            "active_mode": "The latest version of each mode. New lobbies use it; live matches "
            "keep the version they started with.",
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        ids = [version.pk for version in modes.latest_versions()]
        if self.instance.pk and self.instance.active_mode_id:
            ids.append(self.instance.active_mode_id)
        field = self.fields["active_mode"]
        assert isinstance(field, forms.ModelChoiceField)
        field.queryset = DraftModeVersion.objects.filter(pk__in=ids).order_by("slug")

    def clean_active_mode(self) -> DraftModeVersion:
        version: DraftModeVersion = self.cleaned_data["active_mode"]
        if "active_mode" in self.changed_data:
            try:
                modes.validate_body(version.body)
            except ModeValidationError as exc:
                raise ValidationError(exc.problems) from exc
        return version


class StartSeasonForm(forms.Form):
    params = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3, "cols": 60}),
        help_text='OpenSkill parameters over the defaults, as JSON, such as {"beta": 3.5}. '
        "Leave empty for the defaults. They're fixed once the season rates a match.",
    )

    def clean_params(self) -> dict[str, object] | None:
        raw = self.cleaned_data["params"].strip()
        if not raw:
            return None
        try:
            params = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"That isn't JSON: {exc.msg}.") from exc
        if not isinstance(params, dict):
            raise ValidationError('Give an object, such as {"beta": 3.5}.')
        return params


@admin.register(Community)
class CommunityAdmin(admin.ModelAdmin):
    form = CommunityForm
    list_display = ("name", "discord_guild_id", "active_mode")
    inlines = (RuntimeSettingsInline, RoleGrantInline)
    actions = ("start_next_season",)
    readonly_fields = (*WIRING_FIELDS, "screenshot_reads", "deadlock_api_status")
    fieldsets = (
        (None, {"fields": ("name", "active_mode", "penalty_policy")}),
        ("Status", {"fields": ("screenshot_reads", "deadlock_api_status")}),
        (
            "Discord wiring",
            {
                "classes": ("collapse",),
                "description": "Set by /setup in Discord. Run it again to change them.",
                "fields": WIRING_FIELDS,
            },
        ),
    )

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False  # A server is added by running /setup in it.

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    @admin.display(description="Screenshot reads")
    def screenshot_reads(self, obj: Community) -> SafeString:
        return _lines(ocr.status_lines(obj))

    @admin.display(description="Deadlock API")
    def deadlock_api_status(self, obj: Community) -> SafeString:
        return _lines(api_results.status_lines(obj))

    def save_model(self, request: HttpRequest, obj: Community, form: Any, change: bool) -> None:
        super().save_model(request, obj, form, change)
        if "active_mode" in form.changed_data:
            modes.activate(obj.pk, obj.active_mode_id)

    def save_formset(self, request: HttpRequest, form: Any, formset: Any, change: bool) -> None:
        super().save_formset(request, form, formset, change)
        if formset.model is RuntimeSettings:
            for settings_form in formset.forms:
                _after_settings_saved(settings_form)

    @admin.action(description="Start the next season (fresh ratings)")
    def start_next_season(
        self, request: HttpRequest, queryset: QuerySet[Community]
    ) -> HttpResponse | None:
        if queryset.count() != 1:
            self.message_user(request, "Choose one server.", messages.ERROR)
            return None
        community = queryset.get()
        form = StartSeasonForm(request.POST if "confirm" in request.POST else None)
        if form.is_valid():
            try:
                season = community_service.start_next_season(
                    community.pk, form.cleaned_data["params"]
                )
            except DomainError as exc:
                form.add_error("params", exc.message)
            else:
                self.message_user(request, f"Started {season.name} for {community}.")
                return None
        context = _context(self, request, f"Start the next season for {community}")
        context.update(
            community=community,
            form=form,
            open_season=community.seasons.filter(ended_at__isnull=True).first(),
            action_checkbox_name=ACTION_CHECKBOX_NAME,
        )
        return TemplateResponse(request, "admin/league/community/start_season.html", context)


@admin.register(Season)
class SeasonAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "community",
        "number",
        "started_at",
        "ended_at",
    )

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False  # Use the "Start the next season" action on the server's row.

    def get_readonly_fields(self, request: HttpRequest, obj: Any = None) -> tuple[str, ...]:
        # Rating parameters are fixed once anything is rated: replays must reproduce history.
        if obj is not None and RatingRun.objects.filter(season=obj).exists():
            return ("rating_params",)
        return ()

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False


class SteamAccountInline(admin.TabularInline):
    model = SteamAccount
    extra = 0
    fields = ("account_id", "steam_name", "linked_at", "verified_at")
    readonly_fields = ("account_id", "linked_at", "verified_at")

    def has_add_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False  # Players link their own accounts with /link.


@admin.register(Player)
class PlayerAdmin(UserAdmin):
    """Every player is a user. Most only ever have a Discord account; an admin login is a player
    with a password and staff status, made with `createsuperuser` or given here."""

    list_display = (
        "display_name",
        "discord_user_id",
        "steam_count",
        "is_staff",
        "created_at",
    )
    list_filter = ("is_staff", "is_superuser", "is_active")
    search_fields = ("display_name", "discord_user_id", "username", "steam_accounts__steam_name")
    ordering = ("display_name",)
    readonly_fields = ("discord_user_id", "created_at", "last_login")
    fieldsets = (
        (None, {"fields": ("display_name", "discord_user_id", "created_at")}),
        ("Admin login", {"fields": ("username", "password", "email", "last_login")}),
        (
            "Admin access",
            {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")},
        ),
    )
    inlines = (SteamAccountInline,)

    @admin.display(description="Steam accounts")
    def steam_count(self, obj: Player) -> int:
        return obj.steam_accounts.count()

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False  # The bot makes players; `createsuperuser` makes admin logins.

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False


IMPORT_MAX_BYTES = 2_000_000
IMPORT_SALT = "league.interim.import"
IMPORT_MAX_AGE = 30 * 60  # A preview older than this has to be uploaded again.


class InterimImportForm(forms.Form):
    community = forms.ModelChoiceField(queryset=Community.objects.order_by("name"))
    file = forms.FileField(
        help_text="NeatQueue's leaderboard export as it comes, or a CSV of discord_id, rating, "
        "wins, losses. A header row may name the columns; a name column is optional."
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        communities = list(Community.objects.all()[:2])
        if len(communities) == 1:
            self.fields["community"].initial = communities[0].pk
            self.fields["community"].widget = forms.HiddenInput()

    def clean_file(self) -> interim.ParsedImport:
        upload = self.cleaned_data["file"]
        if upload.size > IMPORT_MAX_BYTES:
            raise ValidationError("That file is too big. Split it, or trim unneeded columns.")
        try:
            text = upload.read().decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValidationError("That file isn't UTF-8 text. Save it as CSV.") from exc
        try:
            parsed = interim.parse_csv(text)
        except InvalidAction as exc:
            raise ValidationError(exc.message) from exc
        if not parsed.rows:
            raise ValidationError("No players could be read from that file.")
        return parsed


@admin.register(InterimRating)
class InterimRatingAdmin(ReadOnlyAdmin):
    """NeatQueue points: change them by importing again (Import NeatQueue CSV), never by hand,
    or the next rebuild would undo it."""

    def get_urls(self) -> list[URLPattern]:
        upload = path(
            "import/",
            self.admin_site.admin_view(self.import_view),
            name="league_interimrating_import",
        )
        return [upload, *super().get_urls()]

    def import_view(self, request: HttpRequest) -> HttpResponse:
        """Upload, preview, Confirm. The parsed rows ride along signed, so Confirm imports
        exactly what was previewed."""
        if not request.user.has_perm("league.add_interimrating"):
            raise PermissionDenied
        if request.method == "POST" and "payload" in request.POST:
            try:
                data = signing.loads(
                    request.POST["payload"], salt=IMPORT_SALT, max_age=IMPORT_MAX_AGE
                )
                community = Community.objects.get(pk=data["community"])
                rows = interim.decode_rows(data["rows"])
            except (signing.BadSignature, Community.DoesNotExist, KeyError, ValueError):
                messages.error(request, "That preview expired or was changed. Upload it again.")
                return HttpResponseRedirect(reverse("admin:league_interimrating_import"))
            count = interim.apply_import(community, rows)
            messages.success(
                request,
                f"Imported {plural(count, 'player')} for {community}. The interim is on: "
                "players see NeatQueue points until you turn Interim points off in Runtime "
                "settings.",
            )
            return HttpResponseRedirect(_changelist(self))

        posted = request.method == "POST"
        form = InterimImportForm(
            request.POST if posted else None, request.FILES if posted else None
        )
        context = _context(self, request, "Import NeatQueue points")
        context["form"] = form
        if posted and form.is_valid():
            parsed: interim.ParsedImport = form.cleaned_data["file"]
            community = form.cleaned_data["community"]
            context.update(
                community=community,
                preview=interim.preview_lines(community, parsed),
                problems=parsed.problems[:50],
                more_problems=max(0, len(parsed.problems) - 50),
                payload=signing.dumps(
                    {"community": community.pk, "rows": interim.encode_rows(parsed.rows)},
                    salt=IMPORT_SALT,
                    compress=True,
                ),
            )
        return TemplateResponse(request, "admin/league/interimrating/import.html", context)

    list_display = (
        "player",
        "season",
        "points",
        "wins",
        "losses",
        "games_played",
        "games_here",
        "imported_points",
        "imported_at",
    )
    list_filter = ("season",)
    search_fields = ("player__display_name", "player__discord_user_id")

    @admin.display(description="Games")
    def games_played(self, obj: InterimRating) -> int:
        """Wins plus losses, NeatQueue's included, so it agrees with the record beside it."""
        return obj.wins + obj.losses

    @admin.display(description="Games here", ordering="games")
    def games_here(self, obj: InterimRating) -> int:
        return obj.games


@admin.register(PlayerSwap)
class PlayerSwapAdmin(ReadOnlyAdmin):
    list_display = ("match", "requested_by", "give", "take", "status", "created_at")
    list_filter = ("status",)


@admin.register(StaffAlert)
class StaffAlertAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "community", "match", "kind", "area", "status", "closed_by")
    list_filter = ("status", "kind", "area")
    search_fields = ("text", "outcome")


@admin.register(Penalty)
class PenaltyAdmin(ReadOnlyAdmin):
    list_display = (
        "player",
        "kind",
        "tier",
        "strikes",
        "strikes_waived",
        "starts_at",
        "expires_at",
        "revoked_at",
    )
    list_filter = ("kind",)
    search_fields = ("player__display_name",)


class ParticipantInline(ReadOnlyInline):
    model = MatchParticipant
    fields = (
        "player",
        "team",
        "is_captain",
        "draft_pick_number",
        "ready_at",
        "removed_reason",
        "left_early",
    )


class DraftActionInline(ReadOnlyInline):
    model = DraftAction
    fields = ("step_index", "action", "team", "target_player", "target_champion", "source")


class TransitionInline(ReadOnlyInline):
    model = MatchTransition
    fields = ("from_status", "to_status", "source", "actor", "created_at")


class SubmissionInline(ReadOnlyInline):
    model = ResultSubmission
    fields = (
        "captain",
        "verdict",
        "claimed_winner",
        "deadlock_match_id",
        "archive_message_id",
        "created_at",
    )


class ResultInline(ReadOnlyInline):
    model = MatchResult
    fields = ("revision", "outcome", "source", "actor", "reason", "created_at")


@admin.register(Match)
class MatchAdmin(ReadOnlyAdmin):
    list_display = ("id", "status", "winner", "mode_version", "created_at", "ended_at")
    list_filter = ("kind", "status", "season")
    inlines = (
        ParticipantInline,
        DraftActionInline,
        SubmissionInline,
        ResultInline,
        TransitionInline,
    )


@admin.register(PlayerRating)
class PlayerRatingAdmin(ReadOnlyAdmin):
    list_display = (
        "player",
        "season",
        "rating",
        "mu",
        "sigma",
        "games",
        "wins",
        "losses",
        "last_played_at",
    )
    list_filter = ("season",)
    search_fields = ("player__display_name",)
    ordering = ("-rating",)


@admin.register(RatingRun)
class RatingRunAdmin(ReadOnlyAdmin):
    list_display = ("id", "kind", "match", "season", "algo_version", "reason", "created_at")
    list_filter = ("kind",)

    def get_urls(self) -> list[URLPattern]:
        check = path(
            "check-ledger/",
            self.admin_site.admin_view(self.ledger_view),
            name="league_ratingrun_check_ledger",
        )
        return [check, *super().get_urls()]

    def ledger_view(self, request: HttpRequest) -> HttpResponse:
        """Check that every season's ratings add up. Read-only."""
        if not self.has_view_permission(request):
            raise PermissionDenied
        problems = integrity.check_all()
        if not problems:
            messages.success(request, "Ratings add up.")
        for problem in problems[:50]:
            messages.error(request, problem)
        if len(problems) > 50:
            messages.error(request, f"...and {len(problems) - 50} more.")
        return HttpResponseRedirect(_changelist(self))


@admin.register(RatingEvent)
class RatingEventAdmin(ReadOnlyAdmin):
    list_display = (
        "id",
        "player",
        "match",
        "delta",
        "rating_after",
        "mu_delta",
        "award_adj",
        "expected",
        "created_at",
    )
    search_fields = ("player__display_name",)


@admin.register(QueueEntry)
class QueueEntryAdmin(ReadOnlyAdmin):
    list_display = ("player", "community", "joined_at")


@admin.register(CaptainVote)
class CaptainVoteAdmin(ReadOnlyAdmin):
    list_display = ("match", "voter", "candidate", "created_at")


@admin.register(MatchResource)
class MatchResourceAdmin(ReadOnlyAdmin):
    list_display = ("match", "kind", "discord_id", "deleted_at")


@admin.register(OutboxEffect)
class OutboxEffectAdmin(ReadOnlyAdmin):
    list_display = ("id", "kind", "match", "lane", "status", "attempts", "run_after", "last_error")
    list_filter = ("status", "kind")
    actions = ("retry",)

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        # Rows stay read-only (no change form); this lets the Retry action show.
        return obj is None and request.user.has_perm("league.change_outboxeffect")

    @admin.action(description="Retry the selected failed effects")
    def retry(self, request: HttpRequest, queryset: QuerySet[OutboxEffect]) -> None:
        # The IDs first: on a list filtered to failed ones, the queryset no longer holds them once
        # they're pending again.
        selected = list(queryset.values_list("pk", flat=True))
        count = effects.retry_failed(selected)
        skipped = len(selected) - count
        note = (
            f" Left {plural(skipped, 'effect')} alone: only failed ones run again."
            if skipped
            else ""
        )
        messages.success(request, f"Queued {plural(count, 'effect')} to run again.{note}")


@admin.register(ScoreboardRead)
class ScoreboardReadAdmin(ReadOnlyAdmin):
    list_display = ("id", "match", "status", "ocr_winner", "ocr_match_id", "badges_clean")
    list_filter = ("status",)


@admin.register(PlayerMatchStat)
class PlayerMatchStatAdmin(ReadOnlyAdmin):
    list_display = (
        "match",
        "ocr_name",
        "player",
        "team",
        "hero_name",
        "badge",
        "kills",
        "deaths",
        "assists",
        "player_damage",
        "map_source",
    )
    search_fields = ("ocr_name", "player__display_name")


@admin.register(MatchAward)
class MatchAwardAdmin(ReadOnlyAdmin):
    list_display = ("match", "revision", "player", "kind", "source", "actor", "created_at")
    list_filter = ("source", "kind")


@admin.register(PlayerAlias)
class PlayerAliasAdmin(admin.ModelAdmin):
    """In-game names. Staff can confirm or remove a wrong one."""

    list_display = ("name", "player", "confirmed", "times_seen", "last_seen_at")
    list_filter = ("confirmed",)
    search_fields = ("name", "player__display_name")


@admin.register(StrikeAdjustment)
class StrikeAdjustmentAdmin(ReadOnlyAdmin):
    list_display = ("player", "delta", "actor", "reason", "created_at")


@admin.register(CaptainOverride)
class CaptainOverrideAdmin(ReadOnlyAdmin):
    list_display = ("player", "status", "actor", "reason", "created_at")
    list_filter = ("status",)


@admin.register(ApiMatchCheck)
class ApiMatchCheckAdmin(ReadOnlyAdmin):
    list_display = (
        "match",
        "deadlock_match_id",
        "attempt",
        "status",
        "api_winner",
        "duration_s",
        "created_at",
    )
    list_filter = ("status",)


@admin.register(EarlyLeave)
class EarlyLeaveAdmin(ReadOnlyAdmin):
    list_display = ("match", "leaver", "requested_by", "status", "resolved_by", "created_at")
    list_filter = ("status",)


@admin.register(PrioEntry)
class PrioEntryAdmin(ReadOnlyAdmin):
    """The priority list. Read-only: it follows the match queue; staff use /removeprio."""

    list_display = ("display_name", "community", "discord_user_id", "queued_at", "grace_until")
    list_filter = ("community",)


@admin.register(ChannelPing)
class ChannelPingAdmin(ReadOnlyAdmin):
    """Named pings (/pingchannel). Managed from Discord, so their mentions are checked."""

    list_display = ("name", "community", "channel_id", "timer_minutes", "last_ping_at")
    list_filter = ("community",)
