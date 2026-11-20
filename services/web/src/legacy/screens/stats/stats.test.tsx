// 5.3 Leaderboard and 5.4 Profile, over HTTP (fetch stubbed with the completed.http-* fixtures
// and what's derived from them).
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { fixture, http, seasonLeaderboard, seasonProfile, twoSeasons } from "../../dev/fixtures";
import type { MeSnap } from "../../../live/types";
import { renderPage } from "../../../test/render";
import { serveHttp } from "../../../test/http";
import { LeaderboardPage } from "./LeaderboardPage";
import { ProfilePage } from "./ProfilePage";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function me(steam?: MeSnap["player"]["steam"]): MeSnap {
  const snap = fixture.me("completed", "player");
  if (steam) snap.player = { ...snap.player, steam };
  return snap;
}

function openLeaderboard(answer: unknown, more: Record<string, unknown> = {}, route = "/leaderboard") {
  const fetch = serveHttp({ "/api/leaderboard/": answer, ...more });
  const snap = me();
  renderPage(<LeaderboardPage />, { snaps: { me: snap }, playerId: snap.player.id, route });
  return fetch;
}

function urls(fetch: ReturnType<typeof serveHttp>): string[] {
  return fetch.mock.calls.map(([url]) => url);
}

function bodyRows() {
  return within(screen.getByRole("grid")).getAllByRole("row").slice(1);
}

describe("Leaderboard", () => {
  it("ranks the season with tiers, and highlights the viewer's row", async () => {
    openLeaderboard(seasonLeaderboard());
    expect(await screen.findByRole("heading", { name: "Leaderboard" })).toBeInTheDocument();
    expect(screen.getByText("Season 1 · ranked after 10 games")).toBeInTheDocument();
    const rows = bodyRows();
    expect(rows).toHaveLength(10);
    const first = rows[0]!;
    expect(within(first).getByText("Pike")).toBeInTheDocument();
    expect(within(first).queryByRole("link", { name: "Pike" })).not.toBeInTheDocument();
    expect(within(first).getByText("Diamond")).toBeInTheDocument();
    expect(within(first).getByText("1,452")).toBeInTheDocument();
    expect(within(first).getByText("41–22")).toBeInTheDocument();
    const mine = rows[5]!;
    expect(within(mine).getByText("You")).toBeInTheDocument();
    expect(mine).toHaveClass("bg-accent-soft");
    expect(rows.filter((r) => r.className.includes("bg-accent-soft"))).toHaveLength(1);
  });

  it("adds the viewer's own row at the foot when they're not in the list", async () => {
    openLeaderboard(seasonLeaderboard(true));
    await screen.findByRole("heading", { name: "Leaderboard" });
    const rows = bodyRows();
    expect(rows).toHaveLength(10);
    const last = rows.at(-1)!;
    expect(within(last).getAllByText("P3").length).toBeGreaterThan(0);
    expect(within(last).getByText("–")).toBeInTheDocument();
    expect(last).toHaveClass("bg-accent-soft");
    expect(screen.getByText("You're ranked once you've played 10 games: 6 so far.")).toBeInTheDocument();
  });

  it("starts the season with nobody ranked but the viewer's row", async () => {
    openLeaderboard(http.leaderboard());
    await screen.findByRole("heading", { name: "Leaderboard" });
    expect(bodyRows()).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "Show more" })).not.toBeInTheDocument();
  });

  it("shows more rows a page at a time", async () => {
    const first = { ...seasonLeaderboard(), next_offset: 10 };
    const extra = { ...first.rows[9]!, rank: 11, player: { id: "300", name: "Zed", avatar_url: null } };
    const second = { ...first, rows: [extra], next_offset: null };
    const fetch = openLeaderboard(first, { "/api/leaderboard/?offset=10": second });
    await userEvent.click(await screen.findByRole("button", { name: "Show more" }));
    expect(await screen.findByText("Zed")).toBeInTheDocument();
    expect(bodyRows()).toHaveLength(11);
    expect(urls(fetch)).toContain("/api/leaderboard/?offset=10");
    expect(screen.queryByRole("button", { name: "Show more" })).not.toBeInTheDocument();
  });

  it("switches to a past season", async () => {
    const past = { ...http.leaderboard(), season: "Preseason", season_id: "7" };
    const fetch = openLeaderboard(seasonLeaderboard(), {
      "/api/seasons/": twoSeasons(),
      "/api/leaderboard/?season=7": past,
    });
    await screen.findByText("Season 1 · ranked after 10 games");
    await userEvent.click(await screen.findByRole("button", { name: /Season/ }));
    await userEvent.click(await screen.findByRole("option", { name: "Preseason" }));
    expect(await screen.findByText("Preseason · ranked after 10 games")).toBeInTheDocument();
    expect(urls(fetch)).toContain("/api/leaderboard/?season=7");
  });

  it("leaves the season picker out with only one season", async () => {
    openLeaderboard(seasonLeaderboard(), { "/api/seasons/": http.seasons() });
    await screen.findByText("Season 1 · ranked after 10 games");
    expect(screen.queryByRole("button", { name: /Season/ })).not.toBeInTheDocument();
  });

  it("says when the season asked for isn't there", async () => {
    openLeaderboard(seasonLeaderboard(), {}, "/leaderboard?season=99");
    expect(await screen.findByText("No such season")).toBeInTheDocument();
  });
});

