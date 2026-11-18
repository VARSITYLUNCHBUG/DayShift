"""Staff alerts: cards in the staff channel, pinged to the right roles, closed by a ruling."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from django.db import connections

from bot.commands import setup as setup_commands
from bot.db import db
from league.domain.errors import NotAllowed
from league.models import Community, Match, StaffAlert
from league.models.alerts import AlertKind, AlertStatus
from league.models.matches import ResourceKind
from league.models.permissions import Area
from league.services import alerts, community, lobby, permissions
from league.services import results as results_service
from tests.conftest import make_player
from tests.helpers import fresh, to_in_progress
from tests.test_bot import FakeGateway, drain, live_notice_texts, popped_match, resource
from tests.test_handlers import click, fake_interaction, replies

pytestmark = pytest.mark.django_db(transaction=True)

STAFF_CHANNEL = 7005
DISPUTES_ROLE, RATINGS_ROLE, SETUP_ROLE = 601, 602, 603


@pytest.fixture
def server(transactional_db: None) -> Iterator[Community]:
    row = community.ensure(guild_id=999, name="Test")
    community.save_wiring(
        row.pk,
        waiting_room_channel_id=7001,
        queue_channel_id=7002,
        results_channel_id=7003,
        archive_channel_id=7004,
        staff_channel_id=STAFF_CHANNEL,
    )
    permissions.grant(row.pk, DISPUTES_ROLE, [Area.DISPUTES], granted_by=None)
    permissions.grant(row.pk, RATINGS_ROLE, [Area.RATINGS], granted_by=None)
    permissions.grant(row.pk, SETUP_ROLE, [Area.SETUP], granted_by=None)
    row.refresh_from_db()
    yield row
    asyncio.run(db(connections.close_all))


def _custom_ids(view: Any) -> list[str]:
    found: list[str] = []

    def walk(component: Any) -> None:
        if isinstance(component, dict):
            if "custom_id" in component:
                found.append(component["custom_id"])
            for value in component.values():
                walk(value)
        elif isinstance(component, list):
            for value in component:
                walk(value)

    walk(view.to_components())
    return found


def _text(view: Any) -> str:
    return str(view.to_components())


def _disputed(server: Community, gateway: FakeGateway) -> Match:
    match = to_in_progress(popped_match(server, gateway))
    results_service.on_in_progress_timeout(fresh(match))
    drain(gateway)
    return fresh(match)


def test_a_dispute_posts_one_card_to_the_disputes_roles(server: Community) -> None:
    gateway = FakeGateway()
    match = _disputed(server, gateway)
    alert = StaffAlert.objects.get(match=match)
    assert (alert.kind, alert.area, alert.status) == ("dispute", "disputes", "open")
    assert gateway.messages[STAFF_CHANNEL] == [alert.message_id]
    assert gateway.view_pings[alert.message_id] == [DISPUTES_ROLE]
    card = gateway.views[alert.message_id]
    assert any("resolve_a" in custom_id for custom_id in _custom_ids(card))
    assert "No captain has reported a result." in _text(card)
    # The match channel gets a short note, pinging nobody, and its board has no ruling buttons.
    assert live_notice_texts(gateway, match) == ["Sent to staff: No captain has reported a result."]
    board = gateway.views[resource(match, ResourceKind.BOARD_MESSAGE)]
    assert not any("resolve" in custom_id for custom_id in _custom_ids(board))


def test_a_dispute_still_open_is_posted_again_lower_down(server: Community) -> None:
    gateway = FakeGateway()
    match = _disputed(server, gateway)
    first = StaffAlert.objects.get(match=match).message_id
    results_service.on_disputed_timeout(fresh(match))
    drain(gateway)
    alert = StaffAlert.objects.get(match=match)
    assert alert.message_id != first
    assert gateway.messages[STAFF_CHANNEL] == [alert.message_id]  # The old card is gone.
    assert gateway.view_pings[alert.message_id] == [DISPUTES_ROLE]
    assert len(live_notice_texts(gateway, match)) == 1  # No second note in the match channel.


def test_a_ruling_from_the_card_closes_it(server: Community) -> None:
    gateway = FakeGateway()
    match = _disputed(server, gateway)
    message_id = StaffAlert.objects.get(match=match).message_id

    outsider = fake_interaction(make_player(90), role_ids=(RATINGS_ROLE,))
    click(outsider, "resolve_a", match.pk)
    assert "It needs Disputes access" in replies(outsider)[0]
    assert fresh(match).status == "disputed"

    staffer = make_player(91)
    click(fake_interaction(staffer, role_ids=(DISPUTES_ROLE,)), "resolve_a", match.pk)
    drain(gateway)
    assert fresh(match).winner == "A"
    alert = StaffAlert.objects.get(match=match)
    assert alert.status == AlertStatus.RESOLVED
    assert alert.closed_by == staffer and alert.outcome.endswith("won")
    assert message_id in gateway.edited
    card = gateway.views[message_id]
    assert _custom_ids(card) == []
    assert "Resolved by P91" in _text(card)
    assert "Disputed result, resolved" in _text(card) and "needs a decision" not in _text(card)


def test_a_void_answers_the_dispute(server: Community) -> None:
    gateway = FakeGateway()
    match = _disputed(server, gateway)
    lobby.staff_void(match.pk, None, "Replay")
    alert = StaffAlert.objects.get(match=match)
    assert alert.status == AlertStatus.RESOLVED
    assert alert.outcome == "Voided: Replay"


def test_other_alerts_are_dismissed_by_their_area(server: Community) -> None:
    gateway = FakeGateway()
    match = to_in_progress(popped_match(server, gateway))
    alert = alerts.raise_alert(
        server, AlertKind.AWARD_FREEZE, Area.RATINGS, "Check P1.", match=match, dedupe_key="k"
    )
    assert alert is not None
    assert (
        alerts.raise_alert(server, AlertKind.AWARD_FREEZE, Area.RATINGS, "Again", dedupe_key="k")
        is None
    )
    drain(gateway)
    alert.refresh_from_db()
    assert gateway.view_pings[alert.message_id] == [RATINGS_ROLE]
    # Staff-only findings stay out of the match channel.
    assert not any("Sent to staff" in text for text in live_notice_texts(gateway, match))

    wrong = fake_interaction(make_player(90), role_ids=(DISPUTES_ROLE,))
    click(wrong, "alert_dismiss", match.pk, str(alert.pk))
    assert "It needs Ratings access" in replies(wrong)[0]
    click(
        fake_interaction(make_player(91), role_ids=(RATINGS_ROLE,)),
        "alert_dismiss",
        match.pk,
        str(alert.pk),
    )
    drain(gateway)
    alert.refresh_from_db()
    assert alert.status == AlertStatus.DISMISSED
    assert "Dismissed by P91" in _text(gateway.views[alert.message_id])


def test_a_dispute_cannot_be_dismissed(server: Community) -> None:
    match = _disputed(server, FakeGateway())
    with pytest.raises(NotAllowed):
        alerts.dismiss(StaffAlert.objects.get(match=match).pk, make_player(91))


def test_without_a_staff_channel_the_card_goes_to_the_match_channel(server: Community) -> None:
    community.save_wiring(server.pk, staff_channel_id=None)
    gateway = FakeGateway()
    match = _disputed(server, gateway)
    alert = StaffAlert.objects.get(match=match)
    assert alert.channel_id == resource(match, ResourceKind.TEXT)
    assert live_notice_texts(gateway, match) == []  # The card is the note.


def test_a_lobby_discord_refuses_tells_setup_staff(server: Community) -> None:
    gateway = FakeGateway()
    match = popped_match(server, gateway)
    lobby.fail_lobby_setup(match.pk, "Discord couldn't create the lobby")
    drain(gateway)
    alert = StaffAlert.objects.get(match=match)
    assert (alert.kind, alert.area) == ("lobby_failed", "setup")
    assert gateway.view_pings[alert.message_id] == [SETUP_ROLE]
    assert fresh(match).status == "voided"


def test_setup_creates_a_hidden_staff_channel(server: Community) -> None:
    community.save_wiring(server.pk, staff_channel_id=None)
    server.refresh_from_db()
    guild = MagicMock()
    guild.create_text_channel = AsyncMock(return_value=MagicMock(id=7777))
    interaction = MagicMock()
    interaction.guild = guild
    asyncio.run(setup_commands.ensure_channels(interaction, server))
    (name,) = guild.create_text_channel.call_args.args
    overwrites = guild.create_text_channel.call_args.kwargs["overwrites"]
    assert name == "staff-alerts"
    assert overwrites[guild.default_role] == discord.PermissionOverwrite(view_channel=False)
    assert Community.objects.get(pk=server.pk).staff_channel_id == 7777
