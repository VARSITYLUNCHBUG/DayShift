import { useState } from "react";

import { cn } from "../lib/cn";
import { initials } from "../lib/format";
import type { TeamKey } from "./team";
import { TEAM_CLASS } from "./team";
import { Glyphs } from "./Glyphs";

const SIZE = {
  sm: "size-6.5 border-2",
  md: "size-10 border-3",
  lg: "size-14 border-3",
} as const;

interface Props {
  /** The hero's name, for the initials when the art is missing. */
  hero: string;
  /** The art (the repo's pack under /static/hero-art/). */
  src?: string | null;
  size?: keyof typeof SIZE;
  /** The ring takes the team's colour inside a match. */
  team?: TeamKey | null;
  /** A cream halo marks you. */
  isYou?: boolean;
  /** Greyed with a cross (dead on the replay map). */
  isDead?: boolean;
  className?: string;
}

/** A round hero portrait in a ring. Decorative: say the hero's name in text or aria-label. */
export function Portrait({ hero, src, size = "md", team, isYou = false, isDead = false, className }: Props) {
  const [broken, setBroken] = useState<string | null>(null);
  const showArt = src && src !== broken;
  return (
    <span
      aria-hidden="true"
      className={cn(
        "relative inline-flex shrink-0 items-center justify-center overflow-hidden rounded-full bg-background",
        SIZE[size],
        isDead ? "border-line" : team ? TEAM_CLASS[team].border : "border-line",
        isYou && "ring-3 ring-foreground",
        className,
      )}
    >
      {showArt ? (
        <img
          src={src}
          alt=""
          loading="lazy"
          onError={() => setBroken(src)}
          className={cn("size-full object-cover object-top", isDead && "brightness-60 grayscale")}
        />
      ) : (
        <Glyphs text={initials(hero)} className="text-micro font-extrabold text-muted" />
      )}
      {isDead ? (
        <span className="absolute inset-0 flex items-center justify-center bg-background/50 font-extrabold text-foreground">×</span>
      ) : null}
    </span>
  );
}
