"""Page objects for the control panel (services/control-panel/).

Tests say what a person does ("complete the phase", "save the script"); these know where the
controls are. Every action waits for its outcome in the page: the panel toasts the result of
each API call (`useAction`), so an action is done when its success toast shows, and fails with
the error toast's text when that shows instead. A success toast is closed once seen, so the
next identical one is a new one.
"""

from __future__ import annotations

import re
from typing import Self

from playwright.sync_api import Locator, Page, expect

# The labels the panel gives each match status (services/control-panel/src/lib/match.ts).
STATUS_LABELS = {
    "ready_check": "Ready check",
    "captain_phase": "Captain vote",
    "captain_checkin": "Captain check-in",
    "player_draft": "Player draft",
    "coinflip": "Captain coinflip",
    "team_confirm": "Captains confirm teams",
    "champion_draft": "Champion draft",
    "lobby_code": "Lobby code",
    "in_progress": "In progress",
    "awaiting_confirmation": "Awaiting confirmation",
    "completed": "Completed",
}

# A phase played through the bot clicks for every player who has to act.
ACTION_TIMEOUT = 90_000


class ControlPanel:
    """The whole app: header, tabs, toasts."""

    def __init__(self, page: Page) -> None:
        self.page = page

    def open(self) -> Self:
        self.page.goto("/")
        expect(self.page.get_by_text("DEV ONLY", exact=True)).to_be_visible()
        return self

    # --- Header --------------------------------------------------------------------------

    def health(self, service: str) -> Locator:
        """The health chip of `web`, `sim` or `bot`. Its label says how that service is."""
        return self.page.get_by_label(re.compile(rf"^{service}: "))

    def expect_healthy(self) -> None:
        expect(self.health("web")).to_have_attribute("aria-label", "web: control API answering")
        expect(self.health("sim")).to_have_attribute(
            "aria-label", re.compile(r"^sim: simulator \S+ answering$")
        )
        expect(self.health("bot")).to_have_attribute(
            "aria-label", "bot: bot connected to the sim gateway"
        )

    def reset(self) -> None:
        self.page.get_by_role("button", name="Reset…").click()
        dialog = self.page.get_by_role("alertdialog", name="Reset the dev stack?")
        dialog.get_by_role("button", name="Reset everything").click()
        self.finish("Reset", "Reset to fixtures")
        expect(dialog).to_be_hidden()

    def pause_timers(self) -> None:
        self.page.get_by_role("button", name="Pause timers").click()
        self.finish("Pause timers")

    def resume_timers(self) -> None:
        self.page.get_by_role("button", name="Resume timers").click()
        self.finish("Resume timers")

    # --- Toasts ----------------------------------------------------------------------------

    def toast(self, name: str | re.Pattern[str]) -> Locator:
        return self.page.get_by_role("alertdialog", name=name, exact=isinstance(name, str))

    def finish(self, action: str, success: str | re.Pattern[str] | None = None) -> None:
        """Wait for the outcome of `action`: its success toast (by default "<action>: done"),
        which is then closed, or its error toast, which fails the test with the panel's
        message."""
        done = self.toast(success or f"{action}: done")
        failed = self.toast(action)
        expect(done.or_(failed).first).to_be_visible(timeout=ACTION_TIMEOUT)
        if failed.count():
            raise AssertionError(f"{action} failed in the panel: {failed.first.inner_text()}")
        # The toast covers its own close button for the pointer while it slides in.
        done.first.get_by_role("button", name="Close").dispatch_event("click")
        expect(done).to_have_count(0)

    # --- Screens ---------------------------------------------------------------------------

    def _tab(self, name: str) -> None:
        tab = self.page.get_by_role("tab", name=name)
        tab.click()
        expect(tab).to_have_attribute("aria-selected", "true")

    def players(self) -> PlayersScreen:
        self._tab("Players")
        return PlayersScreen(self)

    def matches(self) -> MatchesScreen:
        self._tab("Queue & matches")
        return MatchesScreen(self)

    def discord(self) -> DiscordScreen:
        self._tab("Discord view")
        return DiscordScreen(self)

    def scenarios(self) -> ScenariosScreen:
        self._tab("Scenarios")
        return ScenariosScreen(self)


def choose(page: Page, trigger: Locator, option: str | re.Pattern[str]) -> None:
    """Pick an option of a HeroUI select, or an item of a dropdown menu."""
    trigger.click()
    item = page.get_by_role("option", name=option).or_(page.get_by_role("menuitem", name=option))
    item.first.click()


def toggle(switch: Locator, on: bool) -> None:
    """Set a HeroUI switch or checkbox. Its input is visually hidden; the label takes clicks."""
    if switch.is_checked() != on:
        switch.locator("xpath=ancestor::label").click()
    expect(switch).to_be_checked(checked=on)


