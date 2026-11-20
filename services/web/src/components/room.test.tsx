import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AM_PLAYERS, DRAFT_STEPS, heroChoices, HK_PLAYERS, inSeconds } from "../dev/sample";
import { renderPage } from "../test/render";
import { DraftStrip } from "./DraftStrip";
import { HeroCard } from "./HeroCard";
import { HeroGrid } from "./HeroGrid";
import { LobbyCode } from "./LobbyCode";
import { PlayerGrid } from "./PlayerGrid";
import { PlayerTile } from "./PlayerTile";
import { Scorebug, TeamBlock, TurnBanner } from "./Scorebug";
import { TeamPanel } from "./TeamPanel";

describe("HeroCard", () => {
  it("says Banned on a banned hero, and lifts the selected one", () => {
    render(
      <>
        <HeroCard name="Haze" state="banned" />
        <HeroCard name="Ivy" state="selected" tag="Pike wants her" />
      </>,
    );
    expect(screen.getByText("Banned")).toBeInTheDocument();
    expect(screen.getByText("Pike wants her")).toBeInTheDocument();
    expect(screen.getByText("Ivy").closest(".tilt-card")).not.toBeNull();
  });
});

describe("HeroGrid", () => {
  it("is one pick grid: banned and taken heroes can't be picked", async () => {
    const onSelect = vi.fn();
    render(<HeroGrid heroes={heroChoices()} selectedId={null} onSelect={onSelect} />);
    const grid = screen.getByRole("listbox", { name: "Heroes" });
    expect(within(grid).getByRole("option", { name: /^Haze/ })).toHaveAttribute("aria-disabled", "true");
    expect(within(grid).getByRole("option", { name: /^Dynamo/ })).toHaveAttribute("aria-disabled", "true");
    await userEvent.click(within(grid).getByRole("option", { name: /^Ivy/ }));
    expect(onSelect).toHaveBeenCalledWith("Ivy");
    await userEvent.click(within(grid).getByRole("option", { name: /^Haze/ }));
    expect(onSelect).toHaveBeenCalledTimes(1);
  });

  it("marks the chosen hero selected", () => {
    render(<HeroGrid heroes={heroChoices()} selectedId="Ivy" onSelect={() => {}} />);
    expect(screen.getByRole("option", { name: /^Ivy/ })).toHaveAttribute("aria-selected", "true");
  });

  it("stays browsable but not pickable while waiting", () => {
    render(<HeroGrid heroes={heroChoices()} />);
    expect(screen.getByRole("option", { name: /^Mirage/ })).not.toHaveAttribute("aria-selected", "true");
  });
});

describe("PlayerTile, TeamPanel and PlayerGrid", () => {
  it("tints your own row and shows its action", () => {
    render(
      <ul>
        <PlayerTile name="Rook" tag="OWL" team="hk" isYou line="Captain" action={<button type="button">Swap</button>} />
      </ul>,
    );
    expect(screen.getByRole("listitem")).toHaveClass("bg-team-hk-soft");
    expect(screen.getByText("Captain")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Swap" })).toBeInTheDocument();
  });

  it("names a team's panel after it and lists its six", () => {
    render(<TeamPanel team="am" name="Vesper's Team" players={AM_PLAYERS.map((p) => ({ id: p.id, name: p.name, tag: p.tag }))} />);
    const panel = screen.getByRole("region", { name: "Vesper's Team" });
    expect(within(panel).getByText("The Archmother")).toBeInTheDocument();
    expect(within(panel).getAllByRole("listitem")).toHaveLength(6);
  });

  it("picks a player from the grid", async () => {
    const onSelect = vi.fn();
    render(<PlayerGrid players={HK_PLAYERS.map((p) => ({ id: p.id, name: p.name, tag: p.tag, line: "Gold" }))} onSelect={onSelect} />);
    await userEvent.click(screen.getByRole("option", { name: /Pike/ }));
    expect(onSelect).toHaveBeenCalledWith("2");
  });
});

describe("DraftStrip", () => {
  it("is a list to read: done steps carry the hero, the current one is marked", () => {
    render(<DraftStrip steps={DRAFT_STEPS} current={7} />);
    const strip = screen.getByRole("list", { name: "Draft order" });
    const steps = within(strip).getAllByRole("listitem");
    expect(steps).toHaveLength(18);
    expect(steps[2]).toHaveAccessibleName("Hidden King ban, step 3: Seven");
    expect(steps[2]).toHaveClass("line-through");
    expect(steps[7]).toHaveAttribute("aria-current", "step");
    expect(steps[7]).toHaveClass("bg-team-hk");
  });
});

describe("Scorebug and TurnBanner", () => {
  it("puts whose move, the clock and the one action in the middle", () => {
    renderPage(
      <Scorebug
        left={<TeamBlock team="hk" name="Rook's Team" line="Captain Rook" isActing />}
        right={<TeamBlock team="am" name="Vesper's Team" line="Captain Vesper" align="end" />}
        deadline={inSeconds(27)}
        tone="hk"
        title="Your pick, Rook"
        action={<button type="button">Lock in Ivy</button>}
      />,
      { live: false },
    );
    const bug = screen.getByRole("region", { name: "Now" });
    expect(within(bug).getByRole("timer")).toHaveClass("text-team-hk");
    expect(within(bug).getByText("Your pick, Rook")).toBeInTheDocument();
    expect(within(bug).getByText("On the clock")).toBeInTheDocument();
    expect(within(bug).getByRole("button", { name: "Lock in Ivy" })).toBeInTheDocument();
  });

  it("draws the compact banner in the acting team's colour", () => {
    renderPage(<TurnBanner deadline={inSeconds(19)} tone="am" title="Vesper's pick" line="You're next" />, { live: false });
    expect(screen.getByRole("region", { name: "Now" })).toHaveClass("bg-team-am-soft", "border-team-am");
  });
});

describe("LobbyCode", () => {
  it("reads the code letter by letter and copies it", async () => {
    const writeText = vi.fn(() => Promise.resolve());
    Object.assign(navigator, { clipboard: { writeText } });
    renderPage(<LobbyCode code="K7Q2PX" />, { live: false });
    expect(screen.getByText("Lobby code: K 7 Q 2 P X")).toHaveClass("sr-only");
    await userEvent.click(screen.getByRole("button", { name: "Copy the lobby code" }));
    expect(writeText).toHaveBeenCalledWith("K7Q2PX");
  });
});
