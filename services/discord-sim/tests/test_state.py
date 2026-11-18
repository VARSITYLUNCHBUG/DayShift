"""The in-memory world: seed, users, channels, permissions, voice and messages."""

from __future__ import annotations

import pytest

from discord_sim import permissions, snowflake
from discord_sim.components import EPHEMERAL, IS_COMPONENTS_V2
from discord_sim.config import Config
from discord_sim.errors import DiscordError
from discord_sim.message_body import MessageBody, UploadedFile
from discord_sim.state import GUILD_CATEGORY, GUILD_TEXT, GUILD_VOICE, SimState

BUTTON_ROW = [
    {"type": 1, "components": [{"type": 2, "style": 1, "label": "Go", "custom_id": "go"}]}
]


@pytest.fixture
def state() -> SimState:
    return SimState(Config(seed_users=2))


def code_of(caught: pytest.ExceptionInfo[DiscordError]) -> int:
    return caught.value.code


def test_seed_has_fixed_ids(state: SimState) -> None:
    assert state.guild.id == snowflake.GUILD_ID
    assert state.guild.owner_id == snowflake.OWNER_USER_ID
    assert state.bot_user.id == snowflake.BOT_USER_ID == state.application_id
    assert state.guild.roles[snowflake.GUILD_ID].name == "@everyone"
    assert {snowflake.SEED_USER_BASE, snowflake.SEED_USER_BASE + 1} <= set(state.users)
    assert state.guild.channels[snowflake.GENERAL_VOICE_ID].type == GUILD_VOICE


def test_reset_restores_the_seed_but_ids_keep_counting(state: SimState) -> None:
    first = state.add_user()
    state.put_commands(snowflake.GUILD_ID, [{"name": "setup"}])
    state.reset()
    assert first.id not in state.users
    assert state.add_user().id > first.id
    assert state.find_command("setup").guild_id == snowflake.GUILD_ID  # The bot syncs only once.


def test_ids_carry_their_time_and_never_repeat_after_a_restart() -> None:
    at = 1_790_000_000.0
    before_restart = snowflake.SnowflakeGenerator(clock=lambda: at)
    first, second = before_restart.next(), before_restart.next()
    assert second == first + 1 > snowflake.RUNTIME_BASE
    assert (first >> 22) + snowflake.DISCORD_EPOCH_MS == int(at * 1000)
    assert snowflake.SnowflakeGenerator(clock=lambda: at + 1).next() > second


def test_new_users_get_numbered_names(state: SimState) -> None:
    a = state.add_user()
    b = state.add_user(name_prefix="sub")
    assert (a.display_name, b.display_name) == ("player3", "sub4")
    assert state.find_user("player3") is a
    assert state.find_user(str(b.id)) is b


def test_text_channel_names_are_normalised_and_sync_with_the_category(state: SimState) -> None:
    hidden = {"id": str(state.guild.id), "type": 0, "allow": "0", "deny": str(1 << 10)}
    category = state.create_channel(
        {"name": "Match 3", "type": GUILD_CATEGORY, "permission_overwrites": [hidden]}
    )
    text = state.create_channel(
        {"name": "Match 3  Lobby", "type": GUILD_TEXT, "parent_id": category.id}
    )
    assert text.name == "match-3-lobby"
    assert [o.deny for o in text.overwrites] == [1 << 10]


def test_channel_under_a_non_category_is_rejected(state: SimState) -> None:
    with pytest.raises(DiscordError) as caught:
        state.create_channel({"name": "x", "type": 0, "parent_id": snowflake.GENERAL_TEXT_ID})
    assert code_of(caught) == 50035


def test_overwrites_hide_a_channel_until_granted(state: SimState) -> None:
    player = state.add_user()
    channel = state.create_channel(
        {
            "name": "match",
            "permission_overwrites": [
                {"id": state.guild.id, "type": 0, "allow": 0, "deny": permissions.VIEW_CHANNEL}
            ],
        }
    )
    assert not state.can_view(player.id, channel)
    assert state.can_view(state.guild.owner_id, channel)
    assert state.can_view(state.bot_user.id, channel)  # The bot's role is administrator.
    state.set_overwrite(channel.id, player.id, {"type": 1, "allow": permissions.VIEW_CHANNEL})
    assert state.can_view(player.id, channel)


def test_moving_someone_not_in_voice_is_40032(state: SimState) -> None:
    player = state.add_user()
    with pytest.raises(DiscordError) as caught:
        state.move_member(player.id, snowflake.GENERAL_VOICE_ID)
    assert code_of(caught) == 40032
    state.set_voice(player.id, snowflake.GENERAL_VOICE_ID)
    change = state.move_member(player.id, None)
    assert change.before == snowflake.GENERAL_VOICE_ID and change.state is None


def test_deleting_a_voice_channel_drops_its_members(state: SimState) -> None:
    player = state.add_user()
    room = state.create_channel({"name": "Team A", "type": GUILD_VOICE})
    state.set_voice(player.id, room.id)
    deleted = state.delete_channel(room.id)
    assert [c.user_id for c in deleted.left_voice] == [player.id]
    assert player.id not in state.guild.voice_states


