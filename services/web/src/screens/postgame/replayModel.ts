// Where everyone is on the replay map at a moment (R09): between the 10-second samples in a
// straight line, or on the sample itself when motion is reduced (steps, not glides).
import type { Postgame } from "../../api/types";

export interface Placed {
  slot: number;
  /** 0..1 across and down the minimap. */
  x: number;
  y: number;
  dead: boolean;
}

/** One player's position at `t`, or null with no samples. */
export function positionAt(flat: readonly number[], stepS: number, t: number, glide: boolean): { x: number; y: number } | null {
  const frames = Math.floor(flat.length / 2);
  if (frames === 0) return null;
  const at = Math.max(0, t / stepS);
  const i0 = Math.min(frames - 1, Math.floor(at));
  const i1 = Math.min(frames - 1, i0 + 1);
  const k = glide ? at - i0 : 0;
  const x0 = flat[i0 * 2] ?? 0;
  const y0 = flat[i0 * 2 + 1] ?? 0;
  const x1 = flat[i1 * 2] ?? x0;
  const y1 = flat[i1 * 2 + 1] ?? y0;
  return { x: x0 + (x1 - x0) * k, y: y0 + (y1 - y0) * k };
}

/** Whether a slot is waiting to respawn at `t`. */
export function isDead(doc: Postgame, slot: number, t: number): boolean {
  return doc.deaths.some((death) => death.victim === slot && t >= death.t && t < death.t + death.respawn_s);
}

/** Everyone with a position at `t`, scaled to 0..1. */
export function placeAll(doc: Postgame, t: number, glide: boolean): Placed[] {
  const scale = doc.map.scale || 1000;
  const out: Placed[] = [];
  doc.players.forEach((line, index) => {
    const at = positionAt(doc.replay.positions[index] ?? [], doc.replay.step_s, t, glide);
    if (at) out.push({ slot: line.slot, x: at.x / scale, y: at.y / scale, dead: isDead(doc, line.slot, t) });
  });
  return out;
}
