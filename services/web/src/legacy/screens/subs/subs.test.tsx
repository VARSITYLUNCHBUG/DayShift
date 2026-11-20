// M8 screens, from the fixtures: requesting, naming and approving subs, the offers, the paused
// match, early leaves, and the toasts derived from snapshot changes.
import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { notify } from "../../components/toast";
import { fixture, inMatchMe, SEARCH_RESULTS, subOptions } from "../../dev/fixtures";
import type { AckScript } from "../../../live/FakeServer";
import type { MatchSnap, MeSnap } from "../../../live/types";
import { renderPage } from "../../../test/render";
import { MatchRoute } from "../match/MatchRoute";
import { resetMatchToasts } from "../match/useMatchToasts";
import { PlayPage } from "../play/Play";
import { MeToasts } from "../useMeToasts";
import { OfferDialog } from "./OfferDialog";
import { markAcceptedHere, resetAcceptedHere } from "./subs";

type Answer = (name: string, args: Record<string, unknown>) => AckScript;

function open(match: MatchSnap, me: MeSnap, answer?: Answer) {
  return renderPage(<MatchRoute />, {
    snaps: { me, [`match:${match.id}`]: match },
    playerId: me.player.id,
    route: `/matches/${match.id}`,
    path: "/matches/:id",
    answer,
  });
}

const view = (scenario: string, who: "captain" | "player" | "spectator") =>
  [fixture.match(scenario, who), fixture.me(scenario, who)] as const;

async function sent(server: { lastAct: () => unknown }, name: string, args: Record<string, unknown>) {
  await vi.waitFor(() => expect(server.lastAct()).toMatchObject({ name, args }));
}

beforeEach(() => {
  for (const kind of ["error", "success", "info", "warning"] as const) {
    vi.spyOn(notify, kind).mockImplementation(() => "");
  }
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  resetMatchToasts();
  resetAcceptedHere();
});

