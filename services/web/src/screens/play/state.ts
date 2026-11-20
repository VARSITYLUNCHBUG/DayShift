// Which Play board applies (A04 to A07): from your own `me` and the queue, both live.
import type { MeSnap, QueueSnap } from "../../api/live";

export type PlayState =
  | { kind: "match" }
  | { kind: "cooldown"; until: string }
  | { kind: "queued"; position: number | null; total: number | null }
  | { kind: "held"; until: string; position: number }
  | { kind: "closed" }
  | { kind: "idle" };

/** What the Play page shows. A match beats everything; then a cooldown (you can't queue); then
 * your place in the queue, a place held for you, or the open queue. */
export function playState(me: MeSnap, queue: QueueSnap | undefined, nowMs: number): PlayState {
  if (me.match) return { kind: "match" };
  if (me.cooldown && Date.parse(me.cooldown.until) > nowMs) return { kind: "cooldown", until: me.cooldown.until };
  if (me.queue.in_queue) {
    const place = me.queue.place;
    return { kind: "queued", position: place?.position ?? me.queue.position, total: place?.total ?? null };
  }
  const held = me.queue.place?.held_until;
  if (held && Date.parse(held) > nowMs && me.queue.place) return { kind: "held", until: held, position: me.queue.place.position };
  if (queue && !queue.open) return { kind: "closed" };
  return { kind: "idle" };
}

/** "4 more to start", "Starting now". */
export function moreToStart(queue: Pick<QueueSnap, "count" | "size">): string {
  const left = Math.max(0, queue.size - queue.count);
  return left === 0 ? "Starting now" : `${left} more to start`;
}

/** Why a cooldown started, as its eyebrow. */
export const COOLDOWN_REASON: Record<string, string> = {
  missed_ready: "Missed ready check",
  dodge: "Left before the match",
  leaver: "Left a match early",
  false_report: "Reported a wrong result",
  manual: "Cooldown from staff",
};
