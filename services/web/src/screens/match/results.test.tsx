import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { reportForm } from "../../match/report";
import { lastAct, openRoom, roomReady } from "./testing";
import { resetMatchToasts } from "./useMatchToasts";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  resetMatchToasts();
});

describe("lobby", () => {
  it("shows the bot making the lobby", async () => {
    openRoom("lobby_code", "player");
    await roomReady();
    expect(screen.getByRole("heading", { name: "The bot is making your lobby" })).toBeInTheDocument();
  });

  it("checks the host's code, shows a refusal under the field, then sends it", async () => {
    let refuse = true;
    const { server, match } = openRoom("lobby_code_failed", "captain", {
      answer: (name) => (name === "draft.lobby_code" && refuse ? { ok: false, error: "That code is in use." } : { ok: true }),
    });
    await roomReady();
    const field = screen.getByRole("textbox", { name: "Lobby code" });
    const share = screen.getByRole("button", { name: /^Share code with the/ });
    await userEvent.type(field, "no!");
    await userEvent.click(share);
    expect(screen.getByText("A lobby code is 3 to 32 letters, numbers or dashes.")).toBeInTheDocument();
    await userEvent.clear(field);
    await userEvent.type(field, "K7Q2PX");
    await userEvent.click(share);
    expect(await screen.findByText("That code is in use.")).toBeInTheDocument();
    expect(lastAct(server)).toEqual(["draft.lobby_code", { match_id: match.id, code: "K7Q2PX" }]);
    refuse = false;
    await userEvent.click(share);
    await waitFor(() => expect(screen.queryByText("That code is in use.")).toBeNull());
  });

  it("lets a captain start the bot's lobby", async () => {
    const { server, match } = openRoom("in_progress_api_lobby", "captain");
    await roomReady();
    await userEvent.click(screen.getAllByRole("button", { name: "Start match" })[0] as HTMLElement);
    await waitFor(() => expect(lastAct(server)).toEqual(["draft.api_start", { match_id: match.id }]));
  });

  it("never shows spectators the code", async () => {
    openRoom("in_progress_api_lobby", "spectator");
    await roomReady();
    expect(screen.queryByText(/^Lobby code:/)).toBeNull();
  });
});

