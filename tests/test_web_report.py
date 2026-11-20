"""Reporting a result from the web: `POST /api/matches/{id}/report/`.

Discord is faked at the HTTP level (`httpx.MockTransport`), so these see exactly what the web
process would send: the file, its name, the message text and the mentions it allows.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from league.domain.engine import Status
from league.domain.images import MAX_IMAGE_BYTES
from league.integrations import discord_rest
from league.models import Community, Match, Player, ResultSubmission
from league.services import community, queue, ratings, results
from league.web.api import report as web_report
from league.web.auth.session import SESSION_KEY
from tests.conftest import make_player
from tests.helpers import fresh, image, to_in_progress

pytestmark = pytest.mark.django_db

ARCHIVE = 777_000
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 64
DEADLOCK_ID = "38211457"


@dataclass
class FakeDiscord:
    status: int = 200
    seen: list[httpx.Request] = field(default_factory=list)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        if self.status != 200:
            return httpx.Response(self.status, json={"message": "Nope", "code": 0})
        return httpx.Response(
            200, json={"id": "5550001", "attachments": [{"id": "5550002", "url": "https://x"}]}
        )

    def payload(self) -> dict[str, Any]:
        """The upload's `payload_json` part."""
        body = self.seen[-1].content
        start = body.index(b'name="payload_json"')
        part = body[body.index(b"\r\n\r\n", start) + 4 :]
        return json.loads(part[: part.index(b"\r\n--")])  # type: ignore[no-any-return]


@pytest.fixture
def discord(monkeypatch: pytest.MonkeyPatch, settings: Any) -> FakeDiscord:
    settings.DISCORD_TOKEN = "bot-token"
    fake = FakeDiscord()
    transport = httpx.MockTransport(fake.handle)
    monkeypatch.setattr(
        discord_rest,
        "_client",
        lambda: httpx.Client(
            base_url=discord_rest.api_base(), headers=discord_rest._headers(), transport=transport
        ),
    )
    monkeypatch.setattr(discord_rest, "_sleep", lambda _seconds: None)
    return fake


@pytest.fixture(autouse=True)
def web(league: Community, settings: Any) -> Iterator[Community]:
    settings.WEB_GUILD_ID = league.discord_guild_id
    Community.objects.filter(pk=league.pk).update(archive_channel_id=ARCHIVE)
    yield league


@pytest.fixture
def match(popped: Match) -> Match:
    return to_in_progress(popped)


def client_for(player: Player, **kwargs: Any) -> Client:
    client = Client(**kwargs)
    session = client.session
    session[SESSION_KEY] = player.pk
    session.save()
    return client


def upload(data: bytes = PNG, name: str = "scoreboard.png") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, data, content_type="image/png")


def report(match: Match, player: Player, client: Client | None = None, **fields: Any) -> Any:
    form: dict[str, Any] = {
        "winner": "A",
        "deadlock_match_id": DEADLOCK_ID,
        "screenshot": upload(),
    }
    form.update(fields)
    form = {key: value for key, value in form.items() if value is not None}
    client = client or client_for(player)
    return client.post(f"/api/matches/{match.pk}/report/", form)


def refusal(response: Any, status: int = 400) -> str:
    assert response.status_code == status, response.content
    assert response["Cache-Control"] == "no-store"
    body = response.json()
    assert set(body) == {"refusal"}
    text: str = body["refusal"]
    return text


# --- Reporting --------------------------------------------------------------------------------


