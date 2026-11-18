"""The Django admin as the host's console: settings, the active mode, seasons, the roster sync,
the NeatQueue import and the ledger check all run through the services, not raw row edits."""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from league.domain.mode_schema import ModeValidationError
from league.models import (
    Champion,
    Community,
    DraftModeVersion,
    InterimRating,
    OutboxEffect,
    Player,
    Season,
)
from league.services import champions, interim, modes, ocr, runtime
from tests.helpers import play_full_match

pytestmark = pytest.mark.django_db


@pytest.fixture
def host(league: Community) -> Client:
    user = get_user_model().objects.create_superuser("host", "host@example.test", "pw")
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def staff_only(league: Community) -> Client:
    """A staff login with no model permissions."""
    user = get_user_model().objects.create_user("helper", is_staff=True)
    client = Client()
    client.force_login(user)
    return client


def _form_data(response: Any) -> dict[str, Any]:
    """The change form as the page shows it, ready to post back with a few values changed."""
    data: dict[str, Any] = {}

    def add(form: Any) -> None:
        for name in form.fields:
            value = form[name].value()
            key = form.add_prefix(name)
            if value is None or value is False:
                continue
            if value is True:
                data[key] = "on"
            elif isinstance(value, list | tuple):
                data[key] = [str(item) for item in value]
            else:
                data[key] = value

    add(response.context["adminform"].form)
    for inline in response.context["inline_admin_formsets"]:
        formset = inline.formset
        management = formset.management_form
        for name in management.fields:
            data[management.add_prefix(name)] = management[name].value()
        for form in formset.forms:
            add(form)
    return data


def _settings_url(league: Community) -> str:
    return f"/admin/league/runtimesettings/{runtime.of(league).pk}/change/"


def _save_settings(host: Client, league: Community, **changes: Any) -> Any:
    url = _settings_url(league)
    data = _form_data(host.get(url))
    for name, value in changes.items():
        if value is False:
            data.pop(name, None)
        else:
            data[name] = "on" if value is True else value
    return host.post(url, data)


def _kinds() -> set[str]:
    return set(OutboxEffect.objects.values_list("kind", flat=True))


# --- Runtime settings ---------------------------------------------------------------------------


def test_turning_the_interim_on_rebuilds_points_and_redraws(
    host: Client, league: Community, players: list[Player]
) -> None:
    play_full_match(league, players, "A", 1)
    assert not InterimRating.objects.exists()
    OutboxEffect.objects.all().delete()

    response = _save_settings(host, league, interim_points=True)

    assert response.status_code == 302
    assert runtime.of(league).interim_points
    season = Season.objects.open_for(league)
    points = {row.points for row in InterimRating.objects.filter(season=season)}
    assert len(points) == 2 and 1000 not in points  # Winners up, losers down.
    assert {"render_leaderboard", "render_queue"} <= _kinds()


def test_changing_the_k_factor_rebuilds_the_points(
    host: Client, league: Community, players: list[Player]
) -> None:
    interim.set_enabled(league, True)
    play_full_match(league, players, "A", 1)
    before = set(InterimRating.objects.values_list("points", flat=True))
    _save_settings(host, league, interim_points=True, interim_k_factor=64)
    after = set(InterimRating.objects.values_list("points", flat=True))
    assert after != before and max(after) - 1000 == 2 * (max(before) - 1000)


def test_screenshot_reading_is_refused_where_it_cannot_run(
    host: Client, league: Community, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ocr, "available", lambda: False)
    response = _save_settings(host, league, score_ocr="on")
    assert response.status_code == 200
    assert "isn&#x27;t available on this install" in response.content.decode()
    assert runtime.of(league).score_ocr == "off"


def test_an_unknown_region_is_refused_and_a_known_one_saved(
    host: Client, league: Community
) -> None:
    response = _save_settings(host, league, lobby_region="atlantis")
    assert response.status_code == 200
    assert runtime.of(league).lobby_region == ""
    response = _save_settings(host, league, lobby_region="south_africa")
    assert response.status_code == 302
    assert runtime.of(league).lobby_region == "south_africa"


def test_settings_rows_cannot_be_added_or_moved(host: Client, league: Community) -> None:
    assert host.get("/admin/league/runtimesettings/add/").status_code == 403
    page = host.get(_settings_url(league))
    assert "community" not in page.context["adminform"].form.fields


# --- Communities ---------------------------------------------------------------------------------


