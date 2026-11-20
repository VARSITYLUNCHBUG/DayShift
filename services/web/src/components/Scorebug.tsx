import type { ReactNode } from "react";

import { cn } from "../lib/cn";
import { Countdown } from "./Countdown";
import type { TeamKey } from "./team";
import { SIDE_NAME, TEAM_CLASS } from "./team";

interface TeamBlockProps {
  team: TeamKey;
  /** "Rook's Team". */
  name: string;
  /** "Captain Rook". */
  line?: ReactNode;
  /** Says "On the clock" under the name: colour never works alone (F07). */
  isActing?: boolean;
  align?: "start" | "end";
}

/** One side of the scorebug: the side, the team's name in its colour, the captain. */
export function TeamBlock({ team, name, line, isActing = false, align = "start" }: TeamBlockProps) {
  const tone = TEAM_CLASS[team].text;
  return (
    <div
      className={cn(
        "flex min-w-0 flex-1 basis-55 flex-col gap-0.5",
        align === "end" ? "items-end text-right max-md:items-start max-md:text-left" : "items-start text-left",
      )}
    >
      <span className={cn("text-caption font-bold", tone)}>{SIDE_NAME[team]}</span>
      <span className={cn("font-display text-team break-words", tone)}>{name}</span>
      {line ? <span className="text-label text-muted">{line}</span> : null}
      {isActing ? <span className={cn("text-caption font-extrabold", tone)}>On the clock</span> : null}
    </div>
  );
}

interface ScorebugProps {
  left: ReactNode;
  right: ReactNode;
  /** The step's server deadline; leave out when nothing is timed. */
  deadline?: string | null;
  /** The acting team (colours the clock and title); none when it's nobody's turn. */
  tone?: TeamKey | null;
  /** Whose move: "Your pick, Rook", "Vesper's pick". */
  title: ReactNode;
  /** "Pick 4 of 12 · then Vesper picks twice · runs out: a random hero". */
  line?: ReactNode;
  /** The one action, under the clock (P02). */
  action?: ReactNode;
  /** Passed to the clock's 30 s / 10 s announcement ("to pick"). */
  announce?: string;
  isStale?: boolean;
}

/** The broadcast bar: teams either side, the clock, whose move and the one action in the
 * middle. Same place every phase; on a phone the room uses TurnBanner instead. */
export function Scorebug({ left, right, deadline, tone = null, title, line, action, announce, isStale }: ScorebugProps) {
  return (
    <section
      aria-label="Now"
      className="flex flex-wrap items-center gap-x-8 gap-y-5 border-b border-line bg-surface px-4 py-5.5 md:px-8"
    >
      {left}
      <div className="flex min-w-65 flex-initial basis-105 flex-col items-center gap-1.5 text-center max-md:order-first max-md:w-full">
        {deadline ? <Countdown deadline={deadline} size="scorebug" tone={tone} announce={announce} isStale={isStale} /> : null}
        <span className={cn("text-card font-extrabold", isStale ? "text-faint" : tone ? TEAM_CLASS[tone].text : "text-foreground")}>
          {title}
        </span>
        {line ? <span className="text-label text-muted">{line}</span> : null}
        {action ? <div className="mt-1.5 flex flex-wrap justify-center gap-2.5">{action}</div> : null}
      </div>
      {right}
    </section>
  );
}

interface TurnBannerProps {
  deadline?: string | null;
  tone?: TeamKey | null;
  title: ReactNode;
  line?: ReactNode;
  action?: ReactNode;
  announce?: string;
  isStale?: boolean;
  className?: string;
}

/** The compact "whose move" strip for phones and side panels, in the acting team's colour. */
export function TurnBanner({ deadline, tone = null, title, line, action, announce, isStale, className }: TurnBannerProps) {
  return (
    <section
      aria-label="Now"
      className={cn(
        "flex items-center gap-3.5 rounded-card border-2 px-4 py-3.5",
        tone ? cn(TEAM_CLASS[tone].soft, TEAM_CLASS[tone].border) : "border-line-strong bg-raised",
        className,
      )}
    >
      {deadline ? <Countdown deadline={deadline} size="banner" tone={tone} announce={announce} isStale={isStale} /> : null}
      <div className="flex min-w-0 flex-col">
        <b className={cn("text-body font-extrabold", tone ? TEAM_CLASS[tone].text : "text-foreground")}>{title}</b>
        {line ? <span className="text-caption text-muted">{line}</span> : null}
      </div>
      {action ? <div className="ml-auto shrink-0">{action}</div> : null}
    </section>
  );
}
