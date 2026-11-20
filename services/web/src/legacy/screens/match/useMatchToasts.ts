// Toasts the match page raises from snapshot changes rather than from a message of their own
// (plan correction 1): the server never says "teams picked", the snapshot just moves on.
import { useEffect, useRef } from "react";

import { notify } from "../../components/toast";
import { teamName } from "../../lib/format";
import { usePlayerId } from "../../../live/hooks";
import type { MatchSnap } from "../../../live/types";

/** What this tab has already toasted, so a remount or a repeated snapshot doesn't toast twice. */
const toasted = new Set<string>();

/** For tests: forget what has been toasted. */
export function resetMatchToasts(): void {
  toasted.clear();
}

/** Runs `show` the first time `key` comes up in this tab. */
export function toastOnce(key: string, show: () => void): void {
  if (toasted.has(key)) return;
  toasted.add(key);
  show();
}

/** Raises the match's one-off toasts as its snapshots arrive. Only for changes seen live: the
 * first snapshot after opening the page toasts nothing.
 *
 * - **Teams picked**: the player draft has just ended and the viewer is on a team.
 * - **Sub found** / **Sub refused** / **Sub cancelled**: a sub request has just ended (seen in
 *   `subs_done`). Not for one you came in through: "You're in" (useMeToasts) covers that.
 * - **Early leave agreed** / **not agreed**: a reported early leave was answered. Agreed voids
 *   the match; refused or unanswered, it goes to staff.
 *
 * "You're in" lives in useMeToasts rather than here: accepting an offer opens the match page
 * with you already on the roster, so this page never sees you join. */
export function useMatchToasts(match: MatchSnap | null | undefined): void {
  const myId = usePlayerId();
  const previous = useRef<MatchSnap | null>(null);

  useEffect(() => {
    if (!match) {
      previous.current = null;
      return;
    }
    const before = previous.current?.id === match.id ? previous.current : null;
    previous.current = match;
    if (!before) return;
    teamsPicked(before, match);
    subsEnded(before, match, myId);
    earlyLeaveAnswered(before, match);
  }, [match, myId]);
}

function teamsPicked(before: MatchSnap, match: MatchSnap): void {
  const team = match.viewer.is_player ? match.viewer.team : null;
  if (before.status !== "player_draft" || match.status === "player_draft" || match.status === "voided" || !team) return;
  toastOnce(`teams:${match.id}`, () => notify.success("Teams picked", `You're on ${teamName(match.team_names, team)}`));
}

function subsEnded(before: MatchSnap, match: MatchSnap, myId: string | null): void {
  const seen = new Set(before.subs_done.map((s) => s.id));
  for (const done of match.subs_done) {
    if (seen.has(done.id) || done.joined_id === myId) continue;
    const key = `sub:${done.id}`;
    if (done.status === "filled" && done.joined_name) {
      const text = done.reason === "sub_out" ? `${done.joined_name} is in for ${done.leaving_name}` : `${done.joined_name} joined`;
      toastOnce(key, () => notify.success("Sub found", text));
    } else if (done.status === "rejected") {
      toastOnce(key, () => notify.warning("Sub refused", `${done.leaving_name} stays in`));
    } else if (done.status === "cancelled") {
      toastOnce(key, () => notify.info("Sub cancelled", `${done.leaving_name} stays in`));
    }
    // Expired: the match restarts or is cancelled, and its page says so.
  }
}

function earlyLeaveAnswered(before: MatchSnap, match: MatchSnap): void {
  const claim = before.early_leave.pending;
  if (!claim || match.early_leave.pending) return;
  const key = `early:${match.id}:${claim.deadline_at}`;
  if (match.status === "voided") {
    toastOnce(key, () => notify.success("Early leave agreed", "Match cancelled with no rating change"));
  } else if (match.status === "in_progress") {
    toastOnce(key, () => notify.warning("Early leave not agreed", "Staff will decide"));
  }
}
