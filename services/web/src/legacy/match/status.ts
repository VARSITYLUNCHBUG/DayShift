// What each match status is called and which phase of the match it belongs to.
import type { MatchKind, MatchStatus } from "../../live/types";

export const STATUS_LABEL: Record<MatchStatus, string> = {
  ready_check: "Ready check",
  captain_phase: "Captain vote",
  player_draft: "Player draft",
  coinflip: "Coinflip",
  champion_draft: "Hero draft",
  lobby_code: "Lobby",
  in_progress: "In game",
  awaiting_confirmation: "Confirming result",
  disputed: "Disputed",
  completed: "Finished",
  voided: "Cancelled",
  captain_claim: "Claim captain",
  ready_to_draft: "Ready to draft",
  drafted: "Drafted",
};

export type StatusTone = "default" | "accent" | "success" | "warning" | "danger";

export const STATUS_TONE: Record<MatchStatus, StatusTone> = {
  ready_check: "success",
  captain_phase: "accent",
  player_draft: "accent",
  coinflip: "accent",
  champion_draft: "accent",
  lobby_code: "accent",
  in_progress: "success",
  awaiting_confirmation: "warning",
  disputed: "warning",
  completed: "default",
  voided: "danger",
  captain_claim: "accent",
  ready_to_draft: "accent",
  drafted: "default",
};

export const RANKED_PHASES = [
  "Ready",
  "Captains",
  "Players",
  "Coinflip",
  "Heroes",
  "Lobby",
  "Game",
] as const;
export const SCRIM_PHASES = ["Captains", "Coinflip", "Heroes"] as const;

/** Index into the kind's phases; past the last one means every phase is done. */
const RANKED_PHASE: Record<MatchStatus, number> = {
  ready_check: 0,
  captain_phase: 1,
  player_draft: 2,
  coinflip: 3,
  champion_draft: 4,
  lobby_code: 5,
  in_progress: 6,
  awaiting_confirmation: 6,
  disputed: 6,
  completed: 7,
  voided: -1,
  // Scrim statuses never show on a ranked match; placed where they'd fit.
  captain_claim: 1,
  ready_to_draft: 3,
  drafted: 5,
};

const SCRIM_PHASE: Record<MatchStatus, number> = {
  captain_claim: 0,
  ready_to_draft: 1,
  coinflip: 1,
  champion_draft: 2,
  drafted: 3,
  completed: 3,
  voided: -1,
  ready_check: 0,
  captain_phase: 0,
  player_draft: 0,
  lobby_code: 3,
  in_progress: 3,
  awaiting_confirmation: 3,
  disputed: 3,
};

export function phasesFor(kind: MatchKind): readonly string[] {
  return kind === "scrim" ? SCRIM_PHASES : RANKED_PHASES;
}

/** -1 when the match was cancelled. */
export function phaseIndex(kind: MatchKind, status: MatchStatus): number {
  return (kind === "scrim" ? SCRIM_PHASE : RANKED_PHASE)[status];
}
