"""A real discord.py 2.7.1 client against the sim: the paths draft-bot depends on."""

from __future__ import annotations

import asyncio
import io
from collections.abc import Callable
from typing import Any

import discord
import pytest

from discord_sim import snowflake
from discord_sim.interactions import PLACEHOLDER_PNG

from .support import Connected, Recorder, RunningSim, SimClient, connect

pytestmark = pytest.mark.asyncio


class ActionButton(discord.ui.Button[Any]):
    """Records the interaction and answers it the way the test asks."""

    def __init__(self, label: str, custom_id: str, answer: str, seen: list[discord.Interaction]):
        super().__init__(label=label, custom_id=custom_id, style=discord.ButtonStyle.success)
        self.answer = answer
        self.seen = seen

    async def callback(self, interaction: discord.Interaction) -> None:
        self.seen.append(interaction)
        if self.answer == "reply":
            await interaction.response.send_message("You are ready", ephemeral=True)
        elif self.answer == "defer":
            await interaction.response.defer(ephemeral=True, thinking=True)
            await interaction.followup.send("Done thinking", ephemeral=True)
        elif self.answer == "update":
            await interaction.response.defer()
            await interaction.edit_original_response(view=Board(self.seen, disabled=True))
        elif self.answer == "refuse":
            await interaction.response.defer()
            await interaction.followup.send("It isn't your turn.", ephemeral=True)
        elif self.answer == "modal":
            await interaction.response.send_modal(CodeModal(self.seen))


class Board(discord.ui.LayoutView):
    def __init__(self, seen: list[discord.Interaction], *, disabled: bool = False) -> None:
        super().__init__(timeout=None)
        buttons = [
            ActionButton("✅ Ready", "test:ready", "reply", seen),
            ActionButton("Think", "test:think", "defer", seen),
            ActionButton("Lock", "test:lock", "update", seen),
            ActionButton("Enter code", "test:code", "modal", seen),
            ActionButton("Pick", "test:pick", "refuse", seen),
        ]
        for button in buttons:
            button.disabled = disabled
        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay("## Ready check"), discord.ui.ActionRow(*buttons)
            )
        )


class CodeModal(discord.ui.Modal, title="Lobby code"):
    code: discord.ui.TextInput[Any] = discord.ui.TextInput(label="Code", custom_id="lobby_code")

    def __init__(self, seen: list[discord.Interaction]) -> None:
        super().__init__()
        self.seen = seen

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.seen.append(interaction)
        await interaction.response.send_message(f"Code {self.code.value}", ephemeral=True)


async def eventually(check: Callable[[], bool], timeout: float = 5.0) -> None:
    async with asyncio.timeout(timeout):
        while not check():
            await asyncio.sleep(0.02)


async def new_user(running: RunningSim, **body: Any) -> dict[str, Any]:
    created = await running.call("POST", "/_sim/users", {"count": 1, **body}, status=201)
    user: dict[str, Any] = created["users"][0]
    return user


async def test_connect_ready_and_guild_create(connected: Connected) -> None:
    client = connected.client
    assert client.user is not None and client.user.id == snowflake.BOT_USER_ID
    assert client.application_id == snowflake.BOT_USER_ID
    guild = connected.guild
    assert guild.owner_id == snowflake.OWNER_USER_ID
    assert guild.me is not None and guild.me.guild_permissions.administrator
    assert {c.name for c in guild.channels} >= {"general", "General", "Text Channels"}
    assert guild.get_role(snowflake.STAFF_ROLE_ID) is not None
    assert guild.default_role.id == snowflake.GUILD_ID


async def test_layout_view_click_and_callback(connected: Connected) -> None:
    running = connected.sim
    player = await new_user(running)
    seen: list[discord.Interaction] = []
    message = await connected.text_channel().send(view=Board(seen))
    stored = running.sim.state.find_message(message.id)
    assert stored.flags & discord.MessageFlags.components_v2.flag

    result = await running.call(
        "POST",
        "/_sim/interactions/click",
        {"user_id": player["id"], "channel_id": "general", "label": "ready"},
    )

    assert result["response"]["type"] == 4
    assert result["message"]["content"] == "You are ready"
    assert result["message"]["ephemeral"] is True
    assert seen[0].message is not None and seen[0].message.id == message.id
    assert seen[0].user.id == int(player["id"])


async def test_deferred_reply_settles_on_the_followup(connected: Connected) -> None:
    running = connected.sim
    player = await new_user(running)
    seen: list[discord.Interaction] = []
    await connected.text_channel().send(view=Board(seen))

    result = await running.call(
        "POST",
        "/_sim/interactions/click",
        {"user_id": player["id"], "channel_id": "general", "label": "Think"},
    )

    assert result["response"]["type"] == 5
    assert result["settled"] is True
    assert result["message"]["content"] == "Done thinking"
    assert result["message"]["loading"] is False


