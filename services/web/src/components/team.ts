// The two sides. Amber is always The Hidden King and blue always The Archmother; "your move" is
// drawn in the acting team's colour. Class names are spelled out in full so Tailwind sees them.
import type { TeamKey } from "./Button";

export type { TeamKey };

export const SIDE_NAME: Record<TeamKey, string> = {
  hk: "The Hidden King",
  am: "The Archmother",
};

export const TEAM_CLASS = {
  hk: {
    fill: "bg-team-hk text-team-hk-ink",
    text: "text-team-hk",
    soft: "bg-team-hk-soft",
    light: "text-team-hk-light",
    border: "border-team-hk",
    line: "border-team-hk-line",
    softBorder: "border-team-hk-soft",
    dot: "bg-team-hk",
  },
  am: {
    fill: "bg-team-am text-team-am-ink",
    text: "text-team-am",
    soft: "bg-team-am-soft",
    light: "text-team-am-light",
    border: "border-team-am",
    line: "border-team-am-line",
    softBorder: "border-team-am-soft",
    dot: "bg-team-am",
  },
} as const satisfies Record<TeamKey, Record<string, string>>;
