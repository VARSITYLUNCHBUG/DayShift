// TurnBanner, TurnStrip, TeamPanel, SideChip, HeroGrid and HeroCard, from the hero draft fixture.
import { fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { fixture } from "../dev/fixtures";
import { renderPage } from "../../test/render";
import { HeroCard } from "./HeroCard";
import { HeroGrid, heroTags } from "./HeroGrid";
import { SideChip } from "./SideChip";
import { TeamPanel } from "./TeamPanel";
import { TurnBanner } from "./TurnBanner";
import { championSteps, TurnStrip } from "./TurnStrip";

const draft = () => fixture.match("champion_draft", "captain");

describe("TurnBanner", () => {
  it("says whose turn it is, with the clock", async () => {
    const match = draft();
    renderPage(
      <TurnBanner tone="am" line="Ban 4 of 6 · Next: P2" title="Your ban" deadline={match.deadline_at} showBar />,
    );
    expect(screen.getByRole("heading", { name: "Your ban" })).toBeInTheDocument();
    expect(screen.getByText("Ban 4 of 6 · Next: P2")).toBeInTheDocument();
    expect(await screen.findByText(/^0:2[01]$/)).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Turn time left" })).toBeInTheDocument();
  });
});

describe("TurnStrip", () => {
  it("shows done, current and upcoming steps", () => {
    const steps = championSteps(draft());
    expect(steps).toHaveLength(18);
    expect(steps.filter((s) => s.state === "done")).toHaveLength(3);
    expect(steps[3]).toMatchObject({ label: "B2", state: "current", side: "am" });
    renderPage(<TurnStrip steps={steps} />, { live: false });
    const current = screen.getAllByRole("listitem").find((li) => li.getAttribute("aria-current") === "step");
    expect(current).toHaveAccessibleName("P1's Team ban, step 4");
  });
});

describe("TeamPanel and SideChip", () => {
  it("shows a team's side, bans, empty pick slots and players", () => {
    const match = draft();
    renderPage(<TeamPanel match={match} team="A" showHeroes />, { live: false });
    const panel = screen.getByRole("heading", { name: "P2's Team" }).closest("[aria-labelledby]") as HTMLElement;
    expect(within(panel).getByText("The Hidden King")).toBeInTheDocument();
    expect(within(panel).getByText("Infernus")).toBeInTheDocument();
    expect(within(panel).getByText("Vindicta")).toBeInTheDocument();
    const players = within(panel).getByRole("list", { name: "Players" });
    // The captain first.
    expect(within(players).getAllByRole("listitem")[0]).toHaveTextContent("P2C");
    expect(within(players).getAllByRole("listitem")).toHaveLength(6);
  });

  it("names the side", () => {
    renderPage(<SideChip side="am" detail="Pick 2" />, { live: false });
    expect(screen.getByText("The Archmother · Pick 2")).toBeInTheDocument();
  });
});

describe("HeroGrid and HeroCard", () => {
  it("lets the acting captain pick a free hero, not a taken one", async () => {
    const match = draft();
    const onSelect = vi.fn();
    renderPage(<HeroGrid champions={match.champions} onSelect={onSelect} tags={heroTags(match)} />, { live: false });
    expect(screen.getByRole("button", { name: "Infernus, banned" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Pick Abrams" }));
    expect(onSelect).toHaveBeenCalledWith("6");
  });

  it("marks the selected hero", () => {
    const match = draft();
    renderPage(<HeroGrid champions={match.champions} selectedId="6" onSelect={() => {}} />, { live: false });
    expect(screen.getByRole("button", { name: "Pick Abrams" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Selected")).toBeInTheDocument();
  });

  it("falls back from the icon to initials", () => {
    const champion = { id: "1", name: "Grey Talon", slug: "grey_talon", icon_url: "https://example.test/gt.png" };
    const { container } = renderPage(<HeroCard champion={champion} />, { live: false });
    const img = container.querySelector("img");
    expect(img).toHaveAttribute("src", champion.icon_url);
    fireEvent.error(img!);
    expect(screen.getByText("GT")).toBeInTheDocument();
  });

  it("shows the art pack's card, and initials if it isn't there (404)", () => {
    const champion = { id: "2", name: "Mo & Krill", slug: "mo-and-krill", icon_url: "/static/hero-art/mo-and-krill.webp" };
    const { container } = renderPage(<HeroCard champion={champion} compact />, { live: false });
    const img = container.querySelector("img");
    expect(img).toHaveAttribute("src", "/static/hero-art/mo-and-krill.webp");
    expect(screen.queryByText("MK")).not.toBeInTheDocument();
    fireEvent.error(img!);
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText("MK")).toBeInTheDocument();
    expect(screen.getByText("Mo & Krill")).toBeInTheDocument();
  });

  it("shows initials when there's no art at all", () => {
    const champion = { id: "3", name: "Lady Geist", slug: "lady-geist", icon_url: null };
    const { container } = renderPage(<HeroCard champion={champion} />, { live: false });
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText("LG")).toBeInTheDocument();
  });
});
