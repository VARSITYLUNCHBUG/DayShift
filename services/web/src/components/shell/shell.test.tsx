import { act, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LiveContext } from "../../live/context";
import type { ConnectionState, LiveSocket } from "../../live/LiveSocket";
import { asPhone } from "../../test/phone";
import { renderPage } from "../../test/render";
import { AppShell } from "./AppShell";
import { ConnectionBanner, OFFLINE_AFTER_MS, RECONNECTING_AFTER_MS } from "./ConnectionBanner";
import { RANKED_PHASES, RoomHeader, roomPhase } from "./RoomHeader";
import { RoomShell } from "./RoomShell";

const ME = { name: "Rook" };

describe("AppShell", () => {
  it("has a skip link, the main nav with the current page, and you", () => {
    renderPage(
      <AppShell me={ME} status={<span>In the queue · 8/12</span>}>
        <h1>Ladder</h1>
      </AppShell>,
      { live: false, route: "/ladder" },
    );
    expect(screen.getByRole("link", { name: "Skip to content" })).toHaveAttribute("href", "#main");
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(within(nav).getByRole("link", { name: "Ladder" })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("link", { name: "Tools" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Me: Rook" })).toHaveAttribute("href", "/me");
    expect(screen.getByText("In the queue · 8/12")).toBeInTheDocument();
    expect(screen.getByRole("main")).toHaveAttribute("id", "main");
  });

  it("offers Sign in when signed out", () => {
    renderPage(<AppShell me={null}>x</AppShell>, { live: false });
    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/signin");
  });

  it("uses the phone bars below 768: Play, Matches, Ladder, Me", () => {
    asPhone();
    renderPage(<AppShell me={ME}>x</AppShell>, { live: false, route: "/" });
    const tabs = screen.getByRole("navigation", { name: "Main" });
    expect(within(tabs).getAllByRole("link").map((link) => link.textContent)).toEqual(["Play", "Matches", "Ladder", "Me"]);
    expect(within(tabs).getByRole("link", { name: "Play" })).toHaveAttribute("aria-current", "page");
  });
});

describe("Room shell", () => {
  it("maps main's statuses onto the eight-phase rail", () => {
    expect(roomPhase("READY_CHECK").current).toBe(0);
    expect(roomPhase("captain_checkin").current).toBe(1);
    expect(roomPhase("coinflip").current).toBe(3);
    expect(roomPhase("awaiting_confirmation").current).toBe(7);
    expect(roomPhase("drafted", "scrim")).toEqual({ phases: ["Captains", "Sides", "Heroes", "Drafted"], current: 3 });
  });

  it("marks the current phase as the step, in the acting team's colour", () => {
    renderPage(<RoomHeader number="No. 413" phases={RANKED_PHASES} current={4} tone="hk" />, { live: false });
    const rail = screen.getByRole("list", { name: "Match phases" });
    const current = within(rail).getAllByRole("listitem")[4]!;
    expect(current).toHaveAttribute("aria-current", "step");
    expect(current).toHaveAccessibleName("Heroes, current step, 5 of 8");
    expect(current.querySelector(".bg-team-hk")).not.toBeNull();
    expect(screen.getByRole("link", { name: "Skip to the match" })).toHaveAttribute("href", "#stage");
    expect(screen.getByRole("link", { name: "Back to Play" })).toHaveAttribute("href", "/");
  });

  it("puts the stage in #stage and, on a phone, the action in a sticky footer", () => {
    asPhone();
    renderPage(
      <RoomShell number="No. 413" phases={RANKED_PHASES} current={4} tone="hk" phaseLine="Heroes · your pick" footer={<button type="button">Lock in Ivy</button>}>
        <p>the stage</p>
      </RoomShell>,
      { live: false },
    );
    expect(screen.getByRole("main")).toHaveAttribute("id", "stage");
    expect(screen.getByText("Heroes · your pick")).toHaveClass("text-team-hk");
    expect(screen.getByRole("button", { name: "Lock in Ivy" }).parentElement).toHaveClass("fixed");
  });
});

/** A stand-in for the live socket: just its connection state. */
function stubSocket() {
  let state: ConnectionState = "open";
  const listeners = new Set<() => void>();
  return {
    socket: {
      getState: () => state,
      subscribeState: (listener: () => void) => {
        listeners.add(listener);
        return () => listeners.delete(listener);
      },
    } as unknown as LiveSocket,
    set(next: ConnectionState) {
      state = next;
      for (const listener of listeners) listener();
    },
  };
}

describe("ConnectionBanner", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("says reconnecting after 3 s down, offline after 20 s, and goes when it's back", () => {
    vi.useFakeTimers();
    const live = stubSocket();
    renderPage(
      <LiveContext value={live.socket}>
        <ConnectionBanner />
      </LiveContext>,
      { live: false },
    );
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    act(() => {
      live.set("reconnecting");
    });
    act(() => {
      vi.advanceTimersByTime(RECONNECTING_AFTER_MS - 1);
    });
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(screen.getByRole("status")).toHaveTextContent("Reconnecting. Your place and picks are safe.");
    act(() => {
      vi.advanceTimersByTime(OFFLINE_AFTER_MS);
    });
    expect(screen.getByRole("status")).toHaveTextContent("You're offline.");
    expect(screen.getByRole("button", { name: "Reload" })).toBeInTheDocument();
    act(() => {
      live.set("open");
    });
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
