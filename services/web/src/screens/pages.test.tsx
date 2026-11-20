// The pages outside the match room, from Django's fixtures (completed.http-*.json and the live
// snapshots) with fetch stubbed and the live connection faked.
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { describe, expect, it, vi } from "vitest";

import type { MeSnap } from "../api/live";
import { shareCardUrl } from "../api/queries";
import type { Session } from "../api/session";
import { ReadyUpView } from "../app/notices/ReadyUp";
import { LiveStatus } from "../app/LiveStatus";
import { matchFixture } from "../match/fixtures";
import type { AnySnap, Topic } from "../live/types";
import { json, serveHttp } from "../test/http";
import { renderPage, SIGNED_IN } from "../test/render";
import { http, httpAnswers, live, PAGES_NOW } from "./fixtures";
import { LadderPage } from "./ladder/Ladder";
import { groupByDay, MatchesPage } from "./matches/Matches";
import { LinkSteamPage } from "./me/LinkSteam";
import { MePage } from "./me/Me";
import { ShareCardPage } from "./me/ShareCard";
import { PlayPage } from "./play/Play";
import { playState } from "./play/state";
import { REFUSALS, safeNext } from "./signin/refusals";
import { SignInPage } from "./signin/SignIn";
import { draftText, RandomDraftPage, ScrimsPage } from "./tools/Tools";
import { WelcomePage } from "./welcome/Welcome";

const PLAYER: Session = { ...SIGNED_IN, player: { id: "3", name: "P3", avatar: null, steam: [] } };

function snapsOf(me: MeSnap): Partial<Record<Topic, AnySnap>> {
  return { me, queue: live.queue(), live: live.live() };
}

function page(ui: ReactElement, options: { me?: MeSnap; route?: string; answers?: Record<string, unknown>; session?: Session | null } = {}) {
  const fetch = serveHttp(options.answers ?? httpAnswers());
  const me = options.me ?? live.meQueued();
  const result = renderPage(ui, {
    snaps: snapsOf(me),
    playerId: me.player.id,
    serverTime: PAGES_NOW,
    route: options.route ?? "/",
    session: options.session === undefined ? PLAYER : options.session,
  });
  return { ...result, fetch };
}

/** No element on the page addresses another player: profiles are private (D9). */
function expectNoProfileLinks() {
  for (const link of screen.queryAllByRole("link")) {
    const href = link.getAttribute("href") ?? "";
    expect(href).not.toMatch(/\/players\/|\/profile/);
  }
}

describe("sign in", () => {
  it("offers Discord and Steam, and the dev login only when the server says so", () => {
    page(<SignInPage />, { session: { signed_in: false, player: null, dev_login: true, invite_url: null }, route: "/signin?next=/ladder" });
    expect(screen.getByRole("link", { name: /Sign in with Discord/ })).toHaveAttribute("href", "/auth/discord/?next=%2Fladder");
    expect(screen.getByRole("link", { name: /Sign in with Steam/ })).toHaveAttribute("href", "/auth/steam/?next=%2Fladder&intent=login");
    expect(screen.getByRole("link", { name: /Dev login/ })).toBeInTheDocument();
  });

  it("explains every refusal in plain words, with the invite for not-member", () => {
    page(<SignInPage />, { session: { signed_in: false, player: null, dev_login: false, invite_url: "https://discord.gg/x" }, route: "/signin?error=not-member" });
    expect(screen.getByRole("heading", { level: 1, name: REFUSALS["not-member"].title })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open the server invite/ })).toHaveAttribute("href", "https://discord.gg/x");
    expect(screen.queryByText("not-member")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Dev login/ })).not.toBeInTheDocument();
  });

  it("has words for a code it doesn't know, and only goes back to this site", () => {
    page(<SignInPage />, { session: { signed_in: false, player: null, dev_login: false, invite_url: null }, route: "/signin?error=what" });
    expect(screen.getByRole("heading", { level: 1, name: "Sign-in didn't work" })).toBeInTheDocument();
    expect(safeNext("//evil.example")).toBe("/");
    expect(safeNext("/matches/3")).toBe("/matches/3");
  });

  it("says plainly when the session ran out", () => {
    page(<SignInPage />, { session: { signed_in: false, player: null, dev_login: false, invite_url: null }, route: "/signin?expired=1&next=/me" });
    expect(screen.getByRole("heading", { level: 1, name: "You've been signed out" })).toBeInTheDocument();
  });
});