def test_a_captain_reports_with_a_screenshot(match: Match, discord: FakeDiscord) -> None:
    captain = match.captain_of("A").player
    mvp, key = (
        match.participants.filter(team="A", is_captain=False)
        .order_by("id")[:2]
        .values_list("player_id", flat=True)
    )
    response = report(
        match, captain, deadlock_match_id=" 38211457 ", mvp=str(mvp), keys=[str(key), str(mvp)]
    )
    assert response.status_code == 200, response.content
    assert response.json() == {"status": "awaiting_confirmation"}
    assert response["Cache-Control"] == "no-store"

    sent = discord.seen[-1]
    assert sent.url.path.endswith(f"/channels/{ARCHIVE}/messages")
    filename = f"match-{match.pk}-player-{captain.pk}.png"
    assert discord.payload() == {
        "content": f"Match #{match.pk}: submitted by {captain.display_name}",
        "attachments": [{"id": 0, "filename": filename}],
        "allowed_mentions": {"parse": []},
    }
    assert f'filename="{filename}"'.encode() in sent.content and PNG in sent.content

    match = fresh(match)
    assert match.status == Status.AWAITING_CONFIRMATION
    assert match.deadlock_match_id == int(DEADLOCK_ID)
    submission = ResultSubmission.objects.get(match=match)
    assert submission.captain == captain and submission.claimed_winner == "A"
    assert (submission.archive_channel_id, submission.archive_message_id) == (ARCHIVE, 5550001)
    assert submission.attachment_id == 5550002 and submission.image_extension == "png"
    assert submission.deadlock_match_id == int(DEADLOCK_ID)
    # The MVP picked as a key player too stays MVP, as on Discord.
    assert ratings.current_awards(match) == {mvp: "mvp", key: "key"}


def test_a_captain_reports_without_a_screenshot(match: Match, discord: FakeDiscord) -> None:
    response = report(match, match.captain_of("A").player, screenshot=None)
    assert response.status_code == 200 and response.json() == {"status": "awaiting_confirmation"}
    assert not discord.seen
    submission = ResultSubmission.objects.get(match=match)
    assert submission.archive_message_id is None and submission.image_sha256 == ""
    assert submission.deadlock_match_id == int(DEADLOCK_ID)


def test_without_a_screenshot_no_archive_channel_is_needed(
    league: Community, match: Match, discord: FakeDiscord
) -> None:
    Community.objects.filter(pk=league.pk).update(archive_channel_id=None)
    response = report(match, match.captain_of("A").player, screenshot=None)
    assert response.status_code == 200, response.content


def test_the_other_captain_can_confirm_with_their_own_report(
    match: Match, discord: FakeDiscord
) -> None:
    results.submit_report(match.pk, match.captain_of("A").player, "B", image(1))
    response = report(match, match.captain_of("B").player, winner="B")
    assert response.status_code == 200 and response.json() == {"status": "completed"}


def test_a_report_for_the_other_winner_is_a_dispute(match: Match, discord: FakeDiscord) -> None:
    results.submit_report(match.pk, match.captain_of("A").player, "A", image(1))
    response = report(match, match.captain_of("B").player, winner="B", screenshot=None)
    assert response.status_code == 200 and response.json() == {"status": "disputed"}


def test_only_a_captain_can_report(match: Match, discord: FakeDiscord) -> None:
    player = match.participants.filter(is_captain=False).first()
    assert player is not None
    assert refusal(report(match, player.player)) == "Only a captain can do that."
    assert not discord.seen


def test_a_match_not_in_game_cant_be_reported(popped: Match, discord: FakeDiscord) -> None:
    player = popped.participants.first()
    assert player is not None
    assert refusal(report(popped, player.player)) == "This match isn't waiting for a result."
    assert not discord.seen


def test_a_captain_reports_only_once(match: Match, discord: FakeDiscord) -> None:
    captain = match.captain_of("A").player
    assert report(match, captain).status_code == 200
    assert refusal(report(match, captain)) == "You've already responded for this match."
    assert len(discord.seen) == 1


@pytest.mark.parametrize(
    ("fields", "text"),
    [
        ({"winner": "C"}, web_report.NO_WINNER),
        ({"winner": None}, web_report.NO_WINNER),
        ({"deadlock_match_id": None}, web_report.NO_MATCH_ID),
        ({"deadlock_match_id": "  "}, web_report.NO_MATCH_ID),
        ({"deadlock_match_id": "12ab"}, web_report.BAD_MATCH_ID),
        ({"deadlock_match_id": "0"}, web_report.BAD_MATCH_ID),
        ({"deadlock_match_id": "1" * 19}, web_report.BAD_MATCH_ID),
        ({"screenshot": upload(b"GIF89a....")}, web_report.NOT_AN_IMAGE),
        ({"mvp": "someone"}, web_report.BAD_REQUEST),
        ({"keys": ["1", "2", "3"]}, web_report.TOO_MANY_KEYS),
    ],
)
def test_a_bad_form_is_refused_before_anything_is_sent(
    match: Match, discord: FakeDiscord, fields: dict[str, Any], text: str
) -> None:
    assert refusal(report(match, match.captain_of("A").player, **fields)) == text
    assert not discord.seen
    assert fresh(match).status == Status.IN_PROGRESS


