// The Ready Up pop-up, Link Steam and the signed-in gate.
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router";
import { describe, expect, it, vi } from "vitest";

import { fixture } from "../dev/fixtures";
import type { MatchSnap, MeSnap } from "../../live/types";
import { SignedIn } from "../../app/SignedIn";
import { renderPage } from "../../test/render";
import { LinkSteamView } from "./LinkSteam";
import { ReadyUpDialog } from "./ReadyUpDialog";

function readyCheck(): { me: MeSnap; match: MatchSnap } {
  const me = fixture.me("ready_check", "player");
  const base = fixture.match("ready_check", "player");
  const match = { ...base, players: base.players.map((p) => (p.id === me.player.id ? { ...p, is_ready: false } : p)) };
  return { me, match };
}

describe("Ready Up pop-up", () => {
  it("pops up anywhere when your match's ready check is waiting on you", async () => {
    const { me, match } = readyCheck();
    const { server } = renderPage(<ReadyUpDialog />, {
      snaps: { me, "match:1": match },
      playerId: me.player.id,
      route: "/leaderboard",
    });
    const dialog = await screen.findByRole("dialog", { name: "Ready Up" });
    expect(dialog).toHaveTextContent("Match 1");
    expect(dialog).toHaveTextContent("6 / 12 ready");
    await userEvent.click(screen.getByRole("button", { name: "Ready" }));
    await vi.waitFor(() => expect(server.lastAct()).toMatchObject({ name: "lobby.ready", args: { match_id: "1" } }));
  });

  it("stays away once you're ready", async () => {
    const me = fixture.me("ready_check", "player");
    renderPage(<ReadyUpDialog />, { snaps: { me, "match:1": fixture.match("ready_check", "player") }, playerId: me.player.id });
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("stays away on the match's own page", async () => {
    const { me, match } = readyCheck();
    const { server } = renderPage(<ReadyUpDialog />, {
      snaps: { me, "match:1": match },
      playerId: me.player.id,
      route: "/matches/1",
    });
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(server.received.some((m) => m.t === "sub" && m.topics.includes("match:1"))).toBe(false);
  });
});

describe("Link Steam", () => {
  it("says which Discord account Steam links to, and goes to Steam", () => {
    const me = fixture.me("completed", "player");
    renderPage(<LinkSteamView player={me.player} />, { live: false });
    expect(screen.getByRole("heading", { name: "Link Steam" })).toBeInTheDocument();
    expect(screen.getByText(me.player.name, { selector: "b" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Link" })).toHaveAttribute(
      "href",
      "/auth/steam/?intent=link&next=%2Flink-steam",
    );
    expect(screen.getByRole("link", { name: "Cancel" })).toHaveAttribute("href", "/");
  });
});

describe("Signed-in pages", () => {
  it("send a signed-out player to sign in, and back afterwards", async () => {
    renderPage(
      <Routes>
        <Route path="/signin" element={<p>sign-in page</p>} />
        <Route element={<SignedIn />}>
          <Route path="/leaderboard" element={<p>leaderboard</p>} />
        </Route>
      </Routes>,
      {
        live: false,
        route: "/leaderboard",
        session: { signed_in: false, player: null, dev_login: false, invite_url: null },
      },
    );
    expect(await screen.findByText("sign-in page")).toBeInTheDocument();
  });
});
