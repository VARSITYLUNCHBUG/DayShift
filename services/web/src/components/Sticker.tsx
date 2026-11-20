import type { ReactNode } from "react";

import { cn } from "../lib/cn";
import type { TeamKey } from "./team";
import { TEAM_CLASS } from "./team";

export type StickerTone = "brand" | "cream" | "raised" | "danger" | "ok" | TeamKey;

const TONE: Record<StickerTone, string> = {
  brand: "bg-brand text-brand-ink",
  cream: "bg-foreground text-background",
  raised: "bg-raised text-foreground",
  danger: "bg-danger text-danger-foreground",
  ok: "bg-ok text-background",
  hk: TEAM_CLASS.hk.fill,
  am: TEAM_CLASS.am.fill,
};

const TILT = {
  left: "-rotate-4",
  slight: "-rotate-2",
  right: "rotate-6",
  none: "",
} as const;

interface StickerProps {
  children: ReactNode;
  tone?: StickerTone;
  tilt?: keyof typeof TILT;
  size?: "sm" | "md";
  className?: string;
}

/** A sticker: a tilted pill with the hard drop (Doors open, Banned, Won, GG). Bubblegum is for
 * DayShift's own moments only, never a team. */
export function Sticker({ children, tone = "brand", tilt = "left", size = "md", className }: StickerProps) {
  return (
    <span
      className={cn(
        "inline-block rounded-full font-extrabold whitespace-nowrap shadow-sticker",
        size === "md" ? "px-2.5 py-0.5 text-caption" : "px-1.75 py-0.5 text-micro leading-none",
        TONE[tone],
        TILT[tilt],
        className,
      )}
    >
      {children}
    </span>
  );
}

/** A clan tag (OWL, KRK), before every name: the team's colour inside a match, neutral outside. */
export function Tag({ children, team }: { children: ReactNode; team?: TeamKey | null }) {
  return (
    <Sticker tone={team ?? "raised"} size="sm">
      {children}
    </Sticker>
  );
}

/** A small count: unread messages, waiting notices. */
export function Badge({ children, label }: { children: ReactNode; label?: string }) {
  return (
    <span
      aria-label={label}
      className="inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-brand px-1.5 text-micro font-extrabold text-brand-ink"
    >
      {children}
    </span>
  );
}
