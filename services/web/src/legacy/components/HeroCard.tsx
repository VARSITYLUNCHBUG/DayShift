import { ToggleButton } from "@heroui/react";
import { useState } from "react";

import { initials } from "../lib/format";
import type { ChampionRef, Side } from "../../live/types";

/** The hero's card art, as the server names it: the repo's art pack
 * (`/static/hero-art/<slug>.webp`), else the champion's own icon, else null for initials. */
export function heroArtUrl(champion: Pick<ChampionRef, "icon_url">): string | null {
  return champion.icon_url;
}

interface Props {
  champion: ChampionRef;
  /** A label under the name: "Banned", "P2's Team", "Selected". */
  tag?: string | null;
  tone?: Side | "danger" | "success";
  /** Pressable when given: a toggle in the hero grid. */
  onPress?: () => void;
  isSelected?: boolean;
  isDisabled?: boolean;
  /** Taken heroes fade out. */
  isTaken?: boolean;
  /** Smaller, for a team's picks: art and name only. */
  compact?: boolean;
  "aria-label"?: string;
}

const TAG_CLASS: Record<NonNullable<Props["tone"]>, string> = {
  hk: "text-team-hk",
  am: "text-team-am",
  danger: "text-danger-soft-foreground",
  success: "text-success-soft-foreground",
};

const COMPACT_CLASS: Record<NonNullable<Props["tone"]>, string> = {
  hk: "bg-team-hk-soft text-team-hk-soft-foreground",
  am: "bg-team-am-soft text-team-am-soft-foreground",
  danger: "bg-danger-soft text-danger-soft-foreground",
  success: "bg-success-soft text-success-soft-foreground",
};

/** The art, or the hero's initials when there's none or it won't load (a 404 before the art
 * is synced, say). */
export function HeroArt({
  champion,
  className,
  textClass = "text-2xl",
}: {
  champion: ChampionRef;
  className: string;
  /** The initials' size: smaller in small tiles. */
  textClass?: string;
}) {
  const src = heroArtUrl(champion);
  const [broken, setBroken] = useState<string | null>(null);
  if (src && src !== broken) {
    return (
      <img
        src={src}
        alt=""
        loading="lazy"
        className={`${className} bg-surface-tertiary object-cover`}
        onError={() => setBroken(src)}
      />
    );
  }
  return (
    <span
      aria-hidden="true"
      className={`${className} flex items-center justify-center bg-linear-to-b from-surface-tertiary to-surface-secondary font-bold tracking-wide text-foreground/80 ${textClass}`}
    >
      {initials(champion.name)}
    </span>
  );
}

export function HeroCard({
  champion,
  tag,
  tone,
  onPress,
  isSelected = false,
  isDisabled = false,
  isTaken = false,
  compact = false,
  ...aria
}: Props) {
  if (compact) {
    return (
      <figure className="m-0 flex aspect-3/4 flex-col justify-end overflow-hidden rounded-lg">
        <HeroArt champion={champion} className="min-h-0 w-full flex-1" />
        <figcaption
          className={`line-clamp-2 min-h-9.5 px-1.5 py-1 text-xs leading-tight font-semibold ${tone ? COMPACT_CLASS[tone] : "bg-surface-secondary"}`}
        >
          {champion.name}
        </figcaption>
      </figure>
    );
  }

  const body = (
    <>
      <HeroArt champion={champion} className="aspect-3/4 w-full" />
      <span
        className={`flex w-full flex-col gap-0.5 px-2 py-1.5 text-left ${isSelected ? "bg-success-soft" : "bg-surface"}`}
      >
        {/* Two lines kept for every name, so long ones ("Deadman Danny") wrap without making
            their card taller than the rest of the row. */}
        <span className="line-clamp-2 min-h-7.5 text-xs leading-tight font-semibold whitespace-normal">
          {champion.name}
        </span>
        <span className={`min-h-3.5 text-xs font-semibold ${tone ? TAG_CLASS[tone] : "text-muted"}`}>{tag}</span>
      </span>
    </>
  );

  const frame = `flex flex-col gap-0 overflow-hidden rounded-xl border-2 p-0 ${
    isSelected ? "border-success" : "border-border"
  } ${isTaken ? "opacity-40 grayscale" : ""}`;

  if (!onPress) {
    return (
      <div className={frame} aria-label={aria["aria-label"]}>
        {body}
      </div>
    );
  }
  return (
    <ToggleButton
      isSelected={isSelected}
      isDisabled={isDisabled}
      onChange={() => onPress()}
      aria-label={aria["aria-label"] ?? champion.name}
      className={`h-auto w-full ${frame} bg-surface-secondary text-foreground`}
    >
      {body}
    </ToggleButton>
  );
}
