// The arithmetic behind the hand-rolled SVG charts: linear scales, extents, ticks and paths.
// Pure, so every chart's geometry is unit-tested without a DOM.

export type Point = readonly [number, number];

/** Maps a domain onto a range in a straight line. A flat domain maps everything to the middle of
 * the range, so a chart of one value still draws. */
export function linear(domain: readonly [number, number], range: readonly [number, number]): (value: number) => number {
  const [d0, d1] = domain;
  const [r0, r1] = range;
  if (d1 === d0) return () => (r0 + r1) / 2;
  const k = (r1 - r0) / (d1 - d0);
  return (value) => r0 + (value - d0) * k;
}

/** The smallest and largest of the values; [0, 0] for none. */
export function extent(values: readonly number[]): [number, number] {
  if (values.length === 0) return [0, 0];
  let low = Infinity;
  let high = -Infinity;
  for (const value of values) {
    if (value < low) low = value;
    if (value > high) high = value;
  }
  return [low, high];
}

/** A symmetric domain around zero that holds every value: for leads, so zero sits mid-chart. */
export function symmetric(values: readonly number[], floor = 1): [number, number] {
  const top = Math.max(floor, ...values.map((value) => Math.abs(value)));
  return [-top, top];
}

/** Widens a domain by a share of its span on both sides (or by `flat` when it has no span). */
export function pad(domain: readonly [number, number], share = 0.08, flat = 10): [number, number] {
  const [low, high] = domain;
  const span = high - low;
  const by = span === 0 ? flat : span * share;
  return [low - by, high + by];
}

/** Round numbers across a domain, about `count` of them: 1, 2 or 5 times a power of ten. */
export function ticks(low: number, high: number, count = 5): number[] {
  if (!(high > low) || count < 1) return [low];
  const raw = (high - low) / count;
  const power = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 5, 10].map((m) => m * power).find((s) => s >= raw) ?? 10 * power;
  const out: number[] = [];
  for (let value = Math.ceil(low / step) * step; value <= high + step * 1e-9; value += step) {
    out.push(Math.round(value / step) * step);
  }
  return out;
}

const fixed = (value: number) => (Math.round(value * 10) / 10).toString();

/** "M x,y L x,y …" through the points, to one decimal. Empty for no points. */
export function linePath(points: readonly Point[]): string {
  return points.map(([x, y], index) => `${index ? "L" : "M"}${fixed(x)},${fixed(y)}`).join(" ");
}

/** The area between the line and a baseline: down to `base`, along it and closed. */
export function areaPath(points: readonly Point[], base: number): string {
  const first = points[0];
  const last = points.at(-1);
  if (!first || !last) return "";
  const body = points.map(([x, y]) => `L${fixed(x)},${fixed(y)}`).join(" ");
  return `M${fixed(first[0])},${fixed(base)} ${body} L${fixed(last[0])},${fixed(base)} Z`;
}

/** The index of the value nearest to `target` in an ascending list (binary search). */
export function nearestIndex(sorted: readonly number[], target: number): number {
  if (sorted.length === 0) return -1;
  let low = 0;
  let high = sorted.length - 1;
  while (high - low > 1) {
    const mid = (low + high) >> 1;
    if ((sorted[mid] ?? 0) < target) low = mid;
    else high = mid;
  }
  const below = sorted[low] ?? 0;
  const above = sorted[high] ?? 0;
  return Math.abs(target - below) <= Math.abs(above - target) ? low : high;
}

/** The value at `t` on a series sampled at `times`, in a straight line between samples. */
export function interpolate(times: readonly number[], values: readonly number[], t: number): number {
  if (times.length === 0) return 0;
  const first = times[0] ?? 0;
  if (t <= first) return values[0] ?? 0;
  for (let i = 1; i < times.length; i++) {
    const t1 = times[i] ?? 0;
    if (t <= t1) {
      const t0 = times[i - 1] ?? 0;
      const v0 = values[i - 1] ?? 0;
      const v1 = values[i] ?? 0;
      return t1 === t0 ? v1 : v0 + ((t - t0) / (t1 - t0)) * (v1 - v0);
    }
  }
  return values.at(-1) ?? 0;
}
