"""The Discord view: press a bot button as a fake user and submit the form it opens.

Team A's captain reports a win from the match channel, attaching a real screenshot (of this very
screen), and the bot must take the report with that image.
"""

from __future__ import annotations

import re

from playwright.sync_api import expect

from support.api import ControlApi, SimApi, wait_for
from support.boards import wait_board
from support.pages import ControlPanel


def test_report_a_win_with_a_screenshot(
    panel: ControlPanel, control: ControlApi, sim: SimApi
) -> None:
    match = control.lobby_match()
    match = control.advance(match["id"], "in_progress")["match"]
    captain = next(p["name"] for p in match["players"] if p["id"] == match["captains"]["A"])
    channel = sim.channel(match["text_channel_id"])["name"]
    wait_board(sim, control, match["id"])

    screen = panel.discord()
    screen.act_as(captain)
    log = screen.open_channel(channel)
    board = log.get_by_role("article").filter(has_text="Game on").last
    button = f"{captain}'s Team won"
    screenshot = panel.page.screenshot()
    board.get_by_role("button", name=button).click()
    panel.finish(f"Click {button}", re.compile(rf"^Click {re.escape(button)}: the bot opened"))

    screen.bot_modal(button).attach("Scoreboard screenshot", "scoreboard.png", screenshot).submit(
        captain
    )

    reported, shown = wait_board(sim, control, match["id"])
    assert reported["status"] == "awaiting_confirmation"
    assert f"**{captain}** reported **{captain}'s Team** won" in "\n".join(shown["text"])
    expect(log.get_by_role("article").filter(has_text="Confirm the result")).not_to_have_count(0)
    archive = control.state()["community"]["channels"]["archive"]

    def archived() -> bool:
        return any(
            a["size"] == len(screenshot) and sim.attachment(a["id"]) == screenshot
            for message in sim.messages(archive)
            for a in message["attachments"]
        )

    wait_for(archived, "the screenshot in #scoreboard-archive")
