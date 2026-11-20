import { useEffect, useRef } from "react";

import { cn } from "../lib/cn";
import { useCountdown } from "../live/hooks";
import { useAnnounce } from "./Announcer";
import type { TeamKey } from "./team";
import { TEAM_CLASS } from "./team";

export const WAITING = "Waiting for the server";

/** Where the clock sits (F03): the scorebug 64, a dialog 56, a sheet 40, a turn banner 34, the
 * phone room top 22, or inline in a sentence at body size. */
const SIZE = {
  scorebug: "font-display text-clock",
  dialog: "font-display text-board",
  sheet: "font-display text-clock-sheet",
  banner: "font-display text-coin",
  phone: "font-display text-clock-phone",
  inline: "font-extrabold",
} as const;

export type CountdownSize = keyof typeof SIZE;

const ANNOUNCE_AT = [30, 10] as const;

interface Props {
  /** The server's deadline (ISO). The time left comes from the server clock via the live
   * connection's offset, so a slow tab never drifts. */
  deadline: string | null | undefined;
  size?: CountdownSize;
  /** The acting team's colour; cream when it's nobody's turn. */
  tone?: TeamKey | null;
  /** What the timer is, for screen readers: "Time left", "Time to answer". */
  label?: string;
  /** Finishes the 30 s and 10 s announcements: "to pick" → "10 seconds left to pick". Leave out
   * for clocks that shouldn't speak (more than one on a page). */
  announce?: string;
  /** The live connection is down: the clock goes faint but keeps counting (P03). */
  isStale?: boolean;
  className?: string;
}

/** A clock counting down to a server deadline: m:ss, tabular, never below 0:00. At zero it says
 * "Waiting for the server" until the next step arrives. It ticks without animation. */
export function Countdown({ deadline, size = "inline", tone = null, label = "Time left", announce, isStale = false, className }: Props) {
  const left = useCountdown(deadline);
  const say = useAnnounce();
  const previous = useRef<number | null>(null);
  const seconds = left?.seconds ?? null;

  useEffect(() => {
    const before = previous.current;
    previous.current = seconds;
    if (!announce || seconds === null || before === null) return;
    for (const mark of ANNOUNCE_AT) {
      if (before > mark && seconds <= mark) say(`${mark} seconds left ${announce}`);
    }
  }, [seconds, announce, say]);

  if (!left) return null;
  const waiting = left.waiting;
  return (
    <span
      role="timer"
      aria-label={waiting ? WAITING : `${label} ${left.label}`}
      className={cn(
        "tabular-nums",
        waiting ? "text-body font-extrabold text-muted" : SIZE[size],
        !waiting && (isStale ? "text-faint" : tone ? TEAM_CLASS[tone].text : "text-foreground"),
        className,
      )}
    >
      {waiting ? WAITING : left.label}
    </span>
  );
}
