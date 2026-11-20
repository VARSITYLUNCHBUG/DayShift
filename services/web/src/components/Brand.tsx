import { Link } from "react-router";

import { cn } from "../lib/cn";

// The DayShift identity, drawn inline so it follows the theme: the mark is three kit stripes on
// the 14 degree lean (bubblegum, cream, bubblegum) and the wordmark is artwork from
// docs/assets/brand/dayshift-lockup-*.svg, filled with the text colour.

const WORDMARK =
  "M 0 0 H 30 Q 52 0 52 22 V 78 Q 52 100 30 100 H 0 Z M 22 22 V 78 H 26 Q 30 78 30 74 V 26 Q 30 22 26 22 Z M 60 100 V 26 Q 60 0 86 0 Q 112 0 112 26 V 100 H 90 V 68 H 82 V 100 Z M 82 46 H 90 V 27 Q 90 22 86 22 Q 82 22 82 27 Z M 120 0 H 142 V 34 Q 142 40 146 40 Q 150 40 150 34 V 0 H 172 V 40 Q 172 62 157 62 V 100 H 135 V 62 Q 120 62 120 40 Z M 232 0 V 22 H 205 Q 202 22 202 25 V 36 Q 202 39 205 39 H 218 Q 232 39 232 53 V 86 Q 232 100 218 100 H 180 V 78 H 207 Q 210 78 210 75 V 64 Q 210 61 207 61 H 194 Q 180 61 180 47 V 14 Q 180 0 194 0 Z M 240 0 H 262 V 39 H 270 V 0 H 292 V 100 H 270 V 61 H 262 V 100 H 240 Z M 300 0 H 322 V 100 H 300 Z M 330 0 H 380 V 22 H 352 V 39 H 374 V 61 H 352 V 100 H 330 Z M 388 0 H 440 V 22 H 425 V 100 H 403 V 22 H 388 Z";

interface MarkProps {
  /** Height in pixels. */
  size?: number;
  className?: string;
}

/** The mark alone: decorative, so whatever it sits in carries the name. */
export function Mark({ size = 28, className }: MarkProps) {
  return (
    <svg
      viewBox="0 0 112.93 100"
      height={size}
      width={(size * 112.93) / 100}
      aria-hidden="true"
      focusable="false"
      className={cn("shrink-0", className)}
    >
      <g transform="translate(24.93 0) skewX(-14)">
        <rect x="0" width="22" height="100" className="fill-brand" />
        <rect x="33" width="22" height="100" className="fill-foreground" />
        <rect x="66" width="22" height="100" className="fill-brand" />
      </g>
    </svg>
  );
}

/** Mark and wordmark together, as one image named "DayShift" (hidden when `decorative`, inside
 * something that already says it). */
export function Lockup({ size = 24, className, decorative = false }: MarkProps & { decorative?: boolean }) {
  return (
    <svg
      viewBox="0 0 585.93 100"
      height={size}
      width={(size * 585.93) / 100}
      {...(decorative ? { "aria-hidden": true } : { role: "img", "aria-label": "DayShift" })}
      focusable="false"
      className={cn("shrink-0", className)}
    >
      <g transform="translate(24.93 0) skewX(-14)">
        <rect x="0" width="22" height="100" className="fill-brand" />
        <rect x="33" width="22" height="100" className="fill-foreground" />
        <rect x="66" width="22" height="100" className="fill-brand" />
        <g transform="translate(121 0)">
          <path fillRule="evenodd" className="fill-foreground" d={WORDMARK} />
        </g>
      </g>
    </svg>
  );
}

/** The lockup as the home link in a top bar. */
export function HomeLink({ size = 24, to = "/" }: { size?: number; to?: string }) {
  return (
    <Link
      to={to}
      aria-label="DayShift, home"
      className="flex min-h-11 shrink-0 items-center rounded-full"
    >
      <Lockup size={size} decorative />
    </Link>
  );
}