describe("play", () => {
  it("shows your private place and leaves the queue", async () => {
    const { server } = page(<PlayPage />);
    expect(await screen.findByText("You're in the queue · your place")).toBeInTheDocument();
    expect(screen.getByText("1st")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Leave queue" }));
    await waitFor(() => expect(server.lastAct()).toMatchObject({ name: "queue.leave" }));
  });

  it("joins from the open queue", async () => {
    const me = live.meQueued();
    me.queue = { in_queue: false, position: null, joined_at: null, place: null };
    const { server } = page(<PlayPage />, { me });
    await userEvent.click(await screen.findByRole("button", { name: "Join the queue" }));
    await waitFor(() => expect(server.lastAct()).toMatchObject({ name: "queue.join" }));
  });

  it("holds a place with its clock, and shows a cooldown with its strikes", async () => {
    const me = live.meQueued();
    me.queue = { in_queue: false, position: null, joined_at: null, place: { position: 3, total: 9, held_until: "2026-01-05T19:39:00.000Z" } };
    expect(playState(me, live.queue(), Date.parse(PAGES_NOW))).toEqual({ kind: "held", until: "2026-01-05T19:39:00.000Z", position: 3 });
    const cooldown = live.meCooldown();
    if (cooldown.cooldown) cooldown.cooldown.until = "2026-01-05T19:50:00.000Z";
    page(<PlayPage />, { me: cooldown });
    expect(await screen.findByRole("heading", { name: /You can queue again at/ })).toBeInTheDocument();
    expect(screen.getByRole("timer")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Join the queue" })).toBeDisabled();
  });

  it("lets a held place go", async () => {
    const me = live.meQueued();
    me.queue = { in_queue: false, position: null, joined_at: null, place: { position: 3, total: 9, held_until: "2026-01-05T19:39:00.000Z" } };
    const { server } = page(<PlayPage />, { me });
    expect(await screen.findByRole("button", { name: "Rejoin and keep 3rd" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Let it go" }));
    await waitFor(() => expect(server.lastAct()).toMatchObject({ name: "queue.let_go" }));
  });

  it("shows how long each rung of the cooldown's ladder waits, and which was yours", async () => {
    const me = live.meCooldown();
    if (me.cooldown) Object.assign(me.cooldown, { until: "2026-01-05T19:50:00.000Z", ladder: [5, 15, 60, 1440], rung: 1 });
    page(<PlayPage />, { me });
    const ladder = (await screen.findByRole("heading", { name: "How long you wait" })).closest("section");
    if (!ladder) throw new Error("no ladder");
    const rows = within(ladder).getAllByRole("listitem").map((row) => row.textContent);
    expect(rows).toEqual(["No strikes5 minutes", "1 strike15 minutes · you", "2 strikesan hour","3 strikes or morea day"]);
    expect(within(ladder).getByText("1 strike").closest("li")).toHaveAttribute("aria-current", "true");
  });

  it("leaves the ladder out of a cooldown staff set", async () => {
    const me = live.meCooldown();
    if (me.cooldown) Object.assign(me.cooldown, { until: "2026-01-05T19:50:00.000Z", kind: "manual", ladder: [], rung: null });
    page(<PlayPage />, { me });
    await screen.findByRole("heading", { name: /You can queue again at/ });
    expect(screen.queryByRole("heading", { name: "How long you wait" })).not.toBeInTheDocument();
  });

  it("puts your match first, and the status chip says where you are", async () => {
    const me = live.meReady();
    page(
      <>
        <LiveStatus />
        <PlayPage />
      </>,
      { me },
    );
    expect(await screen.findByRole("link", { name: "Open the room" })).toHaveAttribute("href", `/matches/${me.match?.id}`);
    expect(screen.getByRole("link", { name: /No\. 1 · Ready check/ })).toBeInTheDocument();
  });
});

describe("Ready Up", () => {
  it("can't be dismissed with Esc, sends Ready, and Not this time says what it costs", async () => {
    const match = matchFixture("ready_check", "player");
    match.players = match.players.map((p) => (p.id === "1" ? { ...p, is_ready: false } : p));
    const skip = vi.fn();
    const { server } = renderPage(<ReadyUpView match={match} playerId="1" onSkip={skip} />, { snaps: {}, playerId: "1" });
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/a strike and a short cooldown/)).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Ready" }));
    await waitFor(() => expect(server.lastAct()).toMatchObject({ name: "lobby.ready", args: { match_id: match.id } }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Not this time" }));
    expect(skip).toHaveBeenCalled();
  });
});

describe("matches", () => {
  it("lists this season's matches by day and filters to yours", async () => {
    page(<MatchesPage />, { route: "/matches" });
    expect(await screen.findByRole("heading", { name: /Tonight/ })).toBeInTheDocument();
    const card = screen.getByRole("link", { name: /Match No\. 1/ });
    expect(card).toHaveAttribute("href", "/matches/1/summary");
    expect(within(card).getByText("You played")).toBeInTheDocument();
    expectNoProfileLinks();
  });

  it("groups by the viewer's calendar", () => {
    const rows = http.matches().matches;
    const now = Date.parse(PAGES_NOW);
    expect(groupByDay(rows, now)[0]?.title).toBe("Tonight");
    expect(groupByDay(rows, now + 3 * 24 * 3600_000)[0]?.title).toBe("Earlier this week");
  });

  it("says when there's nothing for the filter", async () => {
    const answers = httpAnswers();
    answers["/api/matches/?status=recent&mine=1"] = { matches: [], next_cursor: null };
    page(<MatchesPage />, { route: "/matches?show=mine", answers });
    expect(await screen.findByRole("heading", { name: "No matches of yours yet" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show all" })).toBeInTheDocument();
  });
});

describe("ladder", () => {
  it("highlights you, names everyone without linking anyone", async () => {
    page(<LadderPage />, { route: "/ladder" });
    const table = await screen.findByRole("table");
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(http.ladder().rows.length + 1);
    expect(within(table).getByText("you")).toBeInTheDocument();
    expect(within(table).queryAllByRole("link")).toHaveLength(0);
    expectNoProfileLinks();
  });

  it("pages with Show more", async () => {
    const answers = httpAnswers();
    const first = { ...http.ladder(), next_offset: 1 };
    const second = { ...http.ladder(), rows: http.ladder().rows.slice(0, 1).map((r) => ({ ...r, rank: 99, name: "Later", is_you: false })), next_offset: null };
    answers["/api/ladder/"] = first;
    answers["/api/ladder/?offset=1"] = second;
    page(<LadderPage />, { route: "/ladder", answers });
    await userEvent.click(await screen.findByRole("button", { name: "Show more" }));
    expect(await screen.findByText("Later")).toBeInTheDocument();
  });
});

describe("me", () => {
  it("is private, with rating, record, strikes, recent matches and accounts", async () => {
    page(<MePage />, { route: "/me" });
    expect(await screen.findByText("Only you see this")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "P3" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Strikes and penalties" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /No\. 1/ })).toHaveAttribute("href", "/matches/1/summary");
    expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument();
    expectNoProfileLinks();
  });

  it("unlinks Steam only after the confirmation", async () => {
    const answers = httpAnswers();
    const unlink = vi.fn(() => json({ steam: [] }));
    const steam = http.me().accounts.steam[0];
    answers[`/api/me/steam/${steam?.id}/unlink/`] = unlink;
    page(<LinkSteamPage />, { route: "/link-steam", answers });
    await userEvent.click(await screen.findByRole("button", { name: `Unlink ${steam?.name}` }));
    const dialog = await screen.findByRole("dialog");
    expect(unlink).not.toHaveBeenCalled();
    await userEvent.click(within(dialog).getByRole("button", { name: "Unlink Steam" }));
    await waitFor(() => expect(unlink).toHaveBeenCalled());
  });
});

describe("share card", () => {
  it("reloads the image when a toggle changes, and downloads it", async () => {
    page(<ShareCardPage />, { route: "/me/share" });
    const image = await screen.findByRole("img", { name: /Your share card/ });
    expect(image).toHaveAttribute("src", shareCardUrl({ rating: true, place: true, award: true }));
    await userEvent.click(screen.getByRole("checkbox", { name: /Ladder place/ }));
    expect(screen.getByRole("img", { name: /Your share card/ })).toHaveAttribute("src", "/api/me/share.png?rating=1&place=0&award=1");
    expect(screen.getByRole("link", { name: "Download PNG" })).toHaveAttribute("download");
  });

  it("hides Copy image where the browser can't copy images", async () => {
    page(<ShareCardPage />, { route: "/me/share" });
    await screen.findByRole("img", { name: /Your share card/ });
    expect(screen.queryByRole("button", { name: "Copy image" })).not.toBeInTheDocument();
  });
});

describe("tools", () => {
  it("rolls a random draft, again, and copies it", async () => {
    page(<RandomDraftPage />, { route: "/tools/random-draft" });
    await userEvent.click(screen.getByRole("button", { name: "Roll a draft" }));
    expect(await screen.findByRole("heading", { name: "The Hidden King" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Again" })).toBeInTheDocument();
    expect(draftText(http.randomDraft())).toMatch(/^DayShift random draft\nThe Hidden King: bans .+; picks .+\nThe Archmother: /);
  });

  it("scrims are staff's: explained, with nothing live", async () => {
    page(<ScrimsPage />, { route: "/tools/scrims" });
    expect(await screen.findByRole("heading", { name: "No scrims right now" })).toBeInTheDocument();
  });
});

describe("a first night", () => {
  it("shows each page's empty state and the one thing to do", async () => {
    page(<WelcomePage />, { route: "/welcome" });
    expect(screen.getByRole("heading", { level: 1, name: "Your first night" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Link Steam/ })).toHaveAttribute("href", "/link-steam");
    await act(async () => {
      await Promise.resolve();
    });
    expectNoProfileLinks();
  });
});