def _community_url(league: Community) -> str:
    return f"/admin/league/community/{league.pk}/change/"


def test_choosing_a_mode_activates_it_and_redraws_the_queue(
    host: Client, league: Community
) -> None:
    target = DraftModeVersion.objects.filter(slug="bebot_2ban").order_by("-version").first()
    assert target is not None and league.active_mode_id != target.pk
    OutboxEffect.objects.all().delete()
    data = _form_data(host.get(_community_url(league)))
    data["active_mode"] = target.pk
    response = host.post(_community_url(league), data)
    assert response.status_code == 302
    league.refresh_from_db()
    assert league.active_mode_id == target.pk
    assert "render_queue" in _kinds()


def test_only_the_latest_version_of_each_mode_is_offered(host: Client, league: Community) -> None:
    current = DraftModeVersion.objects.get(pk=league.active_mode_id)
    newer = modes.publish({**current.body, "name": "Renamed"})
    page = host.get(_community_url(league))
    offered = set(page.context["adminform"].form.fields["active_mode"].queryset)
    latest = {version.pk for version in modes.latest_versions()}
    assert newer in offered and current in offered  # The active one stays, to save other fields.
    assert {version.pk for version in offered} - latest == {current.pk}


def test_a_mode_that_cannot_run_is_refused(
    host: Client, league: Community, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(_body: object) -> None:
        raise ModeValidationError(["captains: broken"])

    target = DraftModeVersion.objects.filter(slug="bebot_2ban").order_by("-version").first()
    assert target is not None
    data = _form_data(host.get(_community_url(league)))
    monkeypatch.setattr(modes, "validate_body", broken)
    data["active_mode"] = target.pk
    response = host.post(_community_url(league), data)
    assert response.status_code == 200
    assert "captains: broken" in response.content.decode()
    league.refresh_from_db()
    assert league.active_mode_id != target.pk


def test_the_wiring_is_read_only(host: Client, league: Community) -> None:
    Community.objects.filter(pk=league.pk).update(queue_channel_id=111, pug_role_id=222)
    page = host.get(_community_url(league))
    fields = page.context["adminform"].form.fields
    assert not {"queue_channel_id", "pug_role_id", "discord_guild_id"} & set(fields)
    data = _form_data(page)
    data["queue_channel_id"] = 999
    host.post(_community_url(league), data)
    league.refresh_from_db()
    assert league.queue_channel_id == 111
    assert host.get("/admin/league/community/add/").status_code == 403


def test_the_server_page_shows_settings_status(host: Client, league: Community) -> None:
    body = host.get(_community_url(league)).content.decode()
    assert "Reading screenshots: Off" in body
    assert "Result checks: on" in body


def test_settings_saved_on_the_server_page_follow_through(
    host: Client, league: Community, players: list[Player]
) -> None:
    play_full_match(league, players, "A", 1)
    runtime.of(league)
    data = _form_data(host.get(_community_url(league)))
    data["runtime-0-interim_points"] = "on"
    response = host.post(_community_url(league), data)
    assert response.status_code == 302
    assert runtime.of(league).interim_points
    assert InterimRating.objects.exists()


# --- Seasons -------------------------------------------------------------------------------------


def test_seasons_start_through_the_server_action(host: Client, league: Community) -> None:
    first = Season.objects.open_for(league)
    assert host.get("/admin/league/season/add/").status_code == 403
    action = {"action": "start_next_season", "_selected_action": [league.pk]}

    page = host.post("/admin/league/community/", action)
    assert page.status_code == 200
    assert f"This closes <strong>{first.name}</strong>" in page.content.decode()

    refused = host.post("/admin/league/community/", {**action, "confirm": "yes", "params": "[1]"})
    assert "Give an object" in refused.content.decode()
    unknown = host.post(
        "/admin/league/community/", {**action, "confirm": "yes", "params": '{"nope": 1}'}
    )
    assert "Unknown rating parameters: nope" in unknown.content.decode()
    assert Season.objects.open_for(league).pk == first.pk

    done = host.post(
        "/admin/league/community/", {**action, "confirm": "yes", "params": '{"beta": 3.5}'}
    )
    assert done.status_code == 302
    second = Season.objects.open_for(league)
    assert second.number == 2 and second.rating_params == {"beta": 3.5}
    first.refresh_from_db()
    assert first.ended_at is not None
    assert Season.objects.filter(community=league).count() == 2


# --- Champions -----------------------------------------------------------------------------------


def test_the_roster_sync_previews_then_applies(
    host: Client, league: Community, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = [
        champions.RemoteChampion(id=c.pk, name=c.name, icon_url="") for c in Champion.objects.all()
    ]
    newcomer = champions.RemoteChampion(id=200, name="Newcomer", icon_url="")
    monkeypatch.setattr(champions, "fetch_remote", lambda: [*current, newcomer])

    assert "Sync with Deadlock API" in host.get("/admin/league/champion/").content.decode()
    preview = host.get("/admin/league/champion/sync/")
    assert "Newcomer (ID 200)" in preview.content.decode()
    assert not Champion.objects.filter(pk=200).exists()

    applied = host.post("/admin/league/champion/sync/", follow=True)
    assert "Roster updated" in applied.content.decode()
    assert Champion.objects.get(pk=200).is_enabled


def test_the_roster_sync_reports_an_unreachable_api(
    host: Client, league: Community, monkeypatch: pytest.MonkeyPatch
) -> None:
    import httpx

    def down() -> list[champions.RemoteChampion]:
        raise httpx.ConnectError("down")

    monkeypatch.setattr(champions, "fetch_remote", down)
    response = host.get("/admin/league/champion/sync/", follow=True)
    assert "Couldn&#x27;t reach the Deadlock API" in response.content.decode()


# --- NeatQueue import ----------------------------------------------------------------------------

CSV = b"Discord ID,Rating,Wins,Losses,Name\n111,1240,40,22,Kestrel\n222,980,5,9,Pike\nbad,row\n"


def _upload(host: Client, league: Community, content: bytes = CSV) -> Any:
    form = host.get("/admin/league/interimrating/import/")
    assert form.context["form"]["community"].is_hidden  # One server: nothing to choose.
    upload = SimpleUploadedFile("neatqueue.csv", content, content_type="text/csv")
    return host.post(
        "/admin/league/interimrating/import/", {"community": league.pk, "file": upload}
    )


def test_the_import_previews_then_confirms_exactly_what_was_shown(
    host: Client, league: Community
) -> None:
    assert "Import NeatQueue CSV" in host.get("/admin/league/interimrating/").content.decode()
    preview = _upload(host, league)
    body = preview.content.decode()
    assert "Import NeatQueue points for 2 players" in body
    assert "Highest: Kestrel 1240, Pike 980" in body
    assert "Line 4" in body  # The unreadable row is listed as skipped.
    assert not InterimRating.objects.exists()

    done = host.post(
        "/admin/league/interimrating/import/", {"payload": preview.context["payload"]}, follow=True
    )
    assert "Imported 2 players" in done.content.decode()
    assert runtime.of(league).interim_points
    season = Season.objects.open_for(league)
    standings = interim.standings(season)
    kestrel = Player.objects.get(discord_user_id=111)
    assert standings[kestrel.pk] == interim.Standing(1240, 40, 22)


def test_a_changed_or_bad_import_is_refused(host: Client, league: Community) -> None:
    payload = _upload(host, league).context["payload"]
    tampered = host.post(
        "/admin/league/interimrating/import/", {"payload": payload[:-2] + "xx"}, follow=True
    )
    assert "expired or was changed" in tampered.content.decode()
    assert not InterimRating.objects.exists()

    empty = _upload(host, league, b"\n")
    assert "That file is empty." in empty.content.decode()
    not_text = _upload(host, league, b"\xff\xfe\x00bad")
    assert "isn&#x27;t UTF-8" in not_text.content.decode()


# --- Ledger --------------------------------------------------------------------------------------


def test_the_ledger_check_reports_a_clean_ledger(host: Client, league: Community) -> None:
    listing = host.get("/admin/league/ratingrun/")
    assert "Check ledger" in listing.content.decode()
    response = host.get("/admin/league/ratingrun/check-ledger/", follow=True)
    assert "Ratings add up." in response.content.decode()


# --- Permissions ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "/admin/league/champion/sync/",
        "/admin/league/interimrating/import/",
        "/admin/league/ratingrun/check-ledger/",
    ],
)
def test_the_host_tools_need_permissions(staff_only: Client, url: str) -> None:
    assert staff_only.get(url).status_code == 403


def test_the_host_tools_need_a_login(league: Community) -> None:
    response = Client().get("/admin/league/interimrating/import/")
    assert response.status_code == 302 and "/admin/login/" in response["Location"]
