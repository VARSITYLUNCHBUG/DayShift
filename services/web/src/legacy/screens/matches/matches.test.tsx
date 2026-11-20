// 5.1 Matches, 5.2 a past match, and 3.6's record: live rows from the `live` topic, finished
// ones over HTTP (fetch stubbed with the completed.http-* fixtures).
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { fixture, http, matchList, recordedMatch } from "../../dev/fixtures";
import type { LiveSnap, MatchList } from "../../../live/types";
import { renderPage } from "../../../test/render";
import { json, serveHttp } from "../../../test/http";
import { MatchRoute } from "../match/MatchRoute";
import { listed, MatchesPage } from "./Matches";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

const RECENT = "/api/matches/?status=recent";

function openMatches(live: LiveSnap, answers: Record<string, unknown>) {
  const fetch = serveHttp(answers);
  const me = fixture.me("completed", "player");
  const page = renderPage(<MatchesPage />, { snaps: { me, live }, playerId: me.player.id, route: "/matches" });
  return { ...page, fetch };
}

/** The table's rows, header row left out. */
function rows() {
  const table = screen.getByRole("grid", { name: "Matches" });
  return within(table).getAllByRole("row").slice(1);
}

describe("listed", () => {
  it("puts live matches first and shows a match that just finished once", () => {
    const live = fixture.live("in_progress").matches;
    const recent = matchList().matches;
    const all = listed(live, recent, "1", "all");
    expect(all.map((r) => [r.id, r.live])).toEqual([
      ["1", true],
      ["17", false],
      ["16", false],
      ["15", false],
    ]);
    expect(all[0]?.yours).toBe(true);
    expect(listed(live, recent, null, "live").map((r) => r.id)).toEqual(["1"]);
    // The server already left out other people's finished matches.
    expect(listed(live, recent, null, "mine").map((r) => r.id)).toEqual(["1", "17", "16", "15"]);
  });
});

