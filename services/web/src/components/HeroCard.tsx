import { useState } from "react";
import type { ReactNode } from "react";

import { cn } from "../lib/cn";
import { initials } from "../lib/format";
import { Sticker } from "./Sticker";
import type { TeamKey } from "./team";
import { TEAM_CLASS } from "./team";
import { Glyphs } from "./Glyphs";

/** free: pickable · selected: your choice, not locked yet · banned · hk / am: picked by that side
 * · locked: your team's locked-in pick. */
export type HeroState = "free" | "selected" | "banned" | "hk" | "am" | "locked";

const BORDER: Record<HeroState, string> = {
  free: "border-line",
  selected: "border-foreground",
  banned: "border-line",
  hk: TEAM_CLASS.hk.line,
  am: TEAM_CLASS.am.line,
  locked: "border-team-hk",
};

const TAG_TONE = {
  muted: "text-muted",
  danger: "text-danger",
  hk: TEAM_CLASS.hk.text,
  am: TEAM_CLASS.am.text,
} as const;

export interface HeroCardProps {
  name: string;
  /** Card art (280 x 380). Initials stand in when it's missing or won't load. */
  art?: string | null;
  state?: HeroState;
  /** The line under the name: "Pike wants her", "Vesper's Team", "Banned". */
  tag?: ReactNode;
  tagTone?: keyof typeof TAG_TONE;
  /** Teammates' initials who wished for this hero ("PK"). */
  wishes?: string | null;
  /** Locked by which side, for the Locked sticker's colour. */
  lockedBy?: TeamKey;
  className?: string;
}

/** A hero's card: art, name and a line. Presentational; HeroGrid makes it pickable. */
export function HeroCard({ name, art, state = "free", tag, tagTone = "muted", wishes, lockedBy = "hk", className }: HeroCardProps) {
  const [broken, setBroken] = useState<string | null>(null);
  const dim = state === "banned" || state === "hk" || state === "am";
  const lifted = state === "selected" || state === "locked";
  // The stickers are drawn, not written, so the line says the state in words when no tag does.
  const line = tag ?? (state === "banned" ? "Banned" : state === "locked" ? "Locked" : null);
  return (
    <span
      className={cn(
        "relative flex w-full flex-col overflow-hidden rounded-card border-3 bg-surface text-left text-caption font-bold text-foreground transition-state",
        state === "locked" ? TEAM_CLASS[lockedBy].border : BORDER[state],
        lifted && "tilt-card shadow-lift",
        className,
      )}
    >
      {art && art !== broken ? (
        <img
          src={art}
          alt=""
          loading="lazy"
          onError={() => setBroken(art)}
          className={cn(
            "block aspect-14/19 w-full object-cover",
            state === "banned" && "brightness-50 grayscale",
            (state === "hk" || state === "am") && "brightness-55",
          )}
        />
      ) : (
        <span
          aria-hidden="true"
          className={cn("flex aspect-14/19 w-full items-center justify-center bg-raised font-display text-section text-muted", dim && "opacity-60")}
        >
          <Glyphs text={initials(name)} />
        </span>
      )}
      {state === "banned" ? (
        <span className="absolute top-2/5 left-1/2 -translate-x-1/2 -translate-y-1/2">
          {/* The card's own line says it too: the sticker is drawn, so the name reads once. */}
          <Sticker tone="danger" tilt="none" className="-rotate-8">
            <Glyphs text="Banned" />
          </Sticker>
        </span>
      ) : null}
      {state === "locked" ? (
        <span className="absolute top-2 right-2">
          <Sticker tone={lockedBy} tilt="right" size="sm">
            <Glyphs text="Locked" />
          </Sticker>
        </span>
      ) : null}
      {wishes ? (
        <span className="absolute top-2 left-2">
          <Sticker tone="cream" size="sm" tilt="slight">
            <Glyphs text={wishes} />
          </Sticker>
        </span>
      ) : null}
      <span className="flex min-h-10 flex-col gap-px px-2.25 pt-1.5 pb-2">
        <span className="line-clamp-2">{name}</span>
        {line ? <span className={cn("text-micro font-semibold", TAG_TONE[tagTone])}>{line}</span> : null}
      </span>
    </span>
  );
}
