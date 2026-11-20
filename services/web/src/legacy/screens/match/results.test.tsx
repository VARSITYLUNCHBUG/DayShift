// M7 screens, from the fixtures: reporting (over HTTP, with fetch mocked), confirming,
// disputing, matching scoreboard names, and the finished match.
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { notify } from "../../components/toast";
import { fixture } from "../../dev/fixtures";
import { signed } from "../../lib/format";
import type { AckScript } from "../../../live/FakeServer";
import type { MatchSnap, MeSnap } from "../../../live/types";
import { renderPage } from "../../../test/render";
import { MatchRoute } from "./MatchRoute";

function open(match: MatchSnap, me: MeSnap, answer?: (name: string, args: Record<string, unknown>) => AckScript) {
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

async function sent(server: ReturnType<typeof open>["server"], name: string, args: Record<string, unknown>) {
  await vi.waitFor(() => expect(server.lastAct()).toMatchObject({ name, args }));
}

const PNG = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

function screenshot(bytes: BlobPart = PNG, name = "scoreboard.png", type = "image/png") {
  return new File([bytes], name, { type });
}

function answer(status: number, body: unknown) {
  return vi.fn(() => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } })));
}

beforeEach(() => {
  vi.spyOn(notify, "error").mockImplementation(() => "");
  vi.spyOn(notify, "success").mockImplementation(() => "");
  document.cookie = "csrftoken=token-123";
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

/** The open Report dialog, a winner chosen and a screenshot added. */
async function fillReport(file = screenshot()) {
  await userEvent.click(await screen.findByRole("button", { name: "Report result" }));
  const dialog = await screen.findByRole("dialog");
  await userEvent.click(within(dialog).getByRole("button", { name: /P2's Team/ }));
  const input = dialog.querySelector<HTMLInputElement>('input[type="file"]');
  expect(input).not.toBeNull();
  await userEvent.upload(input!, file);
  return dialog;
}

describe("Report result", () => {
  it("is only for captains", async () => {
    open(...view("in_progress", "player"));
    expect(await screen.findByText("In game")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Report result" })).not.toBeInTheDocument();
  });

  it("sends the winner, the screenshot and the extras, then closes", async () => {
    const fetch = answer(200, { status: "awaiting_confirmation" });
    vi.stubGlobal("fetch", fetch);
    open(...view("in_progress", "captain"));
    const dialog = await fillReport();
    expect(within(dialog).getByText("scoreboard.png")).toBeInTheDocument();
    await userEvent.type(within(dialog).getByRole("textbox", { name: /Deadlock match ID/ }), "38211457");
    await userEvent.click(within(dialog).getByRole("button", { name: "P3" }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Submit" }));

    await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/matches/1/report/");
    expect(init.method).toBe("POST");
    expect(init.headers).toMatchObject({ "X-CSRFToken": "token-123" });
    const form = init.body as FormData;
    expect(form.get("winner")).toBe("A");
    expect((form.get("image") as File).name).toBe("scoreboard.png");
    expect(form.get("deadlock_match_id")).toBe("38211457");
    expect(form.getAll("key")).toEqual(["3"]);
    expect(form.get("mvp")).toBeNull();
    await vi.waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(notify.success).toHaveBeenCalledWith("Thanks: the other captain can now confirm or dispute.");
  });

  it("shows the server's refusal in the dialog", async () => {
    vi.stubGlobal("fetch", answer(400, { error: "This match isn't waiting for a result." }));
    open(...view("in_progress", "captain"));
    const dialog = await fillReport();
    await userEvent.click(within(dialog).getByRole("button", { name: "Submit" }));
    expect(await within(dialog).findByText("This match isn't waiting for a result.")).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("says when Discord didn't take it", async () => {
    vi.stubGlobal("fetch", answer(502, { error: "Couldn't send the screenshot to Discord. Try again in a moment." }));
    open(...view("in_progress", "captain"));
    const dialog = await fillReport();
    await userEvent.click(within(dialog).getByRole("button", { name: "Submit" }));
    expect(await within(dialog).findByText(/Couldn't send the screenshot to Discord/)).toBeInTheDocument();
  });

  it("won't send a file over 20 MB", async () => {
    const fetch = answer(200, { status: "awaiting_confirmation" });
    vi.stubGlobal("fetch", fetch);
    open(...view("in_progress", "captain"));
    const big = screenshot(new Uint8Array(20 * 1024 * 1024 + 1));
    const dialog = await fillReport(big);
    expect(within(dialog).getByText("That file is too large: the limit is 20 MB.")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Submit" })).toBeDisabled();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("needs a winner and a screenshot", async () => {
    open(...view("in_progress", "captain"));
    await userEvent.click(await screen.findByRole("button", { name: "Report result" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("button", { name: "Submit" })).toBeDisabled();
    await userEvent.click(within(dialog).getByRole("button", { name: /P1's Team/ }));
    expect(within(dialog).getByRole("button", { name: "Submit" })).toBeDisabled();
  });
});

describe("Confirm result", () => {
  it("lets the other captain confirm", async () => {
    const { server } = open(...view("awaiting_confirmation", "captain"));
    expect(await screen.findByRole("heading", { name: "Confirm result" })).toBeInTheDocument();
    expect(screen.getByText("P2 reported")).toBeInTheDocument();
    expect(screen.getByText("P2's Team won")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await sent(server, "results.confirm", { match_id: "1" });
  });

  it("lets the other captain dispute, with a note", async () => {
    const { server } = open(...view("awaiting_confirmation", "captain"));
    await userEvent.click(await screen.findByRole("button", { name: "Dispute" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByRole("heading", { name: "Dispute result" })).toBeInTheDocument();
    await userEvent.type(within(dialog).getByRole("textbox", { name: "What happened?" }), "  We took the last base.  ");
    await userEvent.click(within(dialog).getByRole("button", { name: "Dispute" }));
    await sent(server, "results.dispute", { match_id: "1", note: "We took the last base." });
    await vi.waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
  });

  it("keeps the dialog open with the refusal", async () => {
    open(...view("awaiting_confirmation", "captain"), () => ({ ok: false, error: "There's nothing to dispute." }));
    await userEvent.click(await screen.findByRole("button", { name: "Dispute" }));
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Dispute" }));
    expect(await within(dialog).findByText("There's nothing to dispute.")).toBeInTheDocument();
  });

  it("lets the other captain add their own screenshot", async () => {
    open(...view("awaiting_confirmation", "captain"));
    await userEvent.click(await screen.findByRole("button", { name: "Add a screenshot" }));
    expect(await screen.findByRole("heading", { name: "Report result" })).toBeInTheDocument();
  });

  it.each(["player", "spectator"] as const)("shows the %s who it's waiting for", async (who) => {
    const [match, me] = view("awaiting_confirmation", who);
    const other = match.players.find((p) => p.is_captain && p.id !== match.result.reported_by_id);
    open(match, me);
    expect(await screen.findByRole("heading", { name: `Waiting for ${other?.name} to confirm` })).toBeInTheDocument();
    expect(screen.getByRole("timer")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Confirm" })).not.toBeInTheDocument();
  });

  it("shows the captain who reported that they're waiting too", async () => {
    const [match, me] = view("awaiting_confirmation", "captain");
    const reporter = match.result.reported_by_id ?? "";
    open({ ...match, viewer: { ...match.viewer, team: "A" } }, { ...me, player: { ...me.player, id: reporter } });
    expect(await screen.findByRole("heading", { name: /^Waiting for P\d+ to confirm$/ })).toBeInTheDocument();
  });
});

describe("Match scoreboard names", () => {
  it("lets a captain match each name to a player on that team", async () => {
    const [match, me] = view("awaiting_confirmation_scoreboard", "captain");
    const board = match.scoreboard!;
    expect(board.rows).toHaveLength(2);
    const { server } = open(match, me);
    expect(await screen.findByRole("heading", { name: "Match scoreboard names" })).toBeInTheDocument();
    expect(screen.getByText("2 left")).toBeInTheDocument();

    const save = screen.getByRole("button", { name: "Save names" });
    expect(save).toBeDisabled();
    for (const row of board.rows) {
      const player = board.players.find((p) => p.team === row.team)!;
      await userEvent.click(screen.getByRole("button", { name: new RegExp(`Player for ${row.name}`) }));
      await userEvent.click(await screen.findByRole("option", { name: player.name }));
    }
    await userEvent.click(screen.getByRole("button", { name: "Save 2 names" }));
    for (const row of board.rows) {
      const player = board.players.find((p) => p.team === row.team)!;
      await vi.waitFor(() =>
        expect(server.received).toContainEqual(
          expect.objectContaining({ t: "act", name: "ocr.map_row", args: { read_id: board.read_id, row: row.row, player_id: player.id } }),
        ),
      );
    }
  });

  it("offers each row only its own team's players", async () => {
    const [match, me] = view("awaiting_confirmation_scoreboard", "captain");
    const row = match.scoreboard!.rows[0]!;
    open(match, me);
    await userEvent.click(await screen.findByRole("button", { name: new RegExp(`Player for ${row.name}`) }));
    const options = await screen.findAllByRole("option");
    const names = match.scoreboard!.players.filter((p) => p.team === row.team).map((p) => p.name);
    expect(options.map((o) => o.textContent)).toEqual(names);
  });

  it.each(["player", "spectator"] as const)("isn't shown to the %s", async (who) => {
    open(...view("awaiting_confirmation_scoreboard", who));
    expect(await screen.findByText(/^Waiting for/)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Match scoreboard names" })).not.toBeInTheDocument();
  });
});

describe("Result", () => {
  it("shows a player their result and rating change", async () => {
    const [match, me] = view("completed", "player");
    const mine = match.result.deltas[me.player.id]!;
    open(match, me);
    const won = match.viewer.team === match.result.winner;
    expect(await screen.findByRole("heading", { name: won ? "Victory" : "Defeat" })).toBeInTheDocument();
    expect(screen.getByText("Your rating")).toBeInTheDocument();
    expect(screen.getAllByText(signed(mine)).length).toBeGreaterThan(1);
    expect(screen.getByRole("link", { name: "Queue again" })).toHaveAttribute("href", "/");
    for (const team of ["P1's Team", "P2's Team"]) {
      const list = screen.getByRole("list", { name: `${team} players` });
      expect(within(list).getAllByRole("listitem")).toHaveLength(6);
    }
  });

  it("shows a spectator who won, with no rating of their own", async () => {
    const [match, me] = view("completed", "spectator");
    open(match, me);
    expect(await screen.findByRole("heading", { name: "Result" })).toBeInTheDocument();
    expect(screen.getByText(new RegExp(`^${match.team_names[match.result.winner!]} won`))).toBeInTheDocument();
    expect(screen.queryByText("Your rating")).not.toBeInTheDocument();
  });
});

describe("Result disputed", () => {
  it("shows each captain's answer", async () => {
    const [match, me] = view("disputed", "captain");
    open(match, me);
    expect(await screen.findByRole("heading", { name: "Staff are reviewing" })).toBeInTheDocument();
    const [report, dispute] = match.result.responses;
    // The room header's avatar shows initials too ("P1"), so look at the answers' own terms.
    expect(screen.getByText(report!.name, { selector: "dt" }).nextSibling).toHaveTextContent("P2's Team won");
    expect(screen.getByText(dispute!.name, { selector: "dt" }).nextSibling).toHaveTextContent("Disputed");
    expect(screen.queryByText("We won that one.")).not.toBeInTheDocument();
  });
});

describe("Match cancelled", () => {
  it("shows a requeued player their place, and lets them leave", async () => {
    const [match, me] = view("voided_ready_check", "player");
    expect(me.queue.in_queue).toBe(true);
    const { server } = open(match, me);
    expect(await screen.findByRole("heading", { name: "Match cancelled" })).toBeInTheDocument();
    expect(screen.getByText(`${match.result.void_reason}.`)).toBeInTheDocument();
    expect(screen.getByText("Back in queue")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Leave queue" }));
    await sent(server, "queue.leave", {});
  });

  it("shows the player who missed the ready check their cooldown", async () => {
    const [match, me] = view("voided_ready_check", "spectator");
    open(match, me);
    expect(await screen.findByRole("heading", { name: "Match cancelled" })).toBeInTheDocument();
    expect(screen.getByText(me.cooldown!.text)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Leave queue" })).not.toBeInTheDocument();
  });
});
