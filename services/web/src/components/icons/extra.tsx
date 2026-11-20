// Glyphs the brand icon set doesn't have, drawn the same way (24 x 24, 2px round strokes). The
// first four come from the wireframe's icon() in design/dayshift/wireframe/ds.py.
import type { ReactNode } from "react";

export const EXTRA_GLYPHS = {
  alert: (
    <>
      <path d="M12 3 2 21h20z" />
      <path d="M12 10v5" />
      <circle cx="12" cy="18" r="0.6" />
    </>
  ),
  dice: (
    <>
      <rect x="3" y="3" width="18" height="18" rx="4" />
      <circle cx="8.5" cy="8.5" r="1" />
      <circle cx="15.5" cy="15.5" r="1" />
      <circle cx="15.5" cy="8.5" r="1" />
      <circle cx="8.5" cy="15.5" r="1" />
    </>
  ),
  flag: (
    <>
      <path d="M5 21V4" />
      <path d="M5 4h11l-2 4 2 4H5" />
    </>
  ),
  clock: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </>
  ),
  sun: (
    <>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </>
  ),
  moon: (
    <>
      <path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z" />
    </>
  ),
} satisfies Record<string, ReactNode>;
