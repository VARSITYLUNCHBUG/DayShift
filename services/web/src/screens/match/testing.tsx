// Test helpers for the match room: open /matches/:id on a FakeServer with a fixture, and read back
// the actions sent. Only tests import this file.
import { screen } from "@testing-library/react";

import type { AckScript } from "../../live/FakeServer";
import type { MatchSnap } from "../../live/protocol.gen";
import type { AnySnap, Topic } from "../../live/types";
import { FIXTURE_NOW, matchFixture, viewerId } from "../../match/fixtures";
import type { Viewer } from "../../match/fixtures";
import { renderPage } from "../../test/render";
import { MatchRoute } from "./MatchRoute";

interface Options {
  /** Change the fixture before it's served. */
  edit?: (match: MatchSnap) => void;
  answer?: (name: string, args: Record<string, unknown>) => AckScript;
  playerId?: string;
}

export function openRoom(scene: string, viewer: Viewer, options: Options = {}) {
  const match = matchFixture(scene, viewer);
  options.edit?.(match);
  const playerId = options.playerId ?? viewerId(scene, viewer);
  const snaps = { [`match:${match.id}`]: match } as unknown as Partial<Record<Topic, AnySnap>>;
  const result = renderPage(<MatchRoute />, {
    snaps,
    playerId,
    serverTime: FIXTURE_NOW,
    answer: options.answer,
    route: `/matches/${match.id}`,
    path: "/matches/:id",
  });
  return { ...result, match, playerId };
}

/** The room has its first snapshot: the phase rail is up. */
export async function roomReady(): Promise<void> {
  await screen.findByRole("region", { name: "Now" });
}

/** The actions the page sent, as [name, args]. */
export function acts(server: { received: { t: string }[] }): [string, Record<string, unknown>][] {
  return server.received
    .filter((m): m is { t: "act"; name: string; args?: Record<string, unknown> } => m.t === "act")
    .map((m) => [m.name, m.args ?? {}]);
}

export function lastAct(server: { received: { t: string }[] }): [string, Record<string, unknown>] | undefined {
  return acts(server).at(-1);
}