class PlayersScreen:
    """Screen 1: make fake players and tune each one."""

    def __init__(self, panel: ControlPanel) -> None:
        self.panel = panel
        self.page = panel.page

    def add_players(
        self,
        count: int,
        rating: int,
        max_rating: int | None = None,
        *,
        prefix: str,
        join_queue: bool = False,
    ) -> None:
        """Add `count` players at `rating`, or spread from `rating` to `max_rating`."""
        form = self.page.locator("[data-slot=card]").filter(has_text="Add fake players")
        form.get_by_label("Count").fill(str(count))
        form.get_by_label("Rating (or min)").fill(str(rating))
        form.get_by_label("Max (range)").fill("" if max_rating is None else str(max_rating))
        form.get_by_label("Name prefix").fill(prefix)
        toggle(form.get_by_role("switch", name="Join queue"), join_queue)
        form.get_by_role("button", name="Add players").click()
        self.panel.finish("Add players", f"Added {count}")

    def row(self, name: str) -> Locator:
        return self.page.get_by_role("row").filter(
            has=self.page.get_by_role("cell", name=name, exact=True)
        )

    def set_plan(self, name: str, prefer: list[str], ban: list[str]) -> None:
        """Save a player's champion plan, which the autopilot follows for their team."""
        self.row(name).get_by_role("button", name="Edit…").click()
        dialog = self.page.get_by_role("dialog", name=f"Champion plan: {name}")
        dialog.get_by_label("Preferred").fill(", ".join(prefer))
        dialog.get_by_label("Banned").fill(", ".join(ban))
        dialog.get_by_role("button", name="Save plan").click()
        self.panel.finish("Save plan")
        expect(dialog).to_be_hidden()

    def queue_matching(self, text: str, expected: int) -> None:
        """Filter the table, select every player it shows, and queue them."""
        self.page.get_by_label("Filter players").fill(text)
        expect(
            self.page.get_by_role("checkbox", name=re.compile(r"^Select (?!all)"))
        ).to_have_count(expected)
        toggle(self.page.get_by_role("checkbox", name="Select all"), True)
        self.page.get_by_role("button", name="Queue selected", exact=True).click()
        self.panel.finish("Join queue")


class MatchesScreen:
    """Screen 2: the queue and the live matches."""

    def __init__(self, panel: ControlPanel) -> None:
        self.panel = panel
        self.page = panel.page

    def queue_panel(self) -> Locator:
        return self.page.locator("[data-slot=card]").filter(has_text=re.compile(r"^Queue \("))

    def fill_queue(self) -> None:
        self.page.get_by_role("button", name="Fill to 12").click()
        self.panel.finish("Fill queue", "Queue filled to 12")

    def act_via(self, how: str) -> None:
        """`Act via Discord clicks`, `Act via league services` or `Auto`."""
        trigger = self.page.get_by_role("button", name=re.compile("Players act via"))
        choose(self.page, trigger, re.compile(f"^{re.escape(how)}"))
        expect(trigger).to_contain_text(how)

    def card(self, match_id: int) -> MatchCard:
        return MatchCard(self.panel, match_id)

    def recent(self) -> Locator:
        return self.page.locator("[data-slot=card]").filter(has_text="Recent matches")


class MatchCard:
    """One live match on screen 2."""

    def __init__(self, panel: ControlPanel, match_id: int) -> None:
        self.panel = panel
        self.page = panel.page
        self.match_id = match_id
        self.root = self.page.locator("[data-slot=card]").filter(
            has=self.page.get_by_text(f"#{match_id}", exact=True)
        )

    def expect_status(self, status: str) -> None:
        expect(self.root.get_by_text(STATUS_LABELS[status], exact=True).first).to_be_visible()

    def _advanced(self, from_status: str) -> re.Pattern[str]:
        # The panel's toast for an advance: "Ready check → Captain vote (12 actions)".
        return re.compile(rf"^{re.escape(STATUS_LABELS[from_status])} → .+ \(\d+ actions\)$")

    def complete_phase(self, from_status: str) -> None:
        """Play out the current phase, as the players who still have to act."""
        self.root.get_by_role("button", name="Complete phase").click()
        self.panel.finish("Complete phase", self._advanced(from_status))

    def advance_to(self, from_status: str, until: str) -> None:
        """Play phase after phase until the match reaches `until`."""
        trigger = self.root.get_by_role("button", name="Advance to ▸")
        choose(self.page, trigger, STATUS_LABELS[until])
        self.panel.finish(f"Advance to {until}", self._advanced(from_status))

    def pause(self) -> None:
        self.root.get_by_role("button", name="Pause timer").click()
        self.panel.finish("Pause")
        expect(self.root.get_by_text("frozen", exact=True)).to_be_visible()

    def resume(self) -> None:
        self.root.get_by_role("button", name="Resume timer").click()
        self.panel.finish("Resume")
        expect(self.root.get_by_text("frozen", exact=True)).to_be_hidden()

    def fire(self) -> None:
        self.root.get_by_role("button", name="Fire now").click()
        self.panel.finish("Fire deadline")

    def timer(self) -> Locator:
        return self.root.get_by_label(re.compile(r"^(time left|no timer)"))

    def script(self) -> ScriptModal:
        self.root.get_by_role("button", name="Script…").click()
        return ScriptModal(self.panel, self.match_id)


