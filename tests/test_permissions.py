"""Staff areas: grants by role, who holds what, and each kind of command refusing the wrong role."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from discord import app_commands
from django.db import connections

from bot.commands import drafts as draft_commands
from bot.commands import permissions as permission_commands
from bot.commands import prio as prio_commands
from bot.commands import setup as setup_commands
from bot.commands import staff
from bot.db import db
from bot.handlers.permissions import member_areas
from league.models import Community, CommunityRoleGrant, QueueEntry
from league.models.permissions import Area
from league.services import community, permissions, queue
from tests.conftest import make_player, publish_presets
from tests.helpers import finish
from tests.test_handlers import (
    GUILD_ID,
    fake_interaction,
    in_progress,
    replies,
    run_command,
    subcommand,
)

pytestmark = pytest.mark.django_db(transaction=True)

DISPUTES_ROLE, MATCH_ROLE, SCRIMS_ROLE, SETUP_ROLE = 501, 502, 503, 504


def _role(role_id: int, *, default: bool = False) -> MagicMock:
    role = MagicMock(spec=discord.Role)
    role.id = role_id
    role.mention = f"<@&{role_id}>"
    role.is_default.return_value = default
    role.guild.id = GUILD_ID
    return role


def _staffer(number: int, *role_ids: int) -> MagicMock:
    return fake_interaction(make_player(number), role_ids=role_ids)


def _areas(interaction: MagicMock, community: Community) -> frozenset[Area]:
    return asyncio.run(member_areas(interaction, community))


def _refused(interaction: MagicMock) -> bool:
    return any(
        "permission" in text or "Only the server owner" in text for text in replies(interaction)
    )


@pytest.fixture
def server(transactional_db: None) -> Iterator[Community]:
    publish_presets()
    row = community.ensure(guild_id=GUILD_ID, name="Test")
    yield row
    asyncio.run(db(connections.close_all))


@pytest.fixture
def staffed(server: Community) -> Community:
    permissions.grant(server.pk, DISPUTES_ROLE, [Area.DISPUTES], granted_by=None)
    permissions.grant(server.pk, MATCH_ROLE, [Area.MATCH_CONTROL], granted_by=None)
    permissions.grant(server.pk, SCRIMS_ROLE, [Area.SCRIMS], granted_by=None)
    permissions.grant(server.pk, SETUP_ROLE, [Area.SETUP], granted_by=None)
    return server


# --- Grants --------------------------------------------------------------------------------


def test_grant_and_revoke_report_only_what_changed(server: Community) -> None:
    assert permissions.grant(server.pk, 9, [Area.DISPUTES, Area.RATINGS], 1) == [
        Area.DISPUTES,
        Area.RATINGS,
    ]
    assert permissions.grant(server.pk, 9, list(Area), 1) == [
        area for area in Area if area not in (Area.DISPUTES, Area.RATINGS)
    ]
    assert permissions.grant(server.pk, 9, [Area.DISPUTES], 1) == []
    assert permissions.revoke(server.pk, 9, [Area.SCRIMS, Area.SCRIMS]) == [Area.SCRIMS]
    assert permissions.revoke(server.pk, 9, [Area.SCRIMS]) == []
    assert permissions.areas_for_roles(server.pk, [9]) == permissions.ALL_AREAS - {Area.SCRIMS}


def test_roles_are_looked_up_per_server(server: Community) -> None:
    other = Community.objects.create(
        discord_guild_id=1234, name="Other", active_mode=server.active_mode
    )
    permissions.grant(other.pk, 9, [Area.SETUP], None)
    assert permissions.areas_for_roles(server.pk, [9]) == frozenset()
    assert permissions.role_ids_with(server.pk, [Area.SETUP]) == []
    assert permissions.role_ids_with(other.pk, [Area.SETUP]) == [9]


def test_grants_by_area_lists_every_area(staffed: Community) -> None:
    found = permissions.grants_by_area(staffed.pk)
    assert set(found) == set(Area)
    assert found[Area.DISPUTES] == [DISPUTES_ROLE]
    assert found[Area.RATINGS] == []


# --- Who holds what ------------------------------------------------------------------------


def test_owner_and_administrators_hold_every_area(server: Community) -> None:
    assert _areas(fake_interaction(make_player(1), administrator=True), server) == set(Area)
    owner = fake_interaction(make_player(2))
    owner.guild.owner_id = owner.user.id
    assert _areas(owner, server) == set(Area)


def test_members_hold_the_areas_their_roles_are_granted(staffed: Community) -> None:
    assert _areas(_staffer(1, DISPUTES_ROLE, SCRIMS_ROLE, 999_999), staffed) == {
        Area.DISPUTES,
        Area.SCRIMS,
    }
    assert _areas(_staffer(2, 999_999), staffed) == frozenset()
    outside = fake_interaction(make_player(3))
    outside.user = MagicMock(spec=discord.User)  # Not a member: outside a server.
    assert _areas(outside, staffed) == frozenset()


# --- /permissions ---------------------------------------------------------------------------


def _grant(interaction: MagicMock, role: MagicMock, value: str) -> None:
    run_command(
        subcommand(permission_commands.permissions_group, "grant"),
        interaction,
        role=role,
        area=app_commands.Choice(name=value, value=value),
    )


def test_only_the_owner_and_administrators_change_grants(staffed: Community) -> None:
    every_area = _staffer(1, *(DISPUTES_ROLE, MATCH_ROLE, SCRIMS_ROLE, SETUP_ROLE))
    _grant(every_area, _role(77), "disputes")
    assert _refused(every_area)
    assert not CommunityRoleGrant.objects.filter(role_id=77).exists()

    admin = fake_interaction(make_player(2), administrator=True)
    _grant(admin, _role(77), "disputes")
    assert replies(admin) == ["<@&77> can now use Disputes."]
    admin = fake_interaction(make_player(2), administrator=True)
    _grant(admin, _role(77), "all")
    assert permissions.areas_for_roles(staffed.pk, [77]) == set(Area)
    assert "already" not in replies(admin)[0]


def test_everyone_cannot_be_granted_an_area(server: Community) -> None:
    admin = fake_interaction(make_player(1), administrator=True)
    _grant(admin, _role(GUILD_ID, default=True), "setup")
    assert "other than @everyone" in replies(admin)[0]
    assert not CommunityRoleGrant.objects.exists()


def test_revoke_and_list(staffed: Community) -> None:
    admin = fake_interaction(make_player(1), administrator=True)
    run_command(
        subcommand(permission_commands.permissions_group, "revoke"),
        admin,
        role=_role(DISPUTES_ROLE),
        area=app_commands.Choice(name="Every area", value="all"),
    )
    assert replies(admin) == [f"<@&{DISPUTES_ROLE}> can no longer use Disputes."]
    admin = fake_interaction(make_player(1), administrator=True)
    run_command(subcommand(permission_commands.permissions_group, "list"), admin)
    text = replies(admin)[0]
    assert f"**Scrims** ({'/startdraft'}" in text and f"<@&{SCRIMS_ROLE}>" in text
    assert "**Disputes** (" in text and "nobody yet" in text


def test_staff_channel_access_follows_the_grants() -> None:
    stale, kept, wanted = _role(1), _role(2), _role(3)
    everyone = _role(GUILD_ID, default=True)
    channel = MagicMock(spec=discord.TextChannel)
    channel.overwrites = {
        stale: setup_commands.ARCHIVE_STAFF,
        kept: setup_commands.ARCHIVE_STAFF,
        everyone: discord.PermissionOverwrite(view_channel=False),
    }
    channel.overwrites_for = lambda role: channel.overwrites.get(
        role, discord.PermissionOverwrite()
    )
    channel.set_permissions = AsyncMock()
    guild = MagicMock()
    guild.get_channel.return_value = channel
    guild.get_role = {2: kept, 3: wanted}.get  # Role 4 was deleted from the server.
    asyncio.run(setup_commands._sync_roles(guild, 70, [2, 3, 4], setup_commands.ARCHIVE_STAFF))
    calls = [
        (call.args[0], call.kwargs["overwrite"]) for call in channel.set_permissions.call_args_list
    ]
    assert calls == [(stale, None), (wanted, setup_commands.ARCHIVE_STAFF)]


# --- Each command checks its own area -------------------------------------------------------


def test_live_matches_are_match_control_and_finished_ones_disputes(staffed: Community) -> None:
    match = in_progress(staffed)
    void = subcommand(staff.match_group, "void")
    disputes = _staffer(60, DISPUTES_ROLE)
    run_command(void, disputes, match_id=match.pk, reason="test")
    assert "It needs Match control access" in replies(disputes)[0]
    control = _staffer(61, MATCH_ROLE)
    run_command(void, control, match_id=match.pk, reason="test")
    assert replies(control)[0].startswith("Cancel live match")

    finish(match)
    control = _staffer(61, MATCH_ROLE)
    run_command(void, control, match_id=match.pk, reason="test")
    assert "It needs Disputes access" in replies(control)[0]
    disputes = _staffer(60, DISPUTES_ROLE)
    run_command(void, disputes, match_id=match.pk, reason="test")
    assert replies(disputes)[0].startswith("Void finished match")


def test_queue_admin_is_match_control(staffed: Community) -> None:
    queue.join(staffed.pk, make_player(1))
    clear = subcommand(staff.queue_admin_group, "clear")
    scrims = _staffer(60, SCRIMS_ROLE)
    run_command(clear, scrims)
    assert _refused(scrims)
    run_command(clear, _staffer(61, MATCH_ROLE))
    assert not QueueEntry.objects.exists()


def test_scrims_need_the_scrims_area(staffed: Community) -> None:
    def start(interaction: MagicMock) -> MagicMock:
        interaction.channel_id = 6001
        interaction.app_permissions = discord.Permissions(
            view_channel=True, send_messages=True, read_message_history=True
        )
        run_command(draft_commands.startdraft_command, interaction)
        return interaction

    assert _refused(start(_staffer(60, DISPUTES_ROLE)))
    assert replies(start(_staffer(61, SCRIMS_ROLE))) == [
        "Posting the draft. Captains: claim a side."
    ]
    stop = _staffer(62, DISPUTES_ROLE)
    stop.channel_id = 6001
    run_command(draft_commands.stopdraft_command, stop)
    assert _refused(stop)


def test_community_commands_need_the_community_area(staffed: Community) -> None:
    interaction = _staffer(60, SCRIMS_ROLE)
    user = MagicMock()
    user.id, user.display_name = 999, "Someone"
    run_command(prio_commands.removeprio_command, interaction, user=user)
    assert "It needs Community access" in replies(interaction)[0]


def _setup(interaction: MagicMock, guild_id: int) -> MagicMock:
    interaction.guild.id = guild_id
    interaction.guild.name = "Test"
    interaction.guild_id = guild_id
    run_command(setup_commands.setup_command, interaction)
    return interaction


def test_setup_needs_a_manager_first_then_the_setup_area(staffed: Community) -> None:
    assert _refused(_setup(_staffer(60, SETUP_ROLE), 4242))  # A server with no grants yet.
    assert not Community.objects.filter(discord_guild_id=4242).exists()
    assert _refused(_setup(_staffer(61, SCRIMS_ROLE), GUILD_ID))
    # Already set up, so /setup has nothing to create.
    community.save_wiring(
        staffed.pk,
        waiting_room_channel_id=1,
        queue_channel_id=2,
        results_channel_id=3,
        archive_channel_id=4,
        staff_channel_id=5,
    )
    assert replies(_setup(_staffer(62, SETUP_ROLE), GUILD_ID))[0].startswith("Setup done.")


def test_open_commands_stay_open(staffed: Community) -> None:
    interaction = fake_interaction(make_player(1))
    run_command(subcommand(staff.match_group, "status"), interaction, match_id=1)
    assert _refused(interaction)
    interaction = fake_interaction(make_player(1))
    run_command(prio_commands.prio_command, interaction)
    assert not _refused(interaction)
