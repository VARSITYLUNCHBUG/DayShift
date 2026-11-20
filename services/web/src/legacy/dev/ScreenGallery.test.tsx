// The gallery's M6, M7 and M8 entries render (each on its own FakeServer).
import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderPage } from "../../test/render";
import ScreenGallery from "./ScreenGallery";

const DRAFT_ENTRIES = [
  "captain-vote",
  "captain-vote-ineligible",
  "captain-vote-watching",
  "captain-vote-auto",
  "player-draft-pick",
  "player-draft-waiting",
  "coinflip-choose",
  "coinflip-waiting",
  "hero-draft-turn",
  "hero-draft-waiting",
  "hero-draft-watching",
  "lobby-code-host",
  "lobby-code-waiting",
  "lobby",
  "lobby-watching",
  "in-game",
  "scrim-claim",
  "scrim-coinflip",
  "scrim-ready",
  "scrim-draft",
  "scrim-drafted",
];

const RESULT_ENTRIES = [
  "in-game-captain",
  "report",
  "confirm",
  "confirm-waiting",
  "dispute-note",
  "score-names",
  "result",
  "result-watching",
  "disputed",
  "cancelled",
  "cancelled-missed",
];

const SUB_ENTRIES = [
  "sub-request",
  "sub-request-captain",
  "sub-name",
  "sub-naming-notice",
  "sub-approve",
  "sub-approval-waiting",
  "paused",
  "paused-leaving",
  "early-leave",
  "early-leave-answer",
  "early-leave-waiting",
  "refill",
];

describe("ScreenGallery", () => {
  it.each([...DRAFT_ENTRIES, ...RESULT_ENTRIES, ...SUB_ENTRIES])("renders %s", async (id) => {
    renderPage(<ScreenGallery />, { route: `/dev/screens/legacy/${id}`, path: "/dev/screens/legacy/*", live: false });
    expect(await screen.findByText("No. 1")).toBeInTheDocument();
  });

  it.each([
    ["sub-invite", "P3 wants you to sub in"],
    ["spot-offer", "A spot opened"],
  ])("renders %s over Play", async (id, heading) => {
    renderPage(<ScreenGallery />, { route: `/dev/screens/legacy/${id}`, path: "/dev/screens/legacy/*", live: false });
    expect(await screen.findByRole("heading", { name: heading })).toBeInTheDocument();
  });

  it("renders the toasts sheet", async () => {
    renderPage(<ScreenGallery />, { route: "/dev/screens/legacy/toasts", path: "/dev/screens/legacy/*", live: false });
    expect(await screen.findByText(/Toasts show at the bottom right/)).toBeInTheDocument();
  });

  it.each([
    ["matches", "Matches"],
    ["matches-live", "Matches"],
    ["match-detail", "Match 1 · Blazing Lion"],
    ["match-detail-raw", "Match 1 · Blazing Lion"],
    ["leaderboard", "Leaderboard"],
    ["leaderboard-pinned", "Leaderboard"],
    ["leaderboard-empty", "Leaderboard"],
    ["profile", "P3"],
    ["profile-other", "P5"],
    ["profile-new", "P3"],
    ["random-draft", "Random draft"],
    ["random-draft-empty", "Random draft"],
  ])("renders %s", async (id, heading) => {
    renderPage(<ScreenGallery />, { route: `/dev/screens/legacy/${id}`, path: "/dev/screens/legacy/*", live: false });
    expect(await screen.findByRole("heading", { name: heading, level: 1 })).toBeInTheDocument();
  });

  it("renders the result with its record, from fixtures only", async () => {
    const fetch = vi.fn(() => Promise.reject(new Error("The gallery must not ask the server.")));
    vi.stubGlobal("fetch", fetch);
    renderPage(<ScreenGallery />, { route: "/dev/screens/legacy/result", path: "/dev/screens/legacy/*", live: false });
    expect(await screen.findByLabelText("Awards")).toBeInTheDocument();
    expect(fetch.mock.calls).toEqual([]);
    vi.unstubAllGlobals();
  });

  it("renders Play while in a match", async () => {
    renderPage(<ScreenGallery />, { route: "/dev/screens/legacy/play-in-match", path: "/dev/screens/legacy/*", live: false });
    expect(await screen.findByRole("heading", { name: "Match 1 · Player draft" })).toBeInTheDocument();
  });
});
