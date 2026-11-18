import { describe, expect, it } from "vitest";

import { Match } from "../api/schemas";
import { argsFor, validActions } from "./actions";

/** A twelve-player match in `status`: 1 and 7 captain A and B, 2-6 on A, 8-12 on B. */
function match(status: string, extra: Record<string, unknown> = {}) {
  const players = Array.from({ length: 12 }, (_, i) => {
    const id = i + 1;
    return {
      id,
      name: `Dev ${id}`,
      rating: 2000 - id * 10,
      team: id <= 6 ? "A" : "B",
      is_captain: id === 1 || id === 7,
      ready: true,
      active: true,
    };
  });
  return Match.parse({ id: 3, status, players, ...extra });
}

const actions = (m: ReturnType<typeof match>) => validActions(m).map((c) => c.action);

describe("validActions", () => {
  it("puts what the match waits for first", () => {
    const m = match("captain_checkin", {
      turn: { action: "checkin", player_ids: [7] },
      players: [
        { id: 1, name: "Ash", team: "A", is_captain: true, checked_in: true },
        { id: 7, name: "Bo", team: "B", is_captain: true, checked_in: false },
        { id: 2, name: "Cy", team: "", is_captain: false },
      ],
    });
    const [first] = validActions(m);
    expect(first).toMatchObject({ action: "checkin", actors: [7], onTurn: true });
    expect(actions(m)).toEqual(["checkin", "request_sub", "void"]);
  });

  it("offers swaps between the draft and the game, and the answer once one is pending", () => {
    expect(actions(match("coinflip", { turn: { action: "coinflip", team: "A", player_ids: [1] } }))).toEqual([
      "coinflip",
      "swap",
      "request_sub",
      "void",
    ]);
    const pending = match("champion_draft", {
      turn: { action: "ban", team: "B", player_ids: [7] },
      swaps: [{ id: 4, status: "pending", requested_by: 1, give: 2, take: 8 }],
    });
    const choices = validActions(pending);
    expect(choices.map((c) => c.action)).toEqual(["ban", "accept_swap", "decline_swap", "request_sub", "void"]);
    // Only the other captain answers.
    expect(choices.find((c) => c.action === "accept_swap")?.actors).toEqual([7]);
    expect(argsFor("accept_swap", pending, 7)).toEqual({ swap_id: 4 });
  });

  it("follows the lobby step: deadlock-api first, the code by hand when it fails", () => {
    expect(actions(match("lobby_code", { turn: { action: "api_lobby", player_ids: [] } })).slice(0, 2)).toEqual(["api_lobby", "lobby_code"]);
    const byHand = validActions(match("lobby_code", { turn: { action: "lobby_code", player_ids: [1] } }));
    expect(byHand[0]).toMatchObject({ action: "lobby_code", actors: [1], onTurn: true });
  });

  it("settles a sub request step by step", () => {
    const approval = match("player_draft", { on_hold: true, sub_requests: [{ id: 2, status: "approval", offers: [] }] });
    expect(actions(approval)).toEqual(["approve_sub", "cancel_sub", "void"]);
    const offered = match("player_draft", {
      on_hold: true,
      sub_requests: [{ id: 2, status: "open", offers: [{ id: 3, player_id: 13, status: "pending" }] }],
    });
    expect(actions(offered)).toEqual(["invite_sub", "offer_queue", "cancel_sub", "accept_sub", "decline_sub", "void"]);
  });

  it("offers nothing once the match is over", () => {
    expect(validActions(match("completed"))).toEqual([]);
  });
});

describe("argsFor", () => {
  it("fills in a swap from the actor's team", () => {
    const m = match("coinflip");
    expect(argsFor("swap", m, 1)).toEqual({ give: 2, take: 8 });
    expect(argsFor("swap", m, 7)).toEqual({ give: 8, take: 2 });
  });

  it("drafts the best undrafted player, and votes for the two best", () => {
    const m = match("player_draft", {
      players: [
        { id: 1, name: "A", rating: 1500, team: "A", is_captain: true },
        { id: 2, name: "B", rating: 1200, team: "" },
        { id: 3, name: "C", rating: 1800, team: "" },
      ],
    });
    expect(argsFor("pick", m, 1)).toEqual({ player_id: 3 });
    expect(argsFor("vote", m, 2)).toEqual({ candidates: [3, 1] });
    expect(argsFor("coinflip", m, 1)).toEqual({ choice: "hidden_king" });
  });
});
