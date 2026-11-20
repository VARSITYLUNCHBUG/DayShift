import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { hasMatch, SCENES, VIEWERS } from "../../match/fixtures";
import { asPhone } from "../../test/phone";
import { MATCH_SCREENS } from "./MatchRoute";
import { lastAct, openRoom, roomReady } from "./testing";
import { resetMatchToasts } from "./useMatchToasts";

afterEach(() => {
  vi.restoreAllMocks();
  resetMatchToasts();
});

describe("the match room", () => {
  it("has a screen for every status", () => {
    expect(Object.keys(MATCH_SCREENS)).toHaveLength(15);
  });

  const cases = SCENES.flatMap((scene) =>
    VIEWERS.filter((viewer) => hasMatch(scene, viewer)).map((viewer) => [scene, viewer] as const),
  );

  it.each(cases)("renders %s for a %s", async (scene, viewer) => {
    openRoom(scene, viewer);
    await roomReady();
    expect(screen.getAllByRole("heading", { level: 1 }).length).toBeGreaterThan(0);
    // Players only ever see "left early", never the window's minutes (D17).
    expect(document.body.textContent).not.toMatch(/\b5 min/);
  });

  it("hands a match that isn't live to its record", async () => {
    const { server } = openRoom("ready_check", "player");
    await roomReady();
    server.gone("match:1");
    // The record (/matches/1/summary, FE-PAGES') says what happened, or that there's no such match.
    await waitFor(() => expect(screen.queryByRole("region", { name: "Now" })).not.toBeInTheDocument());
  });
});

describe("ready check", () => {
  it("sends Ready", async () => {
    const { server } = openRoom("ready_check", "player", {
      edit: (m) => {
        m.players = m.players.map((p) => (p.id === "1" ? { ...p, is_ready: false } : p));
      },
    });
    await roomReady();
    await userEvent.click(screen.getAllByRole("button", { name: "Ready" })[0] as HTMLElement);
    await waitFor(() => expect(lastAct(server)).toEqual(["lobby.ready", { match_id: "1" }]));
  });

  it("shows a seat being refilled", async () => {
    openRoom("ready_check_refill", "player");
    await roomReady();
    expect(screen.getByText("Refilling a seat")).toBeInTheDocument();
    expect(screen.getAllByText(/P12/).length).toBeGreaterThan(0);
  });
});

