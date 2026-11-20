// The result report: the one match action that isn't on the websocket, since it carries the
// scoreboard screenshot (league/web/api/report.py).
import { useMutation } from "@tanstack/react-query";

import type { MatchStatus, ReportDone, Team } from "../live/types";
import { postForm } from "./http";

/** Discord's upload limit, which the archive copy has to fit (league/domain/images.py). */
export const MAX_SCREENSHOT_BYTES = 20 * 1024 * 1024;
export const SCREENSHOT_TYPES = ["image/png", "image/jpeg", "image/webp"];

export interface Report {
  winner: Team;
  image: File;
  /** As typed: the server checks it. */
  deadlockMatchId?: string;
  mvp?: string | null;
  keys?: string[];
}

export function reportForm(report: Report): FormData {
  const form = new FormData();
  form.set("winner", report.winner);
  form.set("image", report.image, report.image.name);
  if (report.deadlockMatchId?.trim()) form.set("deadlock_match_id", report.deadlockMatchId.trim());
  if (report.mvp) form.set("mvp", report.mvp);
  for (const key of report.keys ?? []) form.append("key", key);
  return form;
}

/** The bot's thanks for each outcome (bot/handlers/results.py `process_report`). */
export const REPORT_THANKS: Partial<Record<MatchStatus, string>> = {
  awaiting_confirmation: "Thanks: the other captain can now confirm or dispute.",
  completed: "Thanks: both captains agree, and the result is posted.",
  disputed: "You and the other captain disagree, so staff will decide.",
};

/** POST /api/matches/{id}/report/. The new state arrives over the socket; this only says how
 * the report went. Errors carry the server's own words. */
export function useReport(matchId: string) {
  return useMutation({
    mutationFn: (report: Report) => postForm<ReportDone>(`/api/matches/${matchId}/report/`, reportForm(report)),
  });
}

/** Why this file can't be sent, before it is: the server checks again. */
export function screenshotProblem(file: File): string | null {
  if (file.size > MAX_SCREENSHOT_BYTES) return "That file is too large: the limit is 20 MB.";
  if (file.type && !SCREENSHOT_TYPES.includes(file.type)) return "That file isn't a PNG, JPEG or WebP image.";
  return null;
}