async def test_edit_original_after_defer_updates_the_board(connected: Connected) -> None:
    running = connected.sim
    player = await new_user(running)
    seen: list[discord.Interaction] = []
    message = await connected.text_channel().send(view=Board(seen))

    result = await running.call(
        "POST",
        "/_sim/interactions/click",
        {"user_id": player["id"], "channel_id": "general", "label": "Lock"},
    )

    assert result["response"]["type"] == 6  # Settles at once; the edit follows.
    stored = running.sim.state.find_message(message.id)
    await eventually(lambda: stored.edited_at is not None)
    missing = await running.call(
        "POST",
        "/_sim/interactions/click",
        {"user_id": player["id"], "channel_id": "general", "label": "Ready"},
        status=404,
    )
    assert missing["available"] == []  # Every button is disabled now.


async def test_followup_wait_reports_a_refusal(connected: Connected) -> None:
    running = connected.sim
    player = await new_user(running)
    await connected.text_channel().send(view=Board([]))

    result = await running.call(
        "POST",
        "/_sim/interactions/click",
        {"user_id": player["id"], "channel_id": "general", "label": "Pick", "followup_wait": 2},
    )

    assert result["response"]["type"] == 6
    assert [f["content"] for f in result["followups"]] == ["It isn't your turn."]
    assert result["followups"][0]["ephemeral_for"] == player["id"]


async def test_modal_round_trip(connected: Connected) -> None:
    running = connected.sim
    player = await new_user(running)
    seen: list[discord.Interaction] = []
    await connected.text_channel().send(view=Board(seen))

    opened = await running.call(
        "POST",
        "/_sim/interactions/click",
        {"user_id": player["id"], "channel_id": "general", "label": "Enter code"},
    )
    assert opened["response"]["type"] == 9
    assert opened["modal"]["title"] == "Lobby code"

    result = await running.call(
        "POST", "/_sim/interactions/modal", {"user_id": player["id"], "values": {"Code": "XYZ12"}}
    )

    assert result["message"]["content"] == "Code XYZ12"


class ScreenshotModal(discord.ui.Modal):
    """Shaped like the bot's report modal: Labels around a file upload, an optional text input
    and an optional select, read after a deferred, thinking response."""

    def __init__(self, seen: list[Any]) -> None:
        super().__init__(title="Ash won")
        self.seen = seen
        self.screenshot: discord.ui.FileUpload[Any] = discord.ui.FileUpload(
            required=True, min_values=1, max_values=1
        )
        self.match_id: discord.ui.TextInput[Any] = discord.ui.TextInput(
            required=False, max_length=18
        )
        self.mvp: discord.ui.Select[Any] = discord.ui.Select(
            options=[discord.SelectOption(label="Ash", value="1")],
            min_values=0,
            max_values=1,
            required=False,
        )
        self.add_item(discord.ui.Label(text="Scoreboard screenshot", component=self.screenshot))
        self.add_item(discord.ui.Label(text="Deadlock match ID", component=self.match_id))
        self.add_item(discord.ui.Label(text="MVP", component=self.mvp))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        upload = self.screenshot.values[0]
        self.seen.append((await upload.read(), upload.size, self.match_id.value, self.mvp.values))
        await interaction.followup.send("Thanks: result received.", ephemeral=True)


class ReportButton(discord.ui.Button[Any]):
    def __init__(self, seen: list[Any]) -> None:
        super().__init__(label="Ash won", custom_id="test:report")
        self.seen = seen

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(ScreenshotModal(self.seen))


async def test_modal_with_a_file_upload(connected: Connected) -> None:
    running = connected.sim
    player = await new_user(running)
    seen: list[Any] = []
    view = discord.ui.LayoutView(timeout=None)
    view.add_item(discord.ui.Container(discord.ui.ActionRow(ReportButton(seen))))
    await connected.text_channel().send(view=view)
    opened = await running.call(
        "POST",
        "/_sim/interactions/click",
        {"user_id": player["id"], "channel_id": "general", "label": "Ash won"},
    )
    upload = next(
        row["component"]["custom_id"]
        for row in opened["modal"]["components"]
        if row["component"]["type"] == 19
    )

    result = await running.call(
        "POST",
        "/_sim/interactions/modal",
        {"user_id": player["id"], "attachments": {upload: [{"filename": "scoreboard.png"}]}},
    )

    assert seen == [(PLACEHOLDER_PNG, len(PLACEHOLDER_PNG), "", [])]
    assert result["response"]["type"] == 5
    assert result["message"]["content"] == "Thanks: result received."
    later = await running.call("GET", f"/_sim/interactions/{result['interaction_id']}")
    assert later["settled"] and later["message"]["id"] == result["message"]["id"]


async def test_slash_command_with_options(connected: Connected) -> None:
    running = connected.sim
    client = connected.client
    guild = discord.Object(id=snowflake.GUILD_ID)
    calls: list[tuple[int, str]] = []

    @client.tree.command(name="echo", description="Say it back", guild=guild)
    async def echo(interaction: discord.Interaction, times: int, word: str) -> None:
        calls.append((times, word))
        await interaction.response.defer(ephemeral=True, thinking=True)
        await interaction.followup.send(" ".join([word] * times), ephemeral=True)

    await client.tree.sync(guild=guild)
    owner = str(snowflake.OWNER_USER_ID)
    result = await running.call(
        "POST",
        "/_sim/interactions/command",
        {"user_id": owner, "name": "echo", "options": {"times": 2, "word": "hi"}},
    )

    assert calls == [(2, "hi")]
    assert result["message"]["content"] == "hi hi"
    assert result["message"]["interaction"]["name"] == "echo"