describe("captain vote", () => {
  it("says when both votes are used, and changes a vote", async () => {
    const { server, match } = openRoom("captain_phase", "player");
    await roomReady();
    expect(screen.getByRole("button", { name: "Vote for P5", pressed: true })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Vote for P2" }));
    expect(screen.getByText("You've used both votes")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Vote for P5" }));
    await userEvent.click(screen.getByRole("button", { name: "Vote for P2" }));
    await userEvent.click(screen.getAllByRole("button", { name: "Change my vote" })[0] as HTMLElement);
    await waitFor(() => expect(lastAct(server)).toEqual(["lobby.vote", { match_id: match.id, candidate_ids: ["8", "2"] }]));
  });

  it("votes for the captains chosen", async () => {
    const { server, match } = openRoom("captain_phase", "player", {
      edit: (m) => {
        m.viewer.has_voted = false;
        m.viewer.votes = [];
      },
    });
    await roomReady();
    const ok = match.players.filter((p) => p.captain_ok && p.id !== "1").slice(0, 2);
    for (const p of ok) await userEvent.click(screen.getByRole("button", { name: `Vote for ${p.name}` }));
    await userEvent.click(screen.getAllByRole("button", { name: "Vote for 2 captains" })[0] as HTMLElement);
    await waitFor(() =>
      expect(lastAct(server)).toEqual(["lobby.vote", { match_id: match.id, candidate_ids: ok.map((p) => p.id) }]),
    );
  });
});

describe("captain check-in", () => {
  it("checks a captain in", async () => {
    const { server, match } = openRoom("captain_checkin", "captain");
    await roomReady();
    await userEvent.click(screen.getAllByRole("button", { name: "I'm here" })[0] as HTMLElement);
    await waitFor(() => expect(lastAct(server)).toEqual(["lobby.checkin", { match_id: match.id }]));
  });

  it("shows the others who has checked in", async () => {
    openRoom("captain_checkin", "player");
    await roomReady();
    expect(screen.getByRole("list", { name: "Captains" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "I'm here" })).toBeNull();
  });
});

describe("player draft", () => {
  it("picks a player with one press", async () => {
    const { server, match } = openRoom("player_draft", "captain");
    await roomReady();
    const grid = screen.getByRole("listbox", { name: /Players left/ });
    await userEvent.click(within(grid).getByRole("option", { name: "P4" }));
    await waitFor(() =>
      expect(lastAct(server)).toEqual([
        "draft.pick_player",
        { match_id: match.id, step_index: match.step_index, player_id: "4" },
      ]),
    );
  });

  it("lets the others watch, with the lobby chat", async () => {
    openRoom("player_draft", "player");
    await roomReady();
    expect(screen.getByRole("list", { name: "Pick order" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Lobby chat" })).toBeInTheDocument();
    const grid = screen.getByRole("listbox", { name: "Players left" });
    expect(within(grid).getByRole("option", { name: "P4" })).toBeInTheDocument();
  });
});

describe("coinflip", () => {
  it("lets the winner choose a side only", async () => {
    const { server, match } = openRoom("coinflip", "captain");
    await roomReady();
    expect(screen.queryByText("First pick")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /The Archmother/ }));
    await userEvent.click(screen.getByRole("button", { name: "Take The Archmother" }));
    await waitFor(() => expect(lastAct(server)).toEqual(["draft.coinflip", { match_id: match.id, choice: "archmother" }]));
  });

  it("shows the others the team sheet while they wait", async () => {
    openRoom("coinflip", "player");
    await roomReady();
    expect(screen.getByRole("heading", { name: /is choosing|won the flip/ })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: /wants$/ })).toBeInTheDocument();
    expect(screen.getByRole("listbox", { name: "Heroes to wish for" })).toBeInTheDocument();
  });

  it("scrims: the other captain takes the other kind of choice", async () => {
    const { server, match } = openRoom("scrim_coinflip", "captain");
    await roomReady();
    await userEvent.click(screen.getByRole("button", { name: /The Hidden King/ }));
    await userEvent.click(screen.getByRole("button", { name: "Take The Hidden King" }));
    await waitFor(() => expect(lastAct(server)).toEqual(["draft.coinflip", { match_id: match.id, choice: "hidden_king" }]));
  });
});

describe("scrims", () => {
  it("starts the draft", async () => {
    const { server, match } = openRoom("scrim_ready_to_draft", "captain");
    await roomReady();
    await userEvent.click(screen.getAllByRole("button", { name: "Start the hero draft" })[0] as HTMLElement);
    await waitFor(() => expect(lastAct(server)).toEqual(["scrims.start", { match_id: match.id }]));
  });

  it("claims the open side", async () => {
    const { server, match } = openRoom("scrim_captain_claim", "spectator", { playerId: "6" });
    await roomReady();
    await userEvent.click(screen.getByRole("button", { name: "Claim The Archmother" }));
    await waitFor(() => expect(lastAct(server)).toEqual(["scrims.claim", { match_id: match.id, side: "am" }]));
  });
});

describe("on a phone", () => {
  it("puts the chat behind a button with an unread badge", async () => {
    asPhone();
    const { server, match } = openRoom("player_draft", "player");
    await roomReady();
    expect(screen.queryByRole("heading", { name: "Lobby chat" })).toBeNull();
    const chat = match.chat;
    if (!chat) throw new Error("fixture has a chat");
    server.snap(
      `match:${match.id}` as never,
      {
        ...match,
        chat: {
          ...chat,
          messages: [
            ...chat.messages,
            { kind: "message", id: "99", player_id: "2", name: "P2", team: "A", body: "new line", at: "2026-01-05T19:00:10.000Z" },
          ],
        },
      } as never,
    );
    const button = await screen.findByRole("button", { name: "Lobby chat, 1 new" });
    await userEvent.click(button);
    const view = screen.getByRole("dialog", { name: "Lobby chat" });
    expect(within(view).getByText("new line")).toBeInTheDocument();
    await userEvent.click(within(view).getByRole("button", { name: "Back to the match" }));
    expect(screen.getByRole("button", { name: "Lobby chat" })).toBeInTheDocument();
  });
});

describe("system lines", () => {
  it("shows what happened between the messages, and doesn't count it as unread", async () => {
    asPhone();
    const { server, match } = openRoom("player_draft", "player");
    await roomReady();
    const chat = match.chat;
    if (!chat) throw new Error("fixture has a chat");
    server.snap(
      `match:${match.id}` as never,
      {
        ...match,
        chat: { ...chat, messages: [...chat.messages, { kind: "system", id: "d99", body: "P1 picked P7.", at: "2026-01-05T19:00:10.000Z" }] },
      } as never,
    );
    const button = await screen.findByRole("button", { name: "Lobby chat" });
    await userEvent.click(button);
    const view = screen.getByRole("dialog", { name: "Lobby chat" });
    expect(within(view).getByText("P1 picked P7.")).toBeInTheDocument();
  });
});