describe("Request a sub", () => {
  it("lets a player sub themself out, warns it's a dodge, then asks who's subbing in", async () => {
    const [match, me] = view("player_draft", "player");
    const naming = fixture.match("player_draft_sub_naming", "captain");
    const line = { ...naming.subs[0]!, leaving_id: me.player.id, leaving_name: me.player.name, requested_by_id: me.player.id, is_self: true };
    let server: ReturnType<typeof open>["server"] | null = null;
    const answer: Answer = (name) => {
      if (name === "subs.options") return { ok: true, result: subOptions(match, me.player.id) };
      // The server sends the fresh snapshot before the ack.
      server?.snap(`match:${match.id}`, { ...match, on_hold: true, subs: [line], viewer: { ...match.viewer, can_request_sub: false } });
      return { ok: true, result: { request_id: line.id } };
    };
    server = open(match, me, answer).server;
    await userEvent.click(await screen.findByRole("button", { name: "Request a sub" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("heading", { name: "Request a sub" })).toBeInTheDocument();
    expect(await within(dialog).findByText("Dodge · +2 strikes")).toBeInTheDocument();
    // Not a captain: no teammates to sub out.
    expect(within(dialog).getByRole("button", { name: /Sub out a teammate/ })).toBeDisabled();
    await userEvent.click(within(dialog).getByRole("button", { name: "Request" }));
    await sent(server, "subs.request", { match_id: "1", player_id: me.player.id });
    expect(await screen.findByRole("heading", { name: "Who's subbing in?" })).toBeInTheDocument();
  });

  it("lets a captain sub out a teammate", async () => {
    const [match, me] = view("in_progress", "captain");
    const answer: Answer = (name) =>
      name === "subs.options" ? { ok: true, result: subOptions(match, me.player.id) } : { ok: true, result: { request_id: "9" } };
    const { server } = open(match, me, answer);
    await userEvent.click(await screen.findByRole("button", { name: "Request a sub" }));
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText("Leaving a game · +2 strikes")).toBeInTheDocument();
    expect(within(dialog).getByText("Captains only · P1 approves")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: /Sub out a teammate/ }));
    await userEvent.click(within(dialog).getByRole("button", { name: /Choose a player/ }));
    await userEvent.click(await screen.findByRole("option", { name: "P3" }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Request" }));
    await sent(server, "subs.request", { match_id: "1", player_id: "3" });
  });

  it("shows the refusal when options can't be had", async () => {
    const [match, me] = view("in_progress", "player");
    open(match, me, () => ({ ok: false, error: "You've already asked for a sub." }));
    await userEvent.click(await screen.findByRole("button", { name: "Request a sub" }));
    expect(await screen.findByText("You've already asked for a sub.")).toBeInTheDocument();
  });

  it("isn't offered to spectators", async () => {
    open(...view("in_progress", "spectator"));
    await screen.findByText("No. 1");
    expect(screen.queryByRole("button", { name: "Request a sub" })).not.toBeInTheDocument();
  });
});

describe("Name a sub", () => {
  function searching() {
    const fetch = vi.fn(() => Promise.resolve(new Response(JSON.stringify({ players: SEARCH_RESULTS }), { status: 200 })));
    vi.stubGlobal("fetch", fetch);
    return fetch;
  }

  it("finds players to invite, leaving out those who can't sub in", async () => {
    const fetch = searching();
    const { server } = open(...view("player_draft_sub_naming", "captain"));
    const notice = await screen.findByRole("region", { name: "Paused" });
    expect(notice).toHaveTextContent("P3 is subbing out");
    expect(notice).toHaveTextContent("Name a sub, or the queue is asked");
    await userEvent.click(within(notice).getByRole("button", { name: "Name a sub" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByRole("searchbox", { name: "Find a player" }), "p1");
    const list = await within(dialog).findByRole("list", { name: "Players" });
    expect(fetch).toHaveBeenCalledWith("/api/players/search/?q=p1", expect.anything());
    expect(within(list).getByText("In queue · 1,250")).toBeInTheDocument();
    expect(within(list).getByText("In a match")).toBeInTheDocument();
    expect(within(list).getByText("On cooldown")).toBeInTheDocument();
    expect(within(list).getAllByRole("button", { name: /^Invite/ })).toHaveLength(2);
    await userEvent.click(within(list).getByRole("button", { name: "Invite P14" }));
    await sent(server, "subs.invite", { request_id: "1", player_id: "14" });
    expect(notify.success).toHaveBeenCalledWith("Asked P14", "To sub in for P3");
  });

  it("doesn't search under two letters", async () => {
    const fetch = searching();
    open(...view("player_draft_sub_naming", "captain"));
    await userEvent.click(await screen.findByRole("button", { name: "Name a sub" }));
    await userEvent.type(await screen.findByRole("searchbox", { name: "Find a player" }), "p");
    await new Promise((resolve) => setTimeout(resolve, 400));
    expect(fetch).not.toHaveBeenCalled();
  });

  it("can hand the spot to the queue", async () => {
    searching();
    const { server } = open(...view("player_draft_sub_naming", "captain"));
    await userEvent.click(await screen.findByRole("button", { name: "Name a sub" }));
    await userEvent.click(await screen.findByRole("button", { name: "Offer to the queue" }));
    await sent(server, "subs.offer_queue", { request_id: "1" });
  });

  it("lets whoever asked cancel", async () => {
    const { server } = open(...view("player_draft_sub_naming", "captain"));
    await userEvent.click(await screen.findByRole("button", { name: "Cancel request" }));
    await sent(server, "subs.cancel", { request_id: "1" });
  });
});

describe("Approve sub out", () => {
  it("lets the other captain approve or refuse", async () => {
    const { server } = open(...view("player_draft_sub_approval", "captain"));
    expect(await screen.findByRole("heading", { name: "P2 wants to sub out P3" })).toBeInTheDocument();
    expect(screen.getByText("Match 1 · Sub out")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Paused" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Refuse" }));
    await sent(server, "subs.answer_request", { request_id: "1", approve: false });
    await userEvent.click(screen.getByRole("button", { name: "Approve" }));
    await sent(server, "subs.answer_request", { request_id: "1", approve: true });
  });

  it("shows everyone else the match is paused for it", async () => {
    open(...view("player_draft_sub_approval", "player"));
    const notice = await screen.findByRole("region", { name: "Paused" });
    expect(notice).toHaveTextContent("P3 is subbing out");
    expect(notice).toHaveTextContent("Waiting for P1 to approve");
    expect(within(notice).queryByRole("button")).not.toBeInTheDocument();
  });
});

describe("Match paused", () => {
  it("shows the one leaving who's been asked, and lets them cancel", async () => {
    const { server } = open(...view("in_progress_sub_offered", "player"));
    const notice = await screen.findByRole("region", { name: "Paused" });
    expect(notice).toHaveTextContent("Waiting for P13");
    expect(within(notice).getByRole("timer")).toBeInTheDocument();
    expect(within(notice).queryByRole("button", { name: "Name a sub" })).not.toBeInTheDocument();
    await userEvent.click(within(notice).getByRole("button", { name: "Cancel request" }));
    await sent(server, "subs.cancel", { request_id: "1" });
  });

  it("shows a refilled ready check seat as joined", async () => {
    open(...view("ready_check_refill", "player"));
    expect(await screen.findByRole("heading", { name: "Need 1 Sub" })).toBeInTheDocument();
    expect(screen.getByText("P12 missed the ready check")).toBeInTheDocument();
    expect(screen.getByText("Joined")).toBeInTheDocument();
    expect(screen.getByText("Waiting on response from")).toHaveTextContent("P14");
    expect(screen.queryByRole("region", { name: "Paused" })).not.toBeInTheDocument();
  });
});

describe("Offers", () => {
  function offered(scenario: string, answer?: Answer) {
    const me = fixture.me(scenario, "spectator");
    return renderPage(
      <Routes>
        <Route path="/" element={<OfferDialog />} />
        <Route path="/matches/:id" element={<p>Match page</p>} />
      </Routes>,
      { snaps: { me }, playerId: me.player.id, answer },
    );
  }

  it("shows an invite on any page, and accepting opens the match", async () => {
    const { server } = offered("player_draft_sub_open");
    const dialog = await screen.findByRole("dialog", { name: "Sub invite" });
    expect(within(dialog).getByRole("heading", { name: "P3 wants you to sub in" })).toBeInTheDocument();
    expect(dialog).toHaveTextContent("Match 1");
    expect(dialog).toHaveTextContent("Player draft");
    await userEvent.click(within(dialog).getByRole("button", { name: "Accept" }));
    await sent(server, "subs.answer_offer", { offer_id: "1", accept: true });
    expect(await screen.findByText("Match page")).toBeInTheDocument();
  });

  it("offers a spot from the queue, which can be turned down", async () => {
    const { server } = offered("in_progress_sub_offered");
    const dialog = await screen.findByRole("dialog", { name: "Spot offered" });
    expect(within(dialog).getByRole("heading", { name: "A spot opened" })).toBeInTheDocument();
    expect(dialog).toHaveTextContent("You're next in line");
    expect(dialog).toHaveTextContent("P2's Team");
    expect(dialog).toHaveTextContent(/In game · \d+:\d\d/);
    await userEvent.click(within(dialog).getByRole("button", { name: "Can't right now" }));
    await sent(server, "subs.answer_offer", { offer_id: "1", accept: false });
  });

  it("shows a refusal in the dialog", async () => {
    offered("player_draft_sub_open", () => ({ ok: false, error: "Too late: that spot has been filled or closed." }));
    await userEvent.click(await screen.findByRole("button", { name: "Accept" }));
    expect(await screen.findByText("Too late: that spot has been filled or closed.")).toBeInTheDocument();
    expect(screen.queryByText("Match page")).not.toBeInTheDocument();
  });
});

describe("Early leave", () => {
  it("lets a captain report who left", async () => {
    const { server } = open(...view("in_progress", "captain"));
    await userEvent.click(await screen.findByRole("button", { name: "Someone left early" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("heading", { name: "Who left in the first 5 min?" })).toBeInTheDocument();
    expect(within(dialog).getByText("P1 confirms · voids the match")).toBeInTheDocument();
    const report = within(dialog).getByRole("button", { name: "Report" });
    expect(report).toBeDisabled();
    await userEvent.click(within(within(dialog).getByRole("group", { name: "P1's Team" })).getByRole("button", { name: "P4" }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Report P4" }));
    await sent(server, "early_leave.report", { match_id: "1", player_id: "4" });
  });

  it("isn't offered to players who aren't captains", async () => {
    open(...view("in_progress", "player"));
    await screen.findByText("No. 1");
    expect(screen.queryByRole("button", { name: "Someone left early" })).not.toBeInTheDocument();
  });

  it("lets the other captain agree or disagree", async () => {
    const { server } = open(...view("in_progress_early_leave", "captain"));
    expect(await screen.findByRole("heading", { name: "P2 says P3 left" })).toBeInTheDocument();
    expect(screen.getByText("Agree to void with no rating change.")).toBeInTheDocument();
    // A report is waiting: no second one.
    expect(screen.queryByRole("button", { name: "Someone left early" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Disagree" }));
    await sent(server, "early_leave.answer", { match_id: "1", agree: false });
    await userEvent.click(screen.getByRole("button", { name: "Agree" }));
    await sent(server, "early_leave.answer", { match_id: "1", agree: true });
  });

  it("tells everyone else who it waits on", async () => {
    open(...view("in_progress_early_leave", "player"));
    const notice = await screen.findByRole("region", { name: "Early leave" });
    expect(notice).toHaveTextContent("P2 says P3 left");
    expect(notice).toHaveTextContent("Waiting for P1");
  });
});

describe("Match toasts", () => {
  it("says when a sub came in, once", async () => {
    const [match, me] = view("in_progress_sub_offered", "captain");
    const { server } = open(match, me);
    await screen.findByRole("region", { name: "Paused" });
    const line = match.subs[0]!;
    const done = {
      id: line.id,
      status: "filled" as const,
      reason: line.reason,
      leaving_id: line.leaving_id ?? "3",
      leaving_name: line.leaving_name,
      team: line.team,
      joined_id: "13",
      joined_name: "P13",
    };
    const next = { ...match, subs: [], subs_done: [done], on_hold: false };
    act(() => server.snap(`match:${match.id}`, next));
    await vi.waitFor(() => expect(notify.success).toHaveBeenCalledWith("Sub found", "P13 is in for P3"));
    act(() => server.snap(`match:${match.id}`, { ...next, deadline_at: "2026-01-05T19:20:00.000Z" }));
    expect(notify.success).toHaveBeenCalledTimes(1);
  });

  it("says when the other captain refused a sub", async () => {
    const [match, me] = view("player_draft_sub_approval", "player");
    const { server } = open(match, me);
    await screen.findByRole("region", { name: "Paused" });
    const line = match.subs[0]!;
    const done = {
      id: line.id,
      status: "rejected" as const,
      reason: line.reason,
      leaving_id: line.leaving_id ?? "3",
      leaving_name: line.leaving_name,
      team: line.team,
      joined_id: null,
      joined_name: null,
    };
    act(() => server.snap(`match:${match.id}`, { ...match, subs: [], subs_done: [done], on_hold: false }));
    await vi.waitFor(() => expect(notify.warning).toHaveBeenCalledWith("Sub refused", "P3 stays in"));
  });

  it("says how an early leave was answered", async () => {
    const [match, me] = view("in_progress_early_leave", "player");
    const { server } = open(match, me);
    await screen.findByRole("region", { name: "Early leave" });
    act(() => server.snap(`match:${match.id}`, { ...match, early_leave: { ...match.early_leave, pending: null } }));
    await vi.waitFor(() => expect(notify.warning).toHaveBeenCalledWith("Early leave not agreed", "Staff will decide"));
  });

  it("says when an early leave voided the match", async () => {
    const [match, me] = view("in_progress_early_leave", "player");
    const { server } = open(match, me);
    await screen.findByRole("region", { name: "Early leave" });
    const voided = fixture.match("voided_ready_check", "player");
    act(() => server.snap(`match:${match.id}`, { ...match, status: "voided", result: voided.result, early_leave: { ...match.early_leave, pending: null } }));
    await vi.waitFor(() =>
      expect(notify.success).toHaveBeenCalledWith("Early leave agreed", "Match cancelled with no rating change"),
    );
  });
});

describe("Your own toasts", () => {
  function watch(me: MeSnap) {
    return renderPage(<MeToasts />, { snaps: { me }, playerId: me.player.id });
  }

  it("says you're in when your offer was taken up", async () => {
    const me = fixture.me("player_draft_sub_open", "spectator");
    const { server } = watch(me);
    await new Promise((resolve) => setTimeout(resolve, 20));
    act(() =>
      server.snap("me", {
        ...me,
        offers: [],
        match: { id: "1", status: "player_draft", kind: "ranked", team: "A", is_captain: false },
        last_offer: { id: "1", match_id: "1", status: "accepted", team_name: "P2's Team" },
      }),
    );
    await vi.waitFor(() =>
      expect(notify.success).toHaveBeenCalledWith("You're in", "Match 1 · P2's Team", expect.objectContaining({ label: "Open" })),
    );
  });

  it("leaves out Open when you accepted on this page", async () => {
    const me = fixture.me("in_progress_sub_offered", "spectator");
    const offer = me.offers[0];
    if (!offer) throw new Error("The fixture has an offer.");
    const { server } = watch(me);
    await new Promise((resolve) => setTimeout(resolve, 20));
    markAcceptedHere(offer.id);
    act(() =>
      server.snap("me", {
        ...me,
        offers: [],
        match: { id: offer.match_id, status: "in_progress", kind: "ranked", team: "A", is_captain: false },
        last_offer: { id: offer.id, match_id: offer.match_id, status: "accepted", team_name: "P2's Team" },
      }),
    );
    await vi.waitFor(() =>
      expect(notify.success).toHaveBeenCalledWith("You're in", `Match ${offer.match_id} · P2's Team`),
    );
  });

  it("says when an offer ran out", async () => {
    const me = fixture.me("in_progress_sub_offered", "spectator");
    const { server } = watch(me);
    await new Promise((resolve) => setTimeout(resolve, 20));
    act(() => server.snap("me", { ...me, offers: [], last_offer: { id: "1", match_id: "1", status: "expired", team_name: "P2's Team" } }));
    await vi.waitFor(() => expect(notify.warning).toHaveBeenCalledWith("Offer expired", "Match 1"));
  });

  it("says nothing when you declined", async () => {
    const me = fixture.me("in_progress_sub_offered", "spectator");
    const { server } = watch(me);
    await new Promise((resolve) => setTimeout(resolve, 20));
    act(() => server.snap("me", { ...me, offers: [], last_offer: { id: "1", match_id: "1", status: "declined", team_name: null } }));
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(notify.success).not.toHaveBeenCalled();
    expect(notify.warning).not.toHaveBeenCalled();
    expect(notify.info).not.toHaveBeenCalled();
  });

  it("says when a strike comes off", async () => {
    const me = fixture.me("voided_ready_check", "spectator");
    const { server } = watch(me);
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(me.strikes).toBe(1);
    act(() => server.snap("me", { ...me, cooldown: null, strikes: 0 }));
    await vi.waitFor(() => expect(notify.success).toHaveBeenCalledWith("Strike removed", "No strikes left"));
  });
});

describe("Play while in a match", () => {
  it("shows your match instead of the queue", async () => {
    const me = inMatchMe();
    renderPage(<PlayPage />, {
      snaps: { me, queue: fixture.queue("player_draft"), live: fixture.live("player_draft") },
      playerId: me.player.id,
    });
    expect(await screen.findByRole("heading", { name: "Match 1 · Player draft" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open match" })).toHaveAttribute("href", "/matches/1");
    expect(screen.queryByRole("button", { name: "Join queue" })).not.toBeInTheDocument();
  });
});
