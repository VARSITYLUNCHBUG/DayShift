import { Avatar as HeroAvatar } from "@heroui/react";

import { cn } from "../lib/cn";
import { initials } from "../lib/format";
import type { TeamKey } from "./team";
import { TEAM_CLASS } from "./team";

const SIZE = {
  sm: "size-8 text-micro",
  md: "size-9 text-caption",
  lg: "size-10 text-caption",
  xl: "size-14 text-lead",
} as const;

interface Props {
  name: string;
  /** The player's picture (their Discord avatar, served from our own origin). */
  src?: string | null;
  size?: keyof typeof SIZE;
  /** Inside a match the fallback takes the team's fill. */
  team?: TeamKey | null;
  /** The ready check: a cream tick when ready, dimmed while not yet. Leave out elsewhere. */
  ready?: boolean | null;
  className?: string;
}

/** A player's round picture, initials while it loads or when there isn't one. Decorative: the name
 * is always in the text next to it. */
export function Avatar({ name, src, size = "lg", team, ready = null, className }: Props) {
  // Not ready yet: the picture fades and the initials go muted on a plain fill. Fading the
  // initials themselves would take them below text contrast.
  const waiting = ready === false;
  const fill = team && !waiting ? TEAM_CLASS[team].fill : waiting ? "bg-raised text-muted" : "bg-raised text-foreground";
  return (
    <span className={cn("relative inline-flex shrink-0", className)}>
      <HeroAvatar
        aria-hidden="true"
        className={cn("rounded-full border-2 border-background", SIZE[size], team && !waiting ? TEAM_CLASS[team].fill : "bg-raised")}
      >
        {src ? <HeroAvatar.Image src={src} alt="" className={cn(waiting && "opacity-50")} /> : null}
        <HeroAvatar.Fallback
          className={cn("font-extrabold", fill)}
          delayMs={src ? 600 : 0}
        >
          {initials(name)}
        </HeroAvatar.Fallback>
      </HeroAvatar>
      {ready ? (
        <span
          role="img"
          aria-label="ready"
          className="absolute -right-1 -bottom-1 flex size-4.5 items-center justify-center rounded-full bg-foreground text-background"
        >
          <svg viewBox="0 0 24 24" width="11" height="11" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="4">
            <path d="M20 6 9 17l-5-5" />
          </svg>
        </span>
      ) : null}
    </span>
  );
}
