// Words and numbers the pages outside the match room share.
import type { MatchStatus, Side, Team } from "../../api/types";
import { number } from "../../lib/format";

/** What a match is doing, in a list or chip: "Hero draft", "In game", "Finished". */
export const STATUS_LABEL: Record<MatchStatus, string> = {
  ready_check: "Ready check",
  captain_phase: "Captain vote",
  captain_checkin: "Captain check-in",
  player_draft: "Player draft",
  coinflip: "Sides",
  champion_draft: "Hero draft",
  lobby_code: "Lobby",
  in_progress: "In game",
  awaiting_confirmation: "Result in",
  disputed: "Disputed",
  completed: "Finished",
  voided: "Cancelled",
  captain_claim: "Captains",
  ready_to_draft: "Sides",
  drafted: "Drafted",
};

/** Statuses whose match is over: the record and postgame, not the room. */
export const FINISHED: ReadonlySet<MatchStatus> = new Set<MatchStatus>(["completed", "voided", "drafted"]);

/** 38021 → "38.0k", 238400 → "238.4k", 950 → "950". */
export function compact(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}m`;
  if (abs >= 1_000) return `${(value / 1_000).toFixed(1)}k`;
  return number(Math.round(value));
}

/** Seconds as a game clock: 1872 → "31:12", 62 → "1:02". */
export function gameClock(seconds: number): string {
  const whole = Math.max(0, Math.round(seconds));
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor((whole % 3600) / 60);
  const ss = String(whole % 60).padStart(2, "0");
  return hours > 0 ? `${hours}:${String(minutes).padStart(2, "0")}:${ss}` : `${minutes}:${ss}`;
}

/** "No. 413". */
export function matchNo(id: string | number): string {
  return `No. ${id}`;
}

export const SIDE_NAME: Record<Side, string> = { hk: "The Hidden King", am: "The Archmother" };

/** The side a team played, from a match's sides; null before the coinflip. */
export function sideOf(sides: { A: Side | null; B: Side | null }, team: Team | null): Side | null {
  return team ? sides[team] : null;
}

/** "Rook's Team", or the captain-less fallback. */
export function teamLabel(captain: string | null | undefined, team: Team): string {
  return captain ? `${captain}'s Team` : `Team ${team}`;
}

/** 0.706 → "71%"; null → "–". */
export function share(value: number | null | undefined): string {
  return value === null || value === undefined ? "–" : `${Math.round(value * 100)}%`;
}

/** The hero art in the repo's pack, by slug. */
export function heroArt(slug: string | null | undefined): string | null {
  return slug ? `/static/hero-art/${slug}.webp` : null;
}

/** A rating move for screen readers and text: "up 17", "down 15", "no change". */
export function moveWords(delta: number): string {
  if (delta > 0) return `up ${number(delta)}`;
  if (delta < 0) return `down ${number(-delta)}`;
  return "no change";
}

/** "1st", "2nd", "3rd", "11th". */
export function ordinal(n: number): string {
  const tens = n % 100;
  if (tens >= 11 && tens <= 13) return `${n}th`;
  return `${n}${["th", "st", "nd", "rd"][n % 10] ?? "th"}`;
}