describe("Matches", () => {
  it("lists the finished matches with their captains, winner and draft name", async () => {
    openMatches({ matches: [] }, { [RECENT]: http.matches() });
    expect(await screen.findByRole("link", { name: /^Match 1 · Blazing Lion/ })).toHaveAttribute("href", "/matches/1");
    const [row] = rows();
    expect(within(row!).getByText("Finished")).toBeInTheDocument();
    expect(within(row!).getByText("P1's Team")).toBeInTheDocument();
    expect(within(row!).getByText("P2")).toHaveClass("text-team-hk");
    expect(within(row!).getByText("P1")).toHaveClass("text-team-am");
    expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
  });

  it("shows the live ones from the live topic, on top", async () => {
    openMatches(fixture.live("in_progress"), { [RECENT]: { matches: [], next_cursor: null } });
    expect(await screen.findByRole("link", { name: /^Match 1 · Blazing Lion/ })).toBeInTheDocument();
    expect(within(rows()[0]!).getByText("In game")).toBeInTheDocument();
  });

  it("loads more with the cursor", async () => {
    const first: MatchList = { matches: http.matches().matches, next_cursor: "1" };
    const second = matchList();
    second.matches = second.matches.slice(1);
    second.next_cursor = null;
    const { fetch } = openMatches({ matches: [] }, { [RECENT]: first, [`${RECENT}&cursor=1`]: second });
    await userEvent.click(await screen.findByRole("button", { name: "Load more" }));
    expect(await screen.findByRole("link", { name: /^Match 15 · Low Tide/ })).toBeInTheDocument();
    expect(rows()).toHaveLength(4);
    expect(fetch).toHaveBeenCalledWith(`${RECENT}&cursor=1`, expect.anything());
    expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
  });

  it("asks for only the viewer's matches under Mine, and none under Live", async () => {
    const { fetch } = openMatches(fixture.live("in_progress"), {
      [RECENT]: matchList(),
      [`${RECENT}&mine=1`]: http.matches(),
    });
    await screen.findByRole("link", { name: /^Match 17/ });
    await userEvent.click(screen.getByRole("tab", { name: "Mine" }));
    await vi.waitFor(() => expect(fetch).toHaveBeenCalledWith(`${RECENT}&mine=1`, expect.anything()));
    await vi.waitFor(() => expect(screen.queryByRole("link", { name: /^Match 17/ })).not.toBeInTheDocument());
    await userEvent.click(screen.getByRole("tab", { name: "Live" }));
    expect(rows().map((r) => within(r).getAllByRole("link")[0]?.textContent)).toEqual(["Match 1 · Blazing Lion"]);
    expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
  });

  it("asks again when a live match ends", async () => {
    const live = fixture.live("in_progress");
    const { fetch, server } = openMatches(live, { [RECENT]: { matches: [], next_cursor: null } });
    await screen.findByRole("link", { name: /^Match 1/ });
    const before = fetch.mock.calls.length;
    server.snap("live", { matches: [] });
    await vi.waitFor(() => expect(fetch.mock.calls.length).toBeGreaterThan(before));
  });

  it("says when there's nothing, or when the list wouldn't load", async () => {
    openMatches({ matches: [] }, { [RECENT]: { matches: [], next_cursor: null } });
    expect(await screen.findByText("No matches this season yet")).toBeInTheDocument();
  });

  it("offers to try again after a failure", async () => {
    openMatches({ matches: [] }, { [RECENT]: () => json({}, 500) });
    expect(await screen.findByText("Couldn't load the finished matches.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});

describe("A match the live connection doesn't serve", () => {
  function openGone(id: string, answers: Record<string, unknown>) {
    serveHttp(answers);
    const me = fixture.me("completed", "player");
    return renderPage(<MatchRoute />, { snaps: { me }, playerId: me.player.id, route: `/matches/${id}`, path: "/matches/:id" });
  }

  it("shows its record (5.2)", async () => {
    openGone("1", { "/api/matches/1/": recordedMatch() });
    expect(await screen.findByRole("heading", { name: "Match 1 · Blazing Lion" })).toBeInTheDocument();
    expect(screen.getByText("Upset · 37% to win")).toBeInTheDocument();
    expect(screen.getByText("31:52")).toBeInTheDocument();
    expect(screen.getByText("38204912")).toBeInTheDocument();
    expect(screen.getAllByRole("listitem", { name: /: ban / })).toHaveLength(6);
    const winners = screen.getByRole("list", { name: "P1's Team players" });
    expect(within(winners).getByText("MVP")).toBeInTheDocument();
    // Profiles are private: names are text, not links to someone else's profile.
    expect(within(winners).queryByRole("link", { name: "P1" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to Matches" })).toHaveAttribute("href", "/matches");
  });

  it("says it isn't there when the server has no record either", async () => {
    openGone("404", {});
    expect(await screen.findByText("Match not found")).toBeInTheDocument();
  });
});

describe("Result with the match's record (3.6)", () => {
  it("adds the awards, ratings before and after, the length and the draft", async () => {
    const fetch = serveHttp({ "/api/matches/1/": recordedMatch() });
    const match = fixture.match("completed", "player");
    const me = fixture.me("completed", "player");
    renderPage(<MatchRoute />, {
      snaps: { me, [`match:${match.id}`]: match },
      playerId: me.player.id,
      route: `/matches/${match.id}`,
      path: "/matches/:id",
    });
    expect(await screen.findByRole("heading", { name: "Defeat" })).toBeInTheDocument();
    expect(await screen.findByLabelText("Awards")).toBeInTheDocument();
    const awards = screen.getByLabelText("Awards");
    expect(within(awards).getByText("MVP")).toBeInTheDocument();
    expect(within(awards).getAllByText("Key")).toHaveLength(2);
    expect(screen.getByText(/^P1's Team won · The Archmother · 31:52/)).toBeInTheDocument();
    // P3 is the viewer: 1,180 + 37 + 0 before, and lost 20.
    expect(screen.getByText("1,217 → 1,197")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Draft" })).toBeInTheDocument();
    expect(screen.getByText(/^Paradox 11\/5\/6/)).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith("/api/matches/1/", expect.anything());
  });
});
