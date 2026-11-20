// The timeline chart's geometry (R08): a lead over time on a fixed viewBox, with zero mid-chart.
import { areaPath, linear, linePath, symmetric } from "../../components/charts/scale";
import type { Point } from "../../components/charts/scale";

export const CHART_W = 1000;
export const CHART_H = 300;

export interface LeadGeometry {
  line: string;
  area: string;
  /** Seconds to x. */
  x: (t: number) => number;
  /** A lead to y. */
  y: (lead: number) => number;
  /** The biggest lead either way: the top and bottom edges. */
  top: number;
  /** Minute marks every five minutes, in x. */
  grid: { t: number; x: number }[];
}

export function leadGeometry(times: readonly number[], leads: readonly number[], duration: number): LeadGeometry {
  const end = Math.max(1, duration, times.at(-1) ?? 0);
  const [, top] = symmetric(leads);
  const x = linear([0, end], [0, CHART_W]);
  const y = linear([-top, top], [CHART_H, 0]);
  const points: Point[] = times.map((t, i) => [x(t), y(leads[i] ?? 0)]);
  const grid: { t: number; x: number }[] = [];
  for (let t = 300; t < end; t += 300) grid.push({ t, x: x(t) });
  return { line: linePath(points), area: areaPath(points, CHART_H / 2), x, y, top, grid };
}