def test_the_refusals_are_the_bots_own_words() -> None:
    assert web_report.NO_MATCH_ID.startswith("Enter the Deadlock match ID.")
    assert web_report.TOO_LARGE == "That file is too large: the limit is 20 MB."
    assert web_report.NO_ARCHIVE == "The archive channel isn't set up. Ask staff to run /setup."


def test_a_20_mb_screenshot_is_taken_and_a_bigger_one_refused(
    match: Match, discord: FakeDiscord
) -> None:
    captain = match.captain_of("A").player
    big = PNG + b"\0" * (MAX_IMAGE_BYTES - len(PNG) + 1)
    assert refusal(report(match, captain, screenshot=upload(big))) == web_report.TOO_LARGE
    assert not discord.seen
    response = report(match, captain, screenshot=upload(big[:MAX_IMAGE_BYTES]))
    assert response.status_code == 200, response.content
    assert len(discord.seen[-1].content) > MAX_IMAGE_BYTES


def test_with_a_screenshot_and_no_archive_channel_nothing_is_sent(
    league: Community, match: Match, discord: FakeDiscord
) -> None:
    Community.objects.filter(pk=league.pk).update(archive_channel_id=None)
    assert refusal(report(match, match.captain_of("A").player)) == web_report.NO_ARCHIVE
    assert not discord.seen
    assert not ResultSubmission.objects.filter(match=match).exists()


@pytest.mark.parametrize("status", [500, 403, 404])
def test_a_discord_failure_saves_no_report(
    match: Match, discord: FakeDiscord, status: int, caplog: pytest.LogCaptureFixture
) -> None:
    discord.status = status
    response = report(match, match.captain_of("A").player)
    assert refusal(response, 502) == web_report.UPLOAD_FAILED
    assert not ResultSubmission.objects.filter(match=match).exists()
    assert fresh(match).status == Status.IN_PROGRESS
    assert "didn't reach Discord" in caplog.text and "bot-token" not in caplog.text


def test_reporting_needs_the_csrf_token(match: Match, discord: FakeDiscord) -> None:
    captain = match.captain_of("A").player
    client = client_for(captain, enforce_csrf_checks=True)
    assert report(match, captain, client).status_code == 403
    client.get("/api/session/")  # Sets the CSRF cookie, as the SPA's first request does.
    token = client.cookies["csrftoken"].value
    response = client.post(
        f"/api/matches/{match.pk}/report/",
        {"winner": "A", "deadlock_match_id": DEADLOCK_ID, "screenshot": upload()},
        headers={"X-CSRFToken": token},
    )
    assert response.status_code == 200, response.content
    assert not ResultSubmission.objects.exclude(captain=captain).exists()


def test_reporting_needs_a_signed_in_player(match: Match, discord: FakeDiscord) -> None:
    response = Client().post(f"/api/matches/{match.pk}/report/", {"winner": "A"})
    assert response.status_code == 401 and response.json() == {"error": "signed-out"}


def test_reporting_is_post_only(match: Match) -> None:
    captain = match.captain_of("A").player
    assert client_for(captain).get(f"/api/matches/{match.pk}/report/").status_code == 405


def test_another_servers_match_is_not_found(discord: FakeDiscord) -> None:
    other = community.ensure(guild_id=4242, name="Elsewhere")
    others = [make_player(number) for number in range(201, 213)]
    for player in others:
        queue.join(other.pk, player)
    elsewhere = to_in_progress(Match.objects.get(community=other))
    response = report(elsewhere, elsewhere.captain_of("A").player)
    assert response.status_code == 404 and response.json() == {"error": "not-found"}
    assert client_for(others[0]).post("/api/matches/99999999/report/").status_code == 404
    assert not discord.seen