async def test_dm_to_closed_user_is_50007(connected: Connected) -> None:
    running = connected.sim
    closed = await new_user(running, dm_open=False)
    open_ = await new_user(running)

    user = await connected.client.fetch_user(int(closed["id"]))
    dm = await user.create_dm()
    with pytest.raises(discord.Forbidden) as caught:
        await dm.send("Your match is ready")
    assert caught.value.code == 50007

    other = await (await connected.client.fetch_user(int(open_["id"]))).create_dm()
    await other.send("Your match is ready")
    dms = await running.call("GET", f"/_sim/users/{open_['id']}/dms")
    assert [m["content"] for m in dms["messages"]] == ["Your match is ready"]


async def test_voice_moves_and_40032(connected: Connected) -> None:
    running = connected.sim
    client = connected.client
    player = await new_user(running)
    player_id = int(player["id"])
    waiting = await connected.guild.create_voice_channel("Waiting Room")

    with pytest.raises(discord.HTTPException) as caught:
        await client.http.edit_member(snowflake.GUILD_ID, player_id, channel_id=waiting.id)
    assert caught.value.status == 400 and caught.value.code == 40032

    await running.call(
        "POST", "/_sim/voice", {"user_id": player_id, "channel_id": snowflake.GENERAL_VOICE_ID}
    )
    await connected.recorder.wait_for("voice")
    general = connected.guild.get_channel(snowflake.GENERAL_VOICE_ID)
    assert isinstance(general, discord.VoiceChannel)
    assert player_id in general.voice_states

    await client.http.edit_member(snowflake.GUILD_ID, player_id, channel_id=waiting.id)
    moves = await connected.recorder.wait_for("voice", count=2)
    assert moves[-1] == (player_id, waiting.id)
    assert player_id in waiting.voice_states


async def test_channel_create_reaches_the_cache(connected: Connected) -> None:
    guild = connected.guild
    category = await guild.create_category("Match 7")
    text = await guild.create_text_channel(
        "Match 7 Lobby",
        category=category,
        overwrites={guild.default_role: discord.PermissionOverwrite(view_channel=False)},
    )

    cached = guild.get_channel(text.id)
    assert isinstance(cached, discord.TextChannel)
    assert cached.name == "match-7-lobby"
    assert cached.category is not None and cached.category.id == category.id
    assert cached.overwrites_for(guild.default_role).view_channel is False

    invite = await (await guild.create_voice_channel("Team A", category=category)).create_invite(
        max_age=3600
    )
    assert invite.url.startswith("https://discord.gg/")

    await text.delete()
    assert guild.get_channel(text.id) is None


async def test_file_upload_and_attachment_url(connected: Connected) -> None:
    running = connected.sim
    view = discord.ui.LayoutView()
    view.add_item(discord.ui.MediaGallery(discord.MediaGalleryItem("attachment://board.png")))
    file = discord.File(io.BytesIO(PLACEHOLDER_PNG), filename="board.png")

    message = await connected.text_channel().send(view=view, file=file)

    attachment = message.attachments[0]
    assert attachment.url.startswith(running.url + "/attachments/")
    assert attachment.content_type == "image/png" and attachment.width == 1
    assert await attachment.read() == PLACEHOLDER_PNG
    fetched = await connected.text_channel().fetch_message(message.id)
    gallery = fetched.components[0]
    assert isinstance(gallery, discord.MediaGalleryComponent)
    assert gallery.items[0].media.url == attachment.url


async def test_chat_reaches_on_message_without_content(connected: Connected) -> None:
    running = connected.sim
    player = await new_user(running)
    await running.call(
        "POST",
        "/_sim/messages",
        {"user_id": player["id"], "channel_id": "general", "content": "gg"},
        status=201,
    )
    seen = await connected.recorder.wait_for("message")
    assert seen[0].author.id == int(player["id"])
    assert seen[0].content == ""  # No Message Content intent, as for the real bot.
    history = [m async for m in connected.text_channel().history(limit=1)]
    assert history[0].id == seen[0].id


async def test_reset_reconnects_with_a_fresh_ready(running: RunningSim, point_at: Any) -> None:
    point_at(running.url)
    client = SimClient(Recorder())
    task = await connect(client)
    try:
        await client.get_guild(snowflake.GUILD_ID).create_text_channel("scratch")  # type: ignore[union-attr]
        await running.call("POST", "/_sim/reset")
        await client.recorder.wait_for("ready", count=2, timeout=10)
        guild = client.get_guild(snowflake.GUILD_ID)
        assert guild is not None
        assert "scratch" not in {c.name for c in guild.channels}
    finally:
        await client.close()
        await task