function openProfile(id: string, answer: unknown, snap = me()) {
  const fetch = serveHttp({ [`/api/players/${id}/`]: answer });
  renderPage(<ProfilePage />, { snaps: { me: snap }, playerId: snap.player.id, route: `/players/${id}`, path: "/players/:id" });
  return fetch;
}

describe("Profile", () => {
  it("shows a player's season: rating, tier, record, awards, strikes and recent matches", async () => {
    openProfile("3", seasonProfile(), me({ linked: true, proven: true, verified: true, name: "P3Plays" }));
    expect(await screen.findByRole("heading", { name: "P3", level: 1 })).toBeInTheDocument();
    expect(screen.getByText("Steam verified")).toBeInTheDocument();
    expect(screen.getByText("Placed")).toBeInTheDocument();
    expect(screen.getAllByText("1,284").length).toBeGreaterThan(0);
    expect(screen.getByText("#6")).toBeInTheDocument();
    expect(screen.getByText("27–19")).toBeInTheDocument();
    expect(screen.getByText("6 · 11")).toBeInTheDocument();
    expect(screen.getByText("Next off in 2 clean matches")).toBeInTheDocument();
    expect(screen.getByText("8.2 / 5.1 / 9.9")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /^Rating went from .* to 1,284 over the last 10 matches$/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Recent matches" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Match 40" })).toHaveAttribute("href", "/matches/40");
    expect(screen.getByRole("heading", { name: "Most played" })).toBeInTheDocument();
  });

  it("shows your own accounts, with Steam to link", async () => {
    openProfile("3", http.profile());
    expect(await screen.findByRole("heading", { name: "Accounts" })).toBeInTheDocument();
    expect(screen.getByText("Not linked")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Link Steam" })).toHaveAttribute("href", "/link-steam");
    expect(screen.getByText("Placement · 1 / 10")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Placement matches" })).toBeInTheDocument();
  });

  it("shows a linked Steam account by name on your own profile", async () => {
    openProfile("3", seasonProfile(), me({ linked: true, proven: true, verified: false, name: "P3Plays" }));
    expect(await screen.findByText("P3Plays")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Link another Steam account" })).toBeInTheDocument();
  });

  it("leaves accounts off someone else's profile", async () => {
    const other = { ...seasonProfile(true), is_you: false, player: { id: "5", name: "P5", avatar_url: null } };
    openProfile("5", other);
    expect(await screen.findByRole("heading", { name: "P5", level: 1 })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Accounts" })).not.toBeInTheDocument();
    expect(screen.getByText("Steam verified")).toBeInTheDocument();
  });

  it("says whether they can captain", async () => {
    openProfile("3", seasonProfile());
    expect(await screen.findByText("Can captain")).toBeInTheDocument();
  });

  it("says why they can't captain yet", async () => {
    openProfile("3", { ...seasonProfile(), captain: { eligible: false, reason: "2/5 matches" } });
    expect(await screen.findByText("Can't captain yet · 2/5 matches")).toBeInTheDocument();
  });

  it("unlinks your Steam account after asking", async () => {
    const fetch = serveHttp({ "/api/players/3/": seasonProfile(), "/api/steam/unlink/": { unlinked: true } });
    const snap = me({ linked: true, proven: true, verified: false, name: "P3Plays" });
    renderPage(<ProfilePage />, { snaps: { me: snap }, playerId: snap.player.id, route: "/players/3", path: "/players/:id" });
    await userEvent.click(await screen.findByRole("button", { name: "Unlink Steam" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Unlink Steam?" });
    expect(within(dialog).getByText(/P3Plays comes off your profile/)).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Unlink" }));
    await vi.waitFor(() =>
      expect(fetch.mock.calls.some(([url, init]) => url === "/api/steam/unlink/" && init?.method === "POST")).toBe(true),
    );
  });

  it("has no Unlink without a linked Steam account", async () => {
    openProfile("3", http.profile());
    await screen.findByRole("heading", { name: "Accounts" });
    expect(screen.queryByRole("button", { name: "Unlink Steam" })).not.toBeInTheDocument();
  });

  it("says when there's no such player", async () => {
    openProfile("999", undefined);
    expect(await screen.findByText("Player not found")).toBeInTheDocument();
  });
});