describe("in game", () => {
  it("reports an early leave", async () => {
    const { server, match } = openRoom("in_progress", "captain", {
      edit: (m) => {
        m.early_leave.open = true;
      },
    });
    await roomReady();
    await userEvent.click(screen.getByRole("button", { name: "Report an early leave" }));
    const dialog = await screen.findByRole("dialog", { name: "Who left early?" });
    const other = match.players.find((p) => p.team === "B");
    if (!other) throw new Error("a player");
    await userEvent.click(within(dialog).getByRole("radio", { name: other.name }));
    await userEvent.click(within(dialog).getByRole("button", { name: `Report ${other.name}` }));
    await waitFor(() => expect(lastAct(server)).toEqual(["early_leave.report", { match_id: match.id, player_id: other.id }]));
    expect(document.body.textContent).not.toMatch(/\d+ min/);
  });

  it("lets the other captain agree", async () => {
    const { server, match } = openRoom("in_progress_early_leave", "captain");
    await roomReady();
    const sheet = screen.getByRole("dialog", { name: "P2 says P3 left early" });
    await userEvent.click(within(sheet).getByRole("button", { name: "Agree: void the match" }));
    await waitFor(() => expect(lastAct(server)).toEqual(["early_leave.answer", { match_id: match.id, agree: true }]));
  });

  it("reports the result over HTTP: the match ID is required, the screenshot isn't", async () => {
    const fetch = vi.fn(() =>
      Promise.resolve(new Response(JSON.stringify({ status: "awaiting_confirmation" }), { status: 200 })),
    );
    vi.stubGlobal("fetch", fetch);
    const { match } = openRoom("in_progress", "captain");
    await roomReady();
    await userEvent.click(screen.getAllByRole("button", { name: "Report result" })[0] as HTMLElement);
    expect(screen.getByRole("heading", { name: `Who won No. ${match.id}?` })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "P2's Team won" }));
    await userEvent.click(screen.getByRole("button", { name: "Send: P2's Team won" }));
    expect(screen.getByText(/Enter the Deadlock match ID/)).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
    await userEvent.type(screen.getByRole("textbox", { name: "Deadlock match ID" }), "41207733");
    await userEvent.click(screen.getByRole("button", { name: "Send: P2's Team won" }));
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe(`/api/matches/${match.id}/report/`);
    const body = init.body as FormData;
    expect(body.get("winner")).toBe("A");
    expect(body.get("deadlock_match_id")).toBe("41207733");
    expect(body.get("screenshot")).toBeNull();
  });

  it("shows the server's refusal", async () => {
    vi.stubGlobal("fetch", () =>
      Promise.resolve(new Response(JSON.stringify({ refusal: "This match isn't waiting for a result." }), { status: 400 })),
    );
    openRoom("in_progress", "captain");
    await roomReady();
    await userEvent.click(screen.getAllByRole("button", { name: "Report result" })[0] as HTMLElement);
    await userEvent.click(screen.getByRole("button", { name: "P2's Team won" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Deadlock match ID" }), "41207733");
    await userEvent.click(screen.getByRole("button", { name: "Send: P2's Team won" }));
    expect(await screen.findByText("This match isn't waiting for a result.")).toBeInTheDocument();
  });

  it("builds the form the endpoint reads", () => {
    const file = new File(["x"], "board.png", { type: "image/png" });
    const form = reportForm({ winner: "B", deadlockMatchId: " 12 ", screenshot: file, mvp: "3", keys: ["3", "4", "5"] });
    expect(form.get("deadlock_match_id")).toBe("12");
    expect((form.get("screenshot") as File).name).toBe("board.png");
    expect(form.getAll("keys")).toEqual(["4", "5"]);
  });
});

describe("confirming", () => {
  it("confirms", async () => {
    const { server, match } = openRoom("awaiting_confirmation", "captain");
    await roomReady();
    expect(screen.getByRole("heading", { name: "P2's Team won" })).toBeInTheDocument();
    await userEvent.click(screen.getAllByRole("button", { name: "Confirm" })[0] as HTMLElement);
    await waitFor(() => expect(lastAct(server)).toEqual(["results.confirm", { match_id: match.id }]));
  });

  it("disputes with a note", async () => {
    const { server, match } = openRoom("awaiting_confirmation", "captain");
    await roomReady();
    await userEvent.click(screen.getAllByRole("button", { name: "Dispute" })[0] as HTMLElement);
    const dialog = await screen.findByRole("dialog", { name: "Dispute the result?" });
    await userEvent.type(within(dialog).getByRole("textbox"), "We won");
    await userEvent.click(within(dialog).getByRole("button", { name: "Dispute" }));
    await waitFor(() => expect(lastAct(server)).toEqual(["results.dispute", { match_id: match.id, note: "We won" }]));
  });

  it("asks a captain to match the scoreboard's names", async () => {
    openRoom("awaiting_confirmation_scoreboard", "captain");
    await roomReady();
    expect(screen.getByRole("heading", { name: "Match the scoreboard names" })).toBeInTheDocument();
    expect(screen.getByText("stranger_A1")).toBeInTheDocument();
  });

  it("links a finished match to its postgame", async () => {
    const { match } = openRoom("completed", "player");
    await roomReady();
    expect(screen.getByRole("link", { name: "Postgame: timeline" })).toHaveAttribute("href", `/matches/${match.id}/timeline`);
  });

  it("says why a match was cancelled", async () => {
    openRoom("voided_ready_check", "player");
    await roomReady();
    expect(screen.getByText("Not enough players to fill the lobby")).toBeInTheDocument();
  });
});

describe("subs", () => {
  it("asks who comes out, then requests the sub", async () => {
    const { server, match } = openRoom("in_progress", "player", {
      edit: (m) => {
        m.viewer.can_request_sub = true;
      },
      answer: (name) =>
        name === "subs.options"
          ? {
              ok: true,
              result: { choices: [{ player_id: "3", name: "P3", is_self: true }], game_on: true, dodge: false, strikes: 1 },
            }
          : name === "subs.request"
            ? { ok: true, result: { request_id: "9" } }
            : { ok: true },
    });
    await roomReady();
    await userEvent.click(screen.getByRole("button", { name: "Need a sub" }));
    const dialog = await screen.findByRole("dialog", { name: "Need a sub?" });
    expect(await within(dialog).findByText(/counts as leaving, with 1 strike/)).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Ask for a sub" }));
    await waitFor(() => expect(lastAct(server)).toEqual(["subs.request", { match_id: match.id, player_id: "3" }]));
  });

  it("lets the other captain approve", async () => {
    const { server } = openRoom("player_draft_sub_approval", "captain");
    await roomReady();
    const sheet = screen.getByRole("dialog", { name: "P2 wants to sub out P3" });
    await userEvent.click(within(sheet).getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(lastAct(server)).toEqual(["subs.answer_request", { request_id: "1", approve: true }]));
  });

  it("pauses the match and lets the captain name a sub or ask the queue", async () => {
    const { server } = openRoom("player_draft_sub_naming", "captain");
    await roomReady();
    expect(screen.getByText(/P3 is subbing out/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Name a sub" }));
    const dialog = await screen.findByRole("dialog", { name: "Name a sub" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Offer it to the queue" }));
    await waitFor(() => expect(lastAct(server)).toEqual(["subs.offer_queue", { request_id: "1" }]));
  });

  it("lets whoever asked cancel", async () => {
    const { server } = openRoom("in_progress_sub_offered", "player");
    await roomReady();
    await userEvent.click(screen.getByRole("button", { name: "Cancel the sub" }));
    await waitFor(() => expect(lastAct(server)).toEqual(["subs.cancel", { request_id: "1" }]));
  });
});
