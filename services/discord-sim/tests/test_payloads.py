"""Payload shapes: the fields discord.py 2.7.1 requires, typed the way Discord types them."""

from __future__ import annotations

import pytest

from discord_sim import payloads, snowflake
from discord_sim.components import IS_COMPONENTS_V2
from discord_sim.config import Config
from discord_sim.message_body import MessageBody, UploadedFile
from discord_sim.state import GUILD_VOICE, SimState

BASE = "http://sim:8090"


@pytest.fixture
def state() -> SimState:
    return SimState(Config())


def test_user_and_member_have_the_required_keys(state: SimState) -> None:
    member = payloads.member(state, state.guild.members[state.bot_user.id], perms=8)
    assert {"roles", "flags", "joined_at", "user"} <= member.keys()
    assert member["roles"] == [str(snowflake.BOT_ROLE_ID)]
    assert member["permissions"] == "8"
    assert {"id", "username", "discriminator", "avatar"} <= member["user"].keys()
    assert member["user"]["bot"] is True


def test_voice_channel_carries_bitrate_and_user_limit(state: SimState) -> None:
    data = payloads.channel(state, state.guild.channels[snowflake.GENERAL_VOICE_ID])
    assert data["type"] == GUILD_VOICE
    assert {"bitrate", "user_limit", "position", "guild_id", "permission_overwrites"} <= data.keys()


def test_dm_channel_lists_its_recipient(state: SimState) -> None:
    player = state.add_user()
    data = payloads.channel(state, state.open_dm(player.id))
    assert data["type"] == 1 and data["recipients"][0]["id"] == str(player.id)


def test_message_resolves_attachment_media(state: SimState) -> None:
    gallery = [{"type": 12, "items": [{"media": {"url": "attachment://b.png"}}]}]
    body = MessageBody.parse(
        {"components": gallery, "flags": IS_COMPONENTS_V2},
        [UploadedFile(0, "b.png", "image/png", b"png")],
    )
    message = state.post_message(snowflake.GENERAL_TEXT_ID, state.bot_user.id, body)
    data = payloads.message(state, message, BASE)
    attachment = data["attachments"][0]
    assert (
        attachment["url"]
        == f"{BASE}/attachments/{snowflake.GENERAL_TEXT_ID}/{attachment['id']}/b.png"
    )
    assert {"id", "size", "filename", "url", "proxy_url"} <= attachment.keys()
    media = data["components"][0]["items"][0]["media"]
    assert media["url"] == attachment["url"] and media["attachment_id"] == attachment["id"]
    assert (
        message.components[0]["items"][0]["media"]["url"] == "attachment://b.png"
    )  # Stored as sent.
    assert data["guild_id"] == str(snowflake.GUILD_ID)


def test_hidden_content_blanks_what_the_intent_gates(state: SimState) -> None:
    player = state.add_user()
    message = state.post_message(
        snowflake.GENERAL_TEXT_ID, player.id, MessageBody.parse({"content": "gg"})
    )
    data = payloads.message(state, message, BASE, hide_content=True)
    assert data["content"] == "" and data["author"]["id"] == str(player.id)


def test_guild_create_lists_members_by_intent(state: SimState) -> None:
    idle = state.add_user()
    talking = state.add_user()
    state.set_voice(talking.id, snowflake.GENERAL_VOICE_ID)
    without = payloads.guild_create(state, intents=1 | 1 << 7)
    listed = {m["user"]["id"] for m in without["members"]}
    assert listed == {str(state.bot_user.id), str(talking.id)}
    assert without["voice_states"][0]["user_id"] == str(talking.id)
    with_members = payloads.guild_create(state, intents=1 | 1 << 1)
    assert str(idle.id) in {m["user"]["id"] for m in with_members["members"]}
    assert with_members["voice_states"] == []


def test_voice_state_update_payload_has_member(state: SimState) -> None:
    player = state.add_user()
    change = state.set_voice(player.id, snowflake.GENERAL_VOICE_ID)
    data = payloads.voice_state(
        state, change.state, user_id=player.id, session_id=change.session_id, full=True
    )
    assert data["guild_id"] == str(snowflake.GUILD_ID)
    assert data["member"]["user"]["id"] == str(player.id)


def test_application_and_ready(state: SimState) -> None:
    app = payloads.application(state)
    assert {"id", "name", "description", "icon", "bot_public", "owner", "verify_key"} <= app.keys()
    assert app["interactions_endpoint_url"] is None
    ready = payloads.ready(state, "abc", "ws://sim/gateway")
    assert ready["session_id"] == "abc" and ready["resume_gateway_url"] == "ws://sim/gateway"
    assert ready["guilds"] == [{"id": str(snowflake.GUILD_ID), "unavailable": True}]
