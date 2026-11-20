import type { ReactNode } from "react";

import { cn } from "../../lib/cn";
import { extent, linear, linePath, pad } from "./scale";
import type { Point } from "./scale";

export interface LinePoint {
  /** Where along: an index or a time. Ascending. */
  x: number;
  y: number;
}

export interface Guide {
  value: number;
  label: string;
}

interface Props {
  points: readonly LinePoint[];
  /** What the chart says, for screen readers: "Rating from 1,402 to 1,512 over 19 matches". */
  label: string;
  /** Dashed lines across at these values (tier thresholds). */
  guides?: readonly Guide[];
  /** Small captions under the chart, left and right ("Placed in Gold", "No. 413"). */
  start?: ReactNode;
  end?: ReactNode;
  className?: string;
}

const W = 1000;
const H = 240;
const INSET = 10;

/** The chart's geometry, separate from the drawing so it can be tested. */
export function lineGeometry(points: readonly LinePoint[], guides: readonly Guide[] = []) {
  const xs = points.map((p) => p.x);
  const ys = points.map((p) => p.y);
  const [x0, x1] = extent(xs);
  const yDomain = pad(extent([...ys, ...guides.map((g) => g.value)]));
  const x = linear([x0, x1], [INSET, W - INSET]);
  const y = linear(yDomain, [H - INSET, INSET]);
  const xy: Point[] = points.map((p) => [x(p.x), y(p.y)]);
  return { path: linePath(xy), last: xy.at(-1) ?? null, guideY: guides.map((g) => ({ ...g, y: y(g.value) })) };
}

/** A line over time in cream (C12): rating history and the like. Decorative SVG inside a
 * role=img figure that carries the words; pair it with a table for the numbers. */
export function LineChart({ points, label, guides = [], start, end, className }: Props) {
  const { path, last, guideY } = lineGeometry(points, guides);
  return (
    <figure className={cn("m-0 flex flex-col gap-2", className)}>
      <div role="img" aria-label={label} className="relative h-56 max-md:h-40">
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" width="100%" height="100%" aria-hidden="true" className="block overflow-visible">
          {guideY.map((guide) => (
            <line
              key={guide.label}
              x1="0"
              x2={W}
              y1={guide.y}
              y2={guide.y}
              className="stroke-line-strong"
              strokeDasharray="6 8"
              strokeWidth="1"
              vectorEffect="non-scaling-stroke"
            />
          ))}
          <path d={path} fill="none" className="stroke-foreground" strokeWidth="3" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
        </svg>
        {guideY.map((guide) => (
          <span
            key={guide.label}
            aria-hidden="true"
            className="absolute right-0 -translate-y-full pb-0.5 text-micro font-bold text-muted tabular-nums"
            style={{ top: `${((guide.y / H) * 100).toFixed(2)}%` }}
          >
            {guide.label}
          </span>
        ))}
        {last ? (
          <span
            aria-hidden="true"
            className="absolute size-3 -translate-1/2 rounded-full bg-foreground"
            style={{ left: `${((last[0] / W) * 100).toFixed(2)}%`, top: `${((last[1] / H) * 100).toFixed(2)}%` }}
          />
        ) : null}
      </div>
      {start || end ? (
        <figcaption className="flex justify-between gap-4 text-micro font-semibold text-muted">
          <span>{start}</span>
          <span>{end}</span>
        </figcaption>
      ) : null}
    </figure>
  );
}
