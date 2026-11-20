import type { SVGProps } from "react";

import { EXTRA_GLYPHS } from "./icons/extra";
import { GLYPHS } from "./icons/glyphs";

const ALL = { ...GLYPHS, ...EXTRA_GLYPHS };

export type IconName = keyof typeof ALL;

interface Props extends Omit<SVGProps<SVGSVGElement>, "name"> {
  name: IconName;
  /** Pixels; 20 by default. */
  size?: number;
  /** Only for an icon that means something on its own. Decorative icons (the default) are
   * hidden from screen readers: the control around them carries the name. */
  label?: string;
}

/** A DayShift icon: 24 x 24 grid, 2px round strokes in the current text colour. */
export function Icon({ name, size = 20, label, ...rest }: Props) {
  const a11y = label ? { role: "img", "aria-label": label } : { "aria-hidden": true as const };
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      focusable="false"
      {...a11y}
      {...rest}
    >
      {ALL[name]}
    </svg>
  );
}

export const ICON_NAMES = Object.keys(ALL) as IconName[];
