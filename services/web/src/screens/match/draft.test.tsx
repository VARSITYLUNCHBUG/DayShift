import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { matchFixture } from "../../match/fixtures";
import { toggleWish, wishesOf } from "../../match/model";
import { renderPage } from "../../test/render";
import { Chat } from "./Chat";
import { lastAct, openRoom, roomReady } from "./testing";
import { resetMatchToasts } from "./useMatchToasts";

afterEach(() => {
  vi.restoreAllMocks();
  resetMatchToasts();
});

describe("hero draft", () => {
  it("chooses a hero, then bans it", async () => {
    const { server, match } = openRoom("champion_draft", "captain");
    await roomReady();
    const grid = screen.getByRole("listbox", { name: "Heroes: choose one" });
    const hero = match.champions.find((h) => !h.taken && !match.draft.some((d) => d.champion?.id === h.id));
    if (!hero) throw new Error("a free hero");
    await userEvent.click(within(grid).getByRole("option", { name: new RegExp(`^${hero.name}`) }));
    // A ban step: the button says Ban.
    await userEvent.click(screen.getAllByRole("button", { name: `Ban ${hero.name}` })[0] as HTMLElement);
    await waitFor(() =>
      expect(lastAct(server)).toEqual([
        "draft.champion",
        { match_id: match.id, step_index: match.step_index, champion_id: hero.id },
      ]),
    );
  });

  it("takes a random hero", async () => {
    const { server, match } = openRoom("champion_draft", "captain");
    await roomReady();
    await userEvent.click(screen.getAllByRole("button", { name: "Random" })[0] as HTMLElement);
    await waitFor(() =>
      expect(lastAct(server)).toEqual(["draft.random_champion", { match_id: match.id, step_index: match.step_index }]),
    );
  });

  it("strikes banned heroes and draws the 18-step strip", async () => {
    const { match } = openRoom("champion_draft", "player");
    await roomReady();
    expect(screen.getByRole("list", { name: "Draft order" }).children).toHaveLength(match.champion_steps.length);
    const banned = match.draft.find((d) => d.action === "ban" && d.champion);
    if (banned?.champion)
      expect(screen.getByRole("option", { name: `${banned.champion.name}, banned` })).toHaveAttribute("aria-disabled", "true");
  });

  it("lets a teammate wish from the grid, straight away", async () => {
    const { server, match, playerId } = openRoom("champion_draft", "player");
    await roomReady();
    const mine = wishesOf(match.wishes, playerId);
    const grid = screen.getByRole("listbox", { name: "Heroes: press to wish" });
    const free = match.champions.find(
      (h) => !h.taken && !mine.includes(h.id) && !match.draft.some((d) => d.champion?.id === h.id),
    );
    if (!free) throw new Error("a free hero");
    await userEvent.click(within(grid).getByRole("option", { name: new RegExp(`^${free.name}`) }));
    const next = toggleWish(mine, free.id);
    if (next === null) {
      expect(screen.getAllByText("You have three wishes already").length).toBeGreaterThan(0);
    } else {
      await waitFor(() => expect(lastAct(server)).toEqual(["wish.set", { match_id: match.id, champion_ids: next }]));
    }
  });

  it("filters to what the team wants", async () => {
    const { match } = openRoom("champion_draft", "player");
    await roomReady();
    await userEvent.click(screen.getByRole("button", { name: "Only what we want" }));
    const wanted = new Set(match.wishes.map((w) => w.champion_id));
    expect(within(screen.getByRole("listbox", { name: /^Heroes/ })).getAllByRole("option")).toHaveLength(wanted.size);
  });

  it("shows spectators no chat, no wishes", async () => {
    openRoom("champion_draft", "spectator");
    await roomReady();
    expect(screen.queryByRole("heading", { name: "Team chat" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Only what we want" })).toBeNull();
    expect(screen.queryByText(/wants$/)).toBeNull();
  });
});

describe("wishes", () => {
  it("adds and removes, and refuses a fourth", () => {
    expect(toggleWish(["1", "2"], "3")).toEqual(["1", "2", "3"]);
    expect(toggleWish(["1", "2", "3"], "4")).toBeNull();
    expect(toggleWish(["1", "2", "3"], "2")).toEqual(["1", "3"]);
  });

  it("puts the server's list back after a refusal, and says why", async () => {
    const { match, playerId } = openRoom("coinflip", "player", {
      answer: (name) => (name === "wish.set" ? { ok: false, error: "Wishes are closed." } : { ok: true }),
    });
    await roomReady();
    const mine = wishesOf(match.wishes, playerId);
    const picker = screen.getByRole("listbox", { name: "Heroes to wish for" });
    const target = mine[0] ?? match.champions[0]?.id;
    const hero = match.champions.find((h) => h.id === target);
    if (!hero) throw new Error("a hero");
    await userEvent.click(within(picker).getByRole("option", { name: new RegExp(`^${hero.name}`) }));
    expect(await screen.findByText("Wishes are closed.")).toBeInTheDocument();
  });
});

describe("swaps", () => {
  it("lets a captain offer one of theirs for one of the other team's", async () => {
    const { server, match } = openRoom("champion_draft", "captain");
    await roomReady();
    await userEvent.click(screen.getByRole("button", { name: "Request a player swap" }));
    const give = match.viewer.swap_give[0];
    const take = match.viewer.swap_take[0];
    if (!give || !take) throw new Error("swap choices");
    await userEvent.click(
      within(screen.getByRole("radiogroup", { name: "One of yours" })).getByRole("radio", { name: give.name }),
    );
    await userEvent.click(
      within(screen.getByRole("radiogroup", { name: "For one of theirs" })).getByRole("radio", { name: take.name }),
    );
    await userEvent.click(screen.getByRole("button", { name: `Offer ${give.name} for ${take.name}` }));
    await waitFor(() =>
      expect(lastAct(server)).toEqual(["swap.propose", { match_id: match.id, give_id: give.player_id, take_id: take.player_id }]),
    );
  });

  it("asks the other captain, in a sheet", async () => {
    const { server, match } = openRoom("champion_draft_swap_pending", "captain");
    await roomReady();
    const sheet = screen.getByRole("dialog", { name: "P2 asks to swap P3 for P4" });
    await userEvent.click(within(sheet).getByRole("button", { name: "Accept the swap" }));
    await waitFor(() => expect(lastAct(server)).toEqual(["swap.answer", { match_id: match.id, swap_id: "1", accept: true }]));
  });

  it("shows a player the pending swap without answering it", async () => {
    openRoom("champion_draft_swap_pending", "player");
    await roomReady();
    expect(screen.queryByRole("button", { name: "Accept the swap" })).toBeNull();
  });
});

describe("chat", () => {
  it("shows lines as text, never HTML", async () => {
    openRoom("player_draft", "player");
    await roomReady();
    const lines = screen.getByRole("list", { name: "Lobby chat messages" });
    expect(within(lines).getByText("Noted. <b>No promises</b> & no tilting")).toBeInTheDocument();
    expect(lines.querySelector("b b")).toBeNull();
    expect(lines).toHaveAttribute("aria-live", "polite");
    expect(lines).toHaveAttribute("aria-relevant", "additions");
    expect(screen.getByText("All 12 players. Closes when teams are set.")).toBeInTheDocument();
  });

  it("sends, shows your line at once, and keeps the draft on a refusal", async () => {
    let refuse = false;
    const { server, match } = openRoom("champion_draft", "player", {
      answer: (name) => (name === "chat.send" && refuse ? { ok: false, error: "Slow down a little." } : { ok: true }),
    });
    await roomReady();
    const box = screen.getByRole("textbox", { name: "Message your team" });
    await userEvent.type(box, "ivy pls{Enter}");
    await waitFor(() => expect(lastAct(server)).toEqual(["chat.send", { match_id: match.id, body: "ivy pls" }]));
    refuse = true;
    await userEvent.type(box, "again{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent("Slow down a little.");
    expect(box).toHaveValue("again");
  });

  it("is read-only once the game is over", async () => {
    const { match } = openRoom("awaiting_confirmation", "player");
    await roomReady();
    expect(screen.queryByRole("textbox", { name: "Message your team" })).toBeNull();
    expect(screen.getByText(match.chat?.closed_reason ?? "")).toBeInTheDocument();
  });

  it("says when it's waiting for the connection", () => {
    const match = matchFixture("champion_draft", "player");
    const chat = match.chat;
    if (!chat) throw new Error("a chat");
    renderPage(<Chat match={match} chat={chat} myId="3" myName="P3" isOffline />);
    expect(screen.getByRole("textbox", { name: "Chat is back when you are" })).toBeDisabled();
  });
});
