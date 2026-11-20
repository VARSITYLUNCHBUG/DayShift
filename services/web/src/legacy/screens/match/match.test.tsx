import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { fixture, has, needSubMatch, SCENARIOS, VIEWS } from "../../dev/fixtures";
import type { MatchSnap, MeSnap } from "../../../live/types";
import { serveHttp } from "../../../test/http";
import { renderPage } from "../../../test/render";
import { MatchRoute } from "./MatchRoute";
import { MATCH_SCREENS } from "./screens";

function open(match: MatchSnap, me: MeSnap) {
  return renderPage(<MatchRoute />, {
    snaps: { me, [`match:${match.id}`]: match },
    playerId: me.player.id,
    route: `/matches/${match.id}`,
    path: "/matches/:id",
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("MatchRoute", () => {
  it.each(
    SCENARIOS.flatMap((scenario) =>
      VIEWS.filter((view) => has(`${scenario}.${view}`) && has(`${scenario}.me-${view}`)).map((view) => [scenario, view] as const),
    ),
  )("renders %s for the %s", async (scenario, view) => {
    const match = fixture.match(scenario, view);
    open(match, fixture.me(scenario, view));
    expect(await screen.findByText(`No. ${match.id}`)).toBeInTheDocument();
    expect(MATCH_SCREENS[match.status]).toBeDefined();
  });

  it("says when the match isn't there, live or on record", async () => {
    serveHttp({});
    renderPage(<MatchRoute />, { route: "/matches/404", path: "/matches/:id" });
    expect(await screen.findByText("Match not found")).toBeInTheDocument();
  });

  it("doesn't ask the server about ids that can't be matches", async () => {
    const { server } = renderPage(<MatchRoute />, { route: "/matches/abc", path: "/matches/:id" });
    expect(await screen.findByText("Match not found")).toBeInTheDocument();
    expect(server.received.some((m) => m.t === "sub" && m.topics.some((t) => t.startsWith("match:")))).toBe(false);
  });
});

describe("Ready check", () => {
  it("lets a player who hasn't readied up ready", async () => {
    const me = fixture.me("ready_check", "player");
    const base = fixture.match("ready_check", "player");
    const match = { ...base, players: base.players.map((p) => (p.id === me.player.id ? { ...p, is_ready: false } : p)) };
    const { server } = open(match, me);
    expect(await screen.findByRole("heading", { name: "Match found" })).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: /^2:4[01] left$/ })).toBeInTheDocument();
    expect(screen.getByText("6 / 12")).toBeInTheDocument();

    const players = screen.getByRole("list", { name: "Players" });
    expect(within(players).getAllByRole("img", { name: "Ready" })).toHaveLength(6);

    await userEvent.click(screen.getByRole("button", { name: "Ready" }));
    await vi.waitFor(() => expect(server.lastAct()).toMatchObject({ name: "lobby.ready", args: { match_id: "1" } }));
  });

  it("shows a player who has readied that they're ready", async () => {
    open(fixture.match("ready_check", "player"), fixture.me("ready_check", "player"));
    await screen.findByRole("heading", { name: "Match found" });
    await vi.waitFor(() =>
      expect(screen.getAllByRole("status").map((el) => el.textContent)).toContain("Ready"),
    );
    expect(screen.queryByRole("button", { name: "Ready" })).not.toBeInTheDocument();
  });

  it("has no Ready button for spectators", async () => {
    open(fixture.match("ready_check", "spectator"), fixture.me("ready_check", "spectator"));
    expect(await screen.findByRole("heading", { name: "Ready check" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Ready" })).not.toBeInTheDocument();
  });

  it("shows the seats being refilled when the check closed short", async () => {
    open(needSubMatch(), fixture.me("ready_check", "player"));
    expect(await screen.findByRole("heading", { name: "Need 1 Sub" })).toBeInTheDocument();
    expect(screen.getByText("P9 missed the ready check")).toBeInTheDocument();
    expect(screen.getByText("P13")).toBeInTheDocument();
    expect(screen.getByText("11 / 12 ready")).toBeInTheDocument();
    expect(screen.getByText(/^1:4[78]$/)).toBeInTheDocument();
  });
});
