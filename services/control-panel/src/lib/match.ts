import type { MatchScript } from "../api";

/** Match status vocabulary from `league/domain/engine.py`, for labels and the advance menu. */

export const RANKED_FLOW = [
  "ready_check",
  "captain_phase",
  "captain_checkin",
  "player_draft",
  "coinflip",
  "team_confirm",
  "champion_draft",
  "lobby_code",
  "in_progress",
  "awaiting_confirmation",
  "completed",
] as const;

export const TERMINAL = new Set(["completed", "voided", "drafted"]);

/** Between the player draft and the game, captains can swap players (`league/services/swaps.py`). */
export const SWAPPABLE = new Set(["coinflip", "team_confirm", "champion_draft", "lobby_code"]);

export type ChipColor = "default" | "accent" | "success" | "warning" | "danger";

// The labels `league.models.MatchStatus` gives each status.
const STATUS_LABELS: Record<string, string> = {
  ready_check: "Ready check",
  captain_phase: "Captain vote",
  captain_checkin: "Captain check-in",
  player_draft: "Player draft",
  coinflip: "Captain coinflip",
  team_confirm: "Captains confirm teams",
  champion_draft: "Champion draft",
  lobby_code: "Lobby code",
  in_progress: "In progress",
  awaiting_confirmation: "Awaiting confirmation",
  disputed: "Disputed",
  completed: "Completed",
  voided: "Voided",
  captain_claim: "Scrim: claiming sides",
  ready_to_draft: "Scrim: ready to draft",
  drafted: "Scrim: drafted",
};

export function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status.replace(/_/g, " ");
}

export function statusColor(status: string): ChipColor {
  if (status === "completed") return "success";
  if (status === "voided" || status === "disputed") return "danger";
  if (status === "awaiting_confirmation" || status === "in_progress") return "warning";
  return "accent";
}

/** Statuses still ahead of `status` in the ranked flow (what "Advance to" can target). */
export function laterStatuses(status: string): string[] {
  const index = (RANKED_FLOW as readonly string[]).indexOf(status);
  return index < 0 ? [] : RANKED_FLOW.slice(index + 1);
}

/** Seconds until `deadlineAt` (ISO), or null without a deadline. Negative when overdue. */
export function secondsUntil(deadlineAt: string | null, now: number): number | null {
  if (!deadlineAt) return null;
  const at = Date.parse(deadlineAt);
  return Number.isNaN(at) ? null : Math.round((at - now) / 1000);
}

export function formatSeconds(seconds: number): string {
  const sign = seconds < 0 ? "-" : "";
  const abs = Math.abs(seconds);
  const m = Math.floor(abs / 60);
  const s = abs % 60;
  return `${sign}${m}:${String(s).padStart(2, "0")}`;
}

/** Split "a, b c" into slugs. */
export function parseList(text: string): string[] {
  return text
    .split(/[\s,]+/)
    .map((s) => s.trim())
    .filter(Boolean);
}

/** "step slug [team]" lines → champion script steps. */
export function parseChampionLines(text: string): NonNullable<MatchScript["champions"]> {
  const out: NonNullable<MatchScript["champions"]> = [];
  for (const line of text.split("\n")) {
    const [step, slug, team] = line.trim().split(/\s+/);
    if (!step || !slug || !/^\d+$/.test(step)) continue;
    out.push({ step: Number(step), slug, ...(team === "A" || team === "B" ? { team } : {}) });
  }
  return out;
}
