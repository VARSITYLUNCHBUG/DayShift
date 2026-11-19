"""Players are the user model: one Discord account each, required, and any number of Steam ones."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import IntegrityError, transaction

from league.models import Community, Player, SteamAccount
from league.services import steam
from tests.conftest import make_player

pytestmark = pytest.mark.django_db


def test_the_user_model_is_the_player() -> None:
    assert get_user_model() is Player


def test_a_player_the_bot_makes_has_no_password(league: Community) -> None:
    player = make_player(1)
    assert player.username == f"discord-{player.discord_user_id}"
    assert not player.has_usable_password()
    assert not player.is_staff and not player.is_superuser


def test_a_discord_account_belongs_to_one_player(league: Community) -> None:
    player = make_player(1)
    with pytest.raises(IntegrityError), transaction.atomic():
        Player.objects.create(discord_user_id=player.discord_user_id, username="someone-else")


def test_a_steam_account_belongs_to_one_player(league: Community) -> None:
    first, second = make_player(1), make_player(2)
    steam.link(first, 42)
    with pytest.raises(IntegrityError), transaction.atomic():
        SteamAccount.objects.create(player=second, account_id=42, linked_at=first.created_at)


def test_an_admin_login_needs_a_discord_id(league: Community) -> None:
    with pytest.raises(ValueError, match="Discord ID"):
        Player.objects.create_superuser("host", "host@example.test", "pw")


def test_createsuperuser_gives_an_existing_player_an_admin_login(league: Community) -> None:
    player = make_player(1)
    call_command(
        "createsuperuser",
        interactive=False,
        username="host",
        discord_user_id=player.discord_user_id,
        verbosity=0,
    )
    host = Player.objects.get(pk=player.pk)
    assert (host.username, host.is_staff, host.is_superuser) == ("host", True, True)
    assert host.display_name == "P1"  # Still the same player, with their history.
    assert Player.objects.count() == 1


def test_createsuperuser_makes_a_new_player_for_a_new_discord_id(league: Community) -> None:
    call_command(
        "createsuperuser",
        interactive=False,
        username="host",
        discord_user_id=900_000_000_000_000_003,
        verbosity=0,
    )
    host = Player.objects.get(username="host")
    assert host.is_superuser and host.discord_user_id == 900_000_000_000_000_003
    assert host.display_name == "host"