class ScriptModal:
    """The plan the autopilot follows for one match."""

    def __init__(self, panel: ControlPanel, match_id: int) -> None:
        self.panel = panel
        self.page = panel.page
        self.dialog = self.page.get_by_role("dialog", name=f"Script for match #{match_id}")
        expect(self.dialog).to_be_visible()

    def captain_votes(self, value: str) -> Self:
        self.dialog.get_by_label(re.compile(r"^Captain votes")).fill(value)
        return self

    def draft_order(self, player_ids: list[int]) -> Self:
        self.dialog.get_by_label(re.compile(r"^Draft order")).fill(", ".join(map(str, player_ids)))
        return self

    def champion_steps(self, steps: dict[int, str]) -> Self:
        lines = "\n".join(f"{step} {slug}" for step, slug in sorted(steps.items()))
        self.dialog.get_by_label(re.compile(r"^Champion steps")).fill(lines)
        return self

    def coinflip(self, side: str) -> Self:
        trigger = self.dialog.get_by_role("button", name=re.compile("The winner's side"))
        choose(self.page, trigger, side)
        expect(trigger).to_contain_text(side)
        return self

    def winner(self, team: str) -> Self:
        trigger = self.dialog.get_by_role("button", name=re.compile("Winner the captains report"))
        choose(self.page, trigger, f"Team {team}")
        expect(trigger).to_contain_text(f"Team {team}")
        return self

    def save(self) -> None:
        self.dialog.get_by_role("button", name="Save script").click()
        self.panel.finish("Save script")
        expect(self.dialog).to_be_hidden()


class DiscordScreen:
    """Screen 3: the simulated guild, clickable as any fake user."""

    def __init__(self, panel: ControlPanel) -> None:
        self.panel = panel
        self.page = panel.page

    def act_as(self, name: str) -> None:
        trigger = self.page.get_by_role("button", name=re.compile("Act as"))
        choose(self.page, trigger, re.compile(rf"^{re.escape(name)} · \d+$"))
        expect(trigger).to_contain_text(name)

    def open_channel(self, name: str) -> Locator:
        """Show a channel; returns its message log."""
        nav = self.page.get_by_role("navigation", name="Channels and DMs")
        nav.get_by_role("button", name=f"# {name}", exact=True).click()
        log = self.page.get_by_role("log", name=f"Messages in # {name}")
        expect(log).to_be_visible()
        return log

    def bot_modal(self, title: str) -> BotModal:
        return BotModal(self.panel, title)


class BotModal:
    """A form a bot button opened, as the fake user sees it."""

    def __init__(self, panel: ControlPanel, title: str) -> None:
        self.dialog = panel.page.get_by_role("dialog", name=title)
        expect(self.dialog).to_be_visible()

    def attach(self, label: str, name: str, png: bytes) -> Self:
        self.dialog.get_by_label(label).set_input_files(
            {"name": name, "mimeType": "image/png", "buffer": png}
        )
        expect(self.dialog.get_by_text("1 file chosen.")).to_be_visible()
        return self

    def submit(self, as_user: str) -> None:
        self.dialog.get_by_role("button", name=f"Submit as {as_user}").click()
        expect(self.dialog).to_be_hidden(timeout=ACTION_TIMEOUT)


class ScenariosScreen:
    """Screen 4: the preset scenarios, as runbooks."""

    def __init__(self, panel: ControlPanel) -> None:
        self.page = panel.page

    def run(self, name: str) -> None:
        """Run a scenario from its first step to its last, and expect every step to pass."""
        listing = self.page.get_by_role("list", name="Scenarios")
        listing.get_by_role("button").filter(has=self.page.get_by_text(name, exact=True)).click()
        steps = self.page.get_by_role("list", name="Steps").get_by_role("listitem")
        expect(steps.first).to_be_visible()
        self.page.get_by_role("button", name=re.compile(r"^Run\b")).click()
        message = self.page.get_by_role("status").filter(
            has_text=re.compile(r"^(Every step ran\.|Step \d+: .*|Paused .*)$")
        )
        expect(message).to_be_visible(timeout=ACTION_TIMEOUT * 2)
        expect(message).to_have_text("Every step ran.")
