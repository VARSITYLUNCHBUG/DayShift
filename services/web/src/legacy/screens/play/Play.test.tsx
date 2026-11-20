import { Toast } from "@heroui/react";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { fixture, placeHeldMe } from "../../dev/fixtures";
import type { LiveSnap, MeSnap, QueueSnap } from "../../../live/types";
import { renderPage } from "../../../test/render";
import { PlayPage } from "./Play";

function play(me: MeSnap, queue: QueueSnap, live: LiveSnap, answer = () => ({ ok: true })) {
  return renderPage(<PlayPage />, { snaps: { me, queue, live }, playerId: me.player.id, answer });
}

describe("Play", () => {
  it("shows the queue and lets an idle player join", async () => {
    const { server } = play(fixture.me("completed", "player"), fixture.queue("ready_check"), fixture.live("ready_check"));
    expect(await screen.findByText("Queue · 11 more to start")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "1 / 12" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Join queue" }));
    await vi.waitFor(() => expect(server.lastAct()).toMatchObject({ name: "queue.join", args: {} }));
  });

  it("shows a queued player's place, and Leave queue", async () => {
    const me = fixture.me("ready_check", "spectator");
    const { server } = play(me, fixture.queue("ready_check"), fixture.live("ready_check"));
    expect(await screen.findByText(/^#1 of 1/)).toBeInTheDocument();
    const list = screen.getByRole("list", { name: "In queue" });
    expect(within(list).getByText(me.player.name).closest("li")).toHaveAttribute("aria-current", "true");
    await userEvent.click(screen.getByRole("button", { name: "Leave queue" }));
    await vi.waitFor(() => expect(server.lastAct()).toMatchObject({ name: "queue.leave" }));
  });

  it("shows a held place counting down", async () => {
    play(placeHeldMe(), fixture.queue("voided_ready_check"), fixture.live("in_progress"));
    expect(await screen.findByText(/^Place held · 2:4[01]$/)).toBeInTheDocument();
  });

  it("keeps a player on cooldown out of the queue", async () => {
    play(fixture.me("voided_ready_check", "spectator"), fixture.queue("voided_ready_check"), fixture.live("voided_ready_check"));
    expect(await screen.findByText("Queue opens in")).toBeInTheDocument();
    expect(screen.getByText("Missed ready check")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "1 strike" })).toBeInTheDocument();
    expect(screen.getByText("next off in 3 clean matches")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Join queue" })).toBeDisabled();
  });

  it("shows a queue refusal in the server's words", async () => {
    renderPage(
      <>
        <Toast.Provider />
        <PlayPage />
      </>,
      {
        snaps: {
          me: fixture.me("completed", "player"),
          queue: fixture.queue("ready_check"),
          live: fixture.live("ready_check"),
        },
        answer: () => ({ ok: false, error: "The queue is closed." }),
      },
    );
    await userEvent.click(await screen.findByRole("button", { name: "Join queue" }));
    expect(await screen.findByText("The queue is closed.")).toBeInTheDocument();
  });

  it("shows a scrim you captain above the queue", async () => {
    const me = fixture.me("scrim_champion_draft", "captain");
    play(me, fixture.queue("scrim_champion_draft"), fixture.live("scrim_champion_draft"));
    expect(await screen.findByText("Your scrim")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Match 1 · Hero draft" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open scrim" })).toHaveAttribute("href", "/matches/1");
    // Scrim captains can still queue.
    expect(screen.getByRole("button", { name: "Join queue" })).toBeInTheDocument();
  });

  it("lists live matches, linking to each", async () => {
    play(fixture.me("completed", "player"), fixture.queue("in_progress"), fixture.live("in_progress"));
    const live = await screen.findByRole("region", { name: "Live" });
    const link = await within(live).findByRole("link", { name: /Match 1/ });
    expect(link).toHaveAttribute("href", "/matches/1");
    expect(link).toHaveTextContent("P2's Team vs P1's Team");
    expect(link).toHaveTextContent(/In game · \d+:\d\d/);
  });
});
