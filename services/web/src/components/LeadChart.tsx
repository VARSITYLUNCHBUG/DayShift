import { useId } from "react";

export interface LeadPoint {
  /** Seconds into the match. */
  t: number;
  /** The Hidden King's lead (negative when The Archmother leads). */
  lead: number;
}

interface Props {
  points: readonly LeadPoint[];
  /** What the chart says, in words, for screen readers: "Souls lead. Rook's Team led from 9:00." */
  label: string;
  /** The lead that touches the top or bottom edge; the biggest lead by default. */
  max?: number;
  /** Minute grid lines every this many minutes; 0 for none. */
  gridMinutes?: number;
  className?: string;
}

const W = 1000;
const H = 200;

/** Lead over time (C12): amber above the line when The Hidden King is ahead, blue below. */
export function LeadChart({ points, label, max, gridMinutes = 5, className }: Props) {
  const id = useId().replace(/:/g, "");
  const duration = Math.max(1, points.at(-1)?.t ?? 1);
  const top = max ?? Math.max(1, ...points.map((p) => Math.abs(p.lead)));
  const xy = points.map(
    (p) => [(p.t / duration) * W, H / 2 - (Math.max(-top, Math.min(top, p.lead)) / top) * (H / 2)] as const,
  );
  const line = xy.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const area = `M0,${H / 2} ${xy.map(([x, y]) => `L${x.toFixed(1)},${y.toFixed(1)}`).join(" ")} L${W},${H / 2} Z`;
  const steps = gridMinutes > 0 ? Math.floor(duration / 60 / gridMinutes) : 0;
  const grid = Array.from({ length: steps }, (_, i) => ((i + 1) * gridMinutes * 60 * W) / duration);
  return (
    <figure role="img" aria-label={label} className={className}>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" width="100%" height="100%" aria-hidden="true" className="block">
        <defs>
          <clipPath id={`${id}-top`}>
            <rect x="0" y="0" width={W} height={H / 2} />
          </clipPath>
          <clipPath id={`${id}-bottom`}>
            <rect x="0" y={H / 2} width={W} height={H / 2} />
          </clipPath>
        </defs>
        {grid.map((x) => (
          <line key={x} x1={x} y1="0" x2={x} y2={H} className="stroke-line" strokeWidth="1" vectorEffect="non-scaling-stroke" />
        ))}
        <path d={area} className="fill-team-hk" fillOpacity="0.32" clipPath={`url(#${id}-top)`} />
        <path d={area} className="fill-team-am" fillOpacity="0.32" clipPath={`url(#${id}-bottom)`} />
        <line
          x1="0"
          y1={H / 2}
          x2={W}
          y2={H / 2}
          className="stroke-line-strong"
          strokeWidth="1.5"
          vectorEffect="non-scaling-stroke"
        />
        <path
          d={line}
          fill="none"
          className="stroke-foreground"
          strokeWidth="2.5"
          strokeLinejoin="round"
          vectorEffect="non-scaling-stroke"
        />
      </svg>
    </figure>
  );
}
