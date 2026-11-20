// The match snapshots Django writes (tests/test_web_fixtures.py), typed by the generated protocol,
// for the room's tests and the screen gallery. The app itself never imports this file.
import type { MatchSnap, MeSnap } from "../live/protocol.gen";

const files = import.meta.glob<unknown>("../fixtures/*.json", { eager: true, import: "default" });

const byName = new Map(Object.entries(files).map(([path, data]) => [path.replace(/^.*\/(.+)\.json$/, "$1"), data]));

export type Viewer = "captain" | "player" | "spectator";

/** The fixtures' clock: a ready check that opened at 19:00:00 has 2:41 left. */
export const FIXTURE_NOW = "2026-01-05T19:00:19.000Z";

function load(name: string): unknown {
  const data = byName.get(name);
  if (data === undefined) throw new Error(`No fixture called ${name}.json`);
  // A fresh copy each time, so a test can change one without touching the next.
  return structuredClone(data);
}

export function hasMatch(scene: string, viewer: Viewer): boolean {
  return byName.has(`${scene}.${viewer}`);
}

export function matchFixture(scene: string, viewer: Viewer): MatchSnap {
  return load(`${scene}.${viewer}`) as MatchSnap;
}

export function meFixture(scene: string, viewer: Viewer): MeSnap {
  return load(`${scene}.me-${viewer}`) as MeSnap;
}

/** The signed-in player each fixture was written for. */
export function viewerId(scene: string, viewer: Viewer): string {
  return byName.has(`${scene}.me-${viewer}`) ? meFixture(scene, viewer).player.id : "13";
}

/** Every scene, in the order a match goes. */
export const SCENES = [
  "ready_check",
  "ready_check_refill",
  "voided_ready_check",
  "captain_phase",
  "captain_checkin",
  "player_draft",
  "player_draft_sub_open",
  "player_draft_sub_approval",
  "player_draft_sub_naming",
  "coinflip",
  "champion_draft",
  "champion_draft_swap_pending",
  "lobby_code",
  "lobby_code_failed",
  "in_progress_api_lobby",
  "in_progress_api_started",
  "in_progress",
  "in_progress_sub_offered",
  "in_progress_early_leave",
  "awaiting_confirmation",
  "awaiting_confirmation_scoreboard",
  "disputed",
  "completed",
  "scrim_captain_claim",
  "scrim_coinflip",
  "scrim_ready_to_draft",
  "scrim_champion_draft",
  "scrim_drafted",
] as const;

export type Scene = (typeof SCENES)[number];

export const VIEWERS: readonly Viewer[] = ["captain", "player", "spectator"];
