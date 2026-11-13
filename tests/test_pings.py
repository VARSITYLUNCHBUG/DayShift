"""Named channel pings (/pingchannel, /ping): only what staff set up can mention anyone."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from bot.commands import pings as ping_commands
from league.domain.errors import InvalidAction, NotAllowed
from league.models import ChannelPing, Community
from league.services import pings
from tests.conftest import Clock, make_player
from tests.test_handlers import fake_interaction, wired  # noqa: F401  (a fixture)

CHANNEL = 8200
ROLE = 555000000000000001
MEMBER = 555000000000000002


@pytest.mark.parametrize(
    ("mention", "roles", "users"),
    [
        (f"<@&{ROLE}>", [ROLE], []),
        (f"<@{MEMBER}>", [], [MEMBER]),
        (f"<@!{MEMBER}>  <@&{ROLE}> <@&{ROLE}>", [ROLE], [MEMBER]),
    ],
)
def test_mentions_parse_to_ids(mention: str, roles: list[int], users: list[int]) -> None:
    targets = pings.parse_targets(mention)
    assert targets.role_ids == roles and targets.user_ids == users


@pytest.mark.parametrize(
    "mention", ["", "   ", "@everyone", "@here", "@PUGS", f"<@&{ROLE}> come play", "<#123>"]
)
def test_anything_but_role_and_member_mentions_is_refused(mention: str) -> None:
    with pytest.raises(InvalidAction):
        pings.parse_targets(mention)


def test_a_ping_mentions_at_most_ten() -> None:
    with pytest.raises(InvalidAction, match="at most"):
        pings.parse_targets(" ".join(f"<@&{ROLE + n}>" for n in range(11)))


def _add(community: Community, name: str = "pugs", **kwargs: Any) -> ChannelPing:
    return pings.add(
        community.pk,
        kwargs.get("channel", CHANNEL),
        name,
        pings.parse_targets(f"<@&{ROLE}>"),
        kwargs.get("timer", 15),
        kwargs.get("required_role"),
    )


@pytest.mark.django_db
def test_cooldown(league: Community, clock: Clock) -> None:
    _add(league)
    pings.claim(CHANNEL, None, set())
    with pytest.raises(InvalidAction, match="cooldown"):
        pings.claim(CHANNEL, "pugs", set())
    clock.advance(15 * 60 + 1)
    pings.claim(CHANNEL, "PUGS", set())  # Names are case-insensitive.


@pytest.mark.django_db
def test_which_ping(league: Community) -> None:
    with pytest.raises(InvalidAction, match="no pings"):
        pings.claim(CHANNEL, None, set())
    _add(league, "pugs")
    _add(league, "ranked")
    with pytest.raises(InvalidAction, match="Pick which"):
        pings.claim(CHANNEL, None, set())
    with pytest.raises(InvalidAction, match="No ping called"):
        pings.claim(CHANNEL, "casual", set())
    assert pings.claim(CHANNEL, "ranked", set()).ping.name == "ranked"


@pytest.mark.django_db
def test_required_role(league: Community) -> None:
    _add(league, required_role=42)
    with pytest.raises(NotAllowed):
        pings.claim(CHANNEL, None, {1, 2})
    pings.claim(CHANNEL, None, {42})


@pytest.mark.django_db
def test_a_failed_send_gives_the_cooldown_back(league: Community, clock: Clock) -> None:
    _add(league)
    claim = pings.claim(CHANNEL, None, set())
    pings.release(claim)
    assert ChannelPing.objects.get().last_ping_at is None
    pings.claim(CHANNEL, None, set())


@pytest.mark.django_db
def test_release_never_undoes_someone_elses_ping(league: Community, clock: Clock) -> None:
    _add(league, timer=1)
    stale = pings.claim(CHANNEL, None, set())
    clock.advance(61)
    newer = pings.claim(CHANNEL, None, set())
    pings.release(stale)  # Too late: a newer ping went out since.
    assert ChannelPing.objects.get().last_ping_at == newer.claimed_at


@pytest.mark.django_db
def test_replacing_a_ping_resets_it(league: Community) -> None:
    _add(league)
    pings.claim(CHANNEL, None, set())
    _add(league, timer=30)
    row = ChannelPing.objects.get()
    assert row.timer_minutes == 30 and row.last_ping_at is None
    assert pings.remove(league.pk, CHANNEL, " Pugs ")
    assert not pings.remove(league.pk, CHANNEL, "pugs")


@pytest.mark.django_db
def test_a_cooldown_outside_its_range_is_refused(league: Community) -> None:
    with pytest.raises(InvalidAction):
        _add(league, timer=0)


# --- /ping ------------------------------------------------------------------------------------


def _ping_interaction() -> MagicMock:
    interaction = fake_interaction(make_player(1))
    interaction.channel_id = CHANNEL
    interaction.response.send_message = AsyncMock()
    return interaction


@pytest.mark.django_db(transaction=True)
def test_ping_only_mentions_what_staff_set_up(wired: Community) -> None:  # noqa: F811
    _add(wired)
    interaction = _ping_interaction()
    asyncio.run(
        ping_commands.ping_command.callback(  # type: ignore[call-arg]
            interaction, message="come play @everyone <@&999> <@123>", name=None
        )
    )
    call = interaction.response.send_message.call_args
    assert call.args[0].startswith(f"<@&{ROLE}> come play")
    allowed: discord.AllowedMentions = call.kwargs["allowed_mentions"]
    assert allowed.everyone is False
    assert [role.id for role in allowed.roles] == [ROLE]  # type: ignore[union-attr]
    assert list(allowed.users) == []  # type: ignore[arg-type]


@pytest.mark.django_db(transaction=True)
def test_a_ping_discord_refuses_keeps_its_cooldown_free(wired: Community) -> None:  # noqa: F811
    _add(wired)
    interaction = _ping_interaction()

    class Response:
        status = 400
        reason = "Bad Request"

    # The ping is refused; the reply saying so goes through.
    interaction.response.send_message = AsyncMock(
        side_effect=[discord.HTTPException(Response(), "nope"), None]  # type: ignore[arg-type]
    )
    interaction.response.is_done = MagicMock(return_value=False)
    asyncio.run(
        ping_commands.ping_command.callback(  # type: ignore[call-arg]
            interaction, message="hello", name=None
        )
    )
    assert ChannelPing.objects.get().last_ping_at is None
    told = interaction.response.send_message.call_args_list[-1]
    assert "cooldown wasn't used" in told.args[0] and told.kwargs["ephemeral"] is True


@pytest.mark.django_db(transaction=True)
def test_autocomplete_lists_this_channels_pings(wired: Community) -> None:  # noqa: F811
    _add(wired, "pugs")
    _add(wired, "ranked")
    _add(wired, "other", channel=CHANNEL + 1)
    interaction = _ping_interaction()
    choices = asyncio.run(ping_commands._ping_names(interaction, "r"))
    assert [choice.value for choice in choices] == ["ranked"]
