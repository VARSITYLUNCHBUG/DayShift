// The room's toasts (I09): news raised from snapshot changes, since the server never says "teams
// picked"; the snapshot just moves on. Only for changes seen live: opening the page toasts
// nothing, and each one shows once per tab.
import { useEffect, useRef } from "react";

import { notify } from "../../components/toast";
import { signed } from "../../lib/format";
import type { MatchSnap } from "../../live/protocol.gen";
import { nameOf, teamPlayers } from "../../match/model";

const toasted = new Set<string>();

/** For tests: forget what has been toasted. */
export function resetMatchToasts(): void {
  toasted.clear();
}

function once(key: string, show: () => void): void {
  if (toasted.has(key)) return;
  toasted.add(key);
  show();
}

export function useMatchToasts(match: MatchSnap | undefined, myId: string | null): void {
  const previous = useRef<MatchSnap | null>(null);
  useEffect(() => {
    if (!match) {
      previous.current = null;
      return;
    }
    const before = previous.current?.id === match.id ? previous.current : null;
    previous.current = match;
    if (!before) return;
    teamsPicked(before, match, myId);
    subsEnded(before, match, myId);
    swapAnswered(before, match);
    earlyLeaveAnswered(before, match);
    resultIn(before, match, myId);
  }, [match, myId]);
}

function teamsPicked(before: MatchSnap, match: MatchSnap, myId: string | null): void {
  const team = match.viewer.is_player ? match.viewer.team : null;
  if (before.status !== "player_draft" || match.status === "player_draft" || match.status === "voided" || !team) return;
  const mates = teamPlayers(match, team)
    .filter((p) => p.id !== myId)
    .map((p) => p.name)
    .join(", ");
  once(`teams:${match.id}`, () => notify.info("Teams picked", `${nameOf(match, team)} is set${mates ? `: ${mates}` : ""}.`));
}

function subsEnded(before: MatchSnap, match: MatchSnap, myId: string | null): void {
  const seen = new Set(before.subs_done.map((s) => s.id));
  for (const done of match.subs_done) {
    if (seen.has(done.id) || done.joined_id === myId) continue;
    const key = `sub:${done.id}`;
    if (done.status === "filled" && done.joined_name) {
      once(key, () =>
        notify.success(
          "Sub found",
          done.reason === "sub_out" ? `${done.joined_name} is in for ${done.leaving_name}.` : `${done.joined_name} joined.`,
        ),
      );
    } else if (done.status === "rejected") {
      once(key, () => notify.info("Sub declined", `${done.leaving_name} stays in.`));
    } else if (done.status === "cancelled") {
      once(key, () => notify.info("Sub cancelled", `${done.leaving_name} stays in.`));
    }
  }
}

function swapAnswered(before: MatchSnap, match: MatchSnap): void {
  const offer = before.swap.pending;
  if (!offer || match.swap.pending?.id === offer.id) return;
  const moved =
    match.players.find((p) => p.id === offer.give_id)?.team !== before.players.find((p) => p.id === offer.give_id)?.team;
  once(`swap:${match.id}:${offer.id}`, () =>
    moved
      ? notify.success("Swap done", `${offer.give_name} and ${offer.take_name} swapped teams.`)
      : notify.info("No swap", `${offer.give_name} and ${offer.take_name} stay put.`),
  );
}

function earlyLeaveAnswered(before: MatchSnap, match: MatchSnap): void {
  const claim = before.early_leave.pending;
  if (!claim || match.early_leave.pending) return;
  const key = `early:${match.id}:${claim.deadline_at}`;
  if (match.status === "voided") once(key, () => notify.success("Early leave agreed", "Match cancelled with no rating change."));
  else if (match.status === "in_progress") once(key, () => notify.info("Early leave not agreed", "Staff will decide."));
}

function resultIn(before: MatchSnap, match: MatchSnap, myId: string | null): void {
  if (before.status === "completed" || match.status !== "completed" || !match.result.winner) return;
  const delta = myId ? match.result.deltas[myId] : undefined;
  once(`result:${match.id}`, () =>
    notify.success(
      "Result confirmed",
      `${nameOf(match, match.result.winner ?? "A")} won No. ${match.id}.${delta !== undefined ? ` ${match.rating_label} ${signed(delta)}.` : ""}`,
    ),
  );
}