def test_dm_to_a_closed_user_is_50007(state: SimState) -> None:
    player = state.add_user(dm_open=False)
    dm = state.open_dm(player.id)
    assert state.open_dm(player.id) is dm
    with pytest.raises(DiscordError) as caught:
        state.post_message(dm.id, state.bot_user.id, MessageBody.parse({"content": "hi"}))
    assert code_of(caught) == 50007


def test_v2_messages_cannot_carry_content(state: SimState) -> None:
    body = MessageBody.parse({"content": "hi", "flags": IS_COMPONENTS_V2, "components": []})
    with pytest.raises(DiscordError) as caught:
        state.post_message(snowflake.GENERAL_TEXT_ID, state.bot_user.id, body)
    assert caught.value.errors is not None and "content" in caught.value.errors


def test_empty_message_is_50006(state: SimState) -> None:
    with pytest.raises(DiscordError) as caught:
        state.post_message(snowflake.GENERAL_TEXT_ID, state.bot_user.id, MessageBody.parse({}))
    assert code_of(caught) == 50006


def test_edits_keep_v2_and_ephemeral(state: SimState) -> None:
    body = MessageBody.parse({"components": BUTTON_ROW, "flags": IS_COMPONENTS_V2})
    message = state.post_message(
        snowflake.GENERAL_TEXT_ID, state.bot_user.id, body, ephemeral_for=snowflake.OWNER_USER_ID
    )
    state.edit_message(message, MessageBody.parse({"flags": 0, "components": BUTTON_ROW}))
    assert message.flags & IS_COMPONENTS_V2 and message.flags & EPHEMERAL
    assert message.components[0]["id"] == 1  # Numbered like Discord does.


def test_mentions_follow_allowed_mentions(state: SimState) -> None:
    player = state.add_user()
    content = f"<@{player.id}> <@&{snowflake.STAFF_ROLE_ID}> @everyone"
    pinged = state.post_message(
        snowflake.GENERAL_TEXT_ID,
        state.bot_user.id,
        MessageBody.parse(
            {"content": content, "allowed_mentions": {"parse": [], "users": [str(player.id)]}}
        ),
    )
    assert pinged.mentions == [player.id]
    assert pinged.mention_roles == [] and not pinged.mention_everyone


def test_history_is_newest_first_and_hides_ephemeral(state: SimState) -> None:
    channel = snowflake.GENERAL_TEXT_ID
    bot = state.bot_user.id
    first = state.post_message(channel, bot, MessageBody.parse({"content": "1"}))
    state.post_message(channel, bot, MessageBody.parse({"content": "secret"}), ephemeral_for=5)
    third = state.post_message(channel, bot, MessageBody.parse({"content": "3"}))
    assert [m.id for m in state.history(channel, limit=10)] == [third.id, first.id]
    assert [m.id for m in state.history(channel, limit=1)] == [third.id]
    assert [m.id for m in state.history(channel, limit=10, before=third.id)] == [first.id]
    assert len(state.history(channel, limit=10, viewer_id=5)) == 3


def test_attachments_and_media_references(state: SimState) -> None:
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + (3).to_bytes(4, "big") + (2).to_bytes(4, "big")
    gallery = [{"type": 12, "items": [{"media": {"url": "attachment://shot.png"}}]}]
    body = MessageBody.parse(
        {"components": gallery, "flags": IS_COMPONENTS_V2, "attachments": [{"id": 0}]},
        [UploadedFile(0, "shot.png", "application/octet-stream", png)],
    )
    message = state.post_message(snowflake.GENERAL_TEXT_ID, state.bot_user.id, body)
    attachment = message.attachments[0]
    assert (attachment.content_type, attachment.width, attachment.height) == ("image/png", 3, 2)

    bad = MessageBody.parse(
        {
            "components": [{"type": 12, "items": [{"media": {"url": "attachment://nope.png"}}]}],
            "flags": IS_COMPONENTS_V2,
        }
    )
    with pytest.raises(DiscordError):
        state.post_message(snowflake.GENERAL_TEXT_ID, state.bot_user.id, bad)


def test_commands_keep_their_ids_across_syncs(state: SimState) -> None:
    first = state.put_commands(state.guild.id, [{"name": "setup", "description": "Set up"}])
    second = state.put_commands(
        state.guild.id, [{"name": "setup", "description": "Set up"}, {"name": "queue"}]
    )
    assert second[0].id == first[0].id
    assert state.find_command("queue").guild_id == state.guild.id
    with pytest.raises(DiscordError):
        state.find_command("missing")


def test_invites_are_reused_unless_unique(state: SimState) -> None:
    room = snowflake.GENERAL_VOICE_ID
    one = state.create_invite(room, state.bot_user.id, {"max_age": 60})
    assert state.create_invite(room, state.bot_user.id, {"max_age": 60}) is one
    assert state.create_invite(room, state.bot_user.id, {"max_age": 60, "unique": True}) is not one
