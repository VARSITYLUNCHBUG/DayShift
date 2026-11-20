// The result report: the one match action that goes over HTTP rather than the socket, since it
// can carry the scoreboard screenshot (league/web/api/report.py). The new state arrives over the
// socket; this only says how the report went.
import { useMutation } from "@tanstack/react-query";

import { csrfToken, HttpError } from "../api/http";
import type { ReportDone, Team } from "../live/protocol.gen";

/** Discord's upload limit, which the archive copy has to fit (league/domain/images.py). */
export const MAX_SCREENSHOT_BYTES = 20 * 1024 * 1024;
export const SCREENSHOT_TYPES = ["image/png", "image/jpeg", "image/webp"];

export interface Report {
  winner: Team;
  /** Required, as on Discord: the server checks it (numbers only, up to 18 digits). */
  deadlockMatchId: string;
  screenshot?: File | null;
  mvp?: string | null;
  keys?: readonly string[];
}

/** The multipart form the endpoint reads: winner, deadlock_match_id, screenshot, mvp, keys. */
export function reportForm(report: Report): FormData {
  const form = new FormData();
  form.set("winner", report.winner);
  form.set("deadlock_match_id", report.deadlockMatchId.trim());
  if (report.screenshot) form.set("screenshot", report.screenshot, report.screenshot.name);
  if (report.mvp) form.set("mvp", report.mvp);
  for (const key of report.keys ?? []) if (key !== report.mvp) form.append("keys", key);
  return form;
}

const FAILED_TEXT: Record<number, string> = {
  401: "You're signed out. Sign in again to carry on.",
  404: "That match isn't here any more.",
  413: "That file is too large: the limit is 20 MB.",
};
const SERVER_TEXT = "Something went wrong on our side. Please try again.";

/** POST /api/matches/{id}/report/. A refusal throws with the server's own sentence. */
export async function sendReport(matchId: string, report: Report): Promise<ReportDone> {
  let response: Response;
  try {
    response = await fetch(`/api/matches/${matchId}/report/`, {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken(), Accept: "application/json" },
      body: reportForm(report),
    });
  } catch {
    throw new HttpError(0, "Couldn't reach the server. Check your connection and try again.");
  }
  const answer: unknown = await response.json().catch(() => null);
  if (response.ok) return answer as ReportDone;
  const refusal = answer && typeof answer === "object" && "refusal" in answer ? answer.refusal : null;
  throw new HttpError(
    response.status,
    typeof refusal === "string" && refusal ? refusal : (FAILED_TEXT[response.status] ?? SERVER_TEXT),
  );
}

export function useReport(matchId: string) {
  return useMutation({ mutationFn: (report: Report) => sendReport(matchId, report) });
}

/** Why this file can't be sent, before it is: the server checks again. */
export function screenshotProblem(file: File): string | null {
  if (file.size > MAX_SCREENSHOT_BYTES) return "That file is too large: the limit is 20 MB.";
  if (file.type && !SCREENSHOT_TYPES.includes(file.type)) return "That file isn't a PNG, JPEG or WebP image.";
  return null;
}

/** The bot's own check, so the field can say so before sending. */
export function matchIdProblem(raw: string): string | null {
  const cleaned = raw.trim();
  const help = "It's on the scoreboard after the game, and in the match history.";
  if (!cleaned) return `Enter the Deadlock match ID. ${help}`;
  if (!/^\d{1,18}$/.test(cleaned) || Number(cleaned) <= 0) return `The Deadlock match ID is numbers only. ${help}`;
  return null;
}
