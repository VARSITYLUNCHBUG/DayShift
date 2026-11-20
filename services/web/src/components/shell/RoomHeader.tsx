import type { ReactNode } from "react";
import { Link } from "react-router";

import { cn } from "../../lib/cn";
import { Avatar } from "../Avatar";
import { Mark } from "../Brand";
import { Countdown } from "../Countdown";
import { SkipLink } from "../Navigation";
import type { TeamKey } from "../team";
import { TEAM_CLASS } from "../team";
import type { ShellUser } from "./TopBar";

/** The match room's phase rail (ds.PHASES). Main's statuses map onto it with `roomPhase`. */
export const RANKED_PHASES = ["Ready", "Captains", "Players", "Sides", "Heroes", "Lobby", "Game", "Result"] as const;
export const SCRIM_PHASES = ["Captains", "Sides", "Heroes", "Drafted"] as const;

const RANKED_INDEX: Record<string, number> = {
  ready_check: 0,
  captain_phase: 1,
  captain_checkin: 1,
  player_draft: 2,
  coinflip: 3,
  champion_draft: 4,
  lobby_code: 5,
  in_progress: 6,
  awaiting_confirmation: 7,
  disputed: 7,
  completed: 7,
  voided: 7,
};

const SCRIM_INDEX: Record<string, number> = {
  captain_claim: 0,
  coinflip: 1,
  ready_to_draft: 1,
  champion_draft: 2,
  drafted: 3,
};

/** Where a match status sits on the rail: the phases for its kind and the current index. */
export function roomPhase(status: string, kind: "ranked" | "scrim" = "ranked"): { phases: readonly string[]; current: number } {
  const key = status.toLowerCase();
  if (kind === "scrim") return { phases: SCRIM_PHASES, current: SCRIM_INDEX[key] ?? 0 };
  return { phases: RANKED_PHASES, current: RANKED_INDEX[key] ?? 0 };
}

export interface RoomHeaderProps {
  /** "No. 413". */
  number: ReactNode;
  /** "Wednesday league night". */
  title?: ReactNode;
  phases: readonly string[];
  current: number;
  /** The current bar takes the acting team's colour; cream when it's nobody's turn. */
  tone?: TeamKey | null;
  /** Need a sub, Watching: the header's right side before you. */
  actions?: ReactNode;
  me?: ShellUser | null;
  /** Where the mark goes: Play by default; Matches from a past match. */
  back?: { to: string; label: string };
}

const BACK_TO_PLAY = { to: "/", label: "Back to Play" };

const BAR_NOW: Record<TeamKey | "none", string> = {
  hk: "bg-team-hk",
  am: "bg-team-am",
  none: "bg-foreground",
};

/** The match room header (ds.room_header): back to Play, the match number, the phase rail with the
 * current bar in the acting team's colour, Need a sub, you. Never moves between phases. */
export function RoomHeader({ number, title, phases, current, tone = null, actions, me, back = BACK_TO_PLAY }: RoomHeaderProps) {
  return (
    <>
      <SkipLink to="#stage">Skip to the match</SkipLink>
      <header className="flex flex-col gap-3.5 border-b border-line px-8 pt-3 pb-4">
        <div className="flex min-h-11 flex-wrap items-center gap-x-5 gap-y-3">
          <Link to={back.to} aria-label={back.label} className="flex h-11 items-center rounded-full px-1">
            <Mark size={28} />
          </Link>
          <div className="flex items-baseline gap-3.5">
            <span className="font-display text-team">{number}</span>
            {title ? <span className="text-body font-semibold text-muted">{title}</span> : null}
          </div>
          <div className="ml-auto flex items-center gap-3">
            {actions}
            {me ? (
              <Link to="/me" aria-label={`Me: ${me.name}`} className="flex rounded-full">
                <Avatar name={me.name} src={me.avatar} size="md" />
              </Link>
            ) : null}
          </div>
        </div>
        <ol aria-label="Match phases" className="grid gap-1.5" style={{ gridTemplateColumns: `repeat(${phases.length}, minmax(0, 1fr))` }}>
          {phases.map((label, index) => {
            const now = index === current;
            return (
              <li
                key={label}
                aria-current={now ? "step" : undefined}
                aria-label={now ? `${label}, current step, ${index + 1} of ${phases.length}` : undefined}
                className="flex flex-col gap-1.5"
              >
                <span
                  aria-hidden="true"
                  className={cn("h-2 rounded-full", now ? BAR_NOW[tone ?? "none"] : index < current ? "bg-muted" : "bg-line")}
                />
                <span
                  className={cn(
                    "truncate text-caption",
                    now ? "font-extrabold text-foreground" : "font-semibold text-faint max-lg:sr-only",
                  )}
                >
                  {label}
                </span>
              </li>
            );
          })}
        </ol>
      </header>
    </>
  );
}

interface PhoneRoomTopProps {
  number: ReactNode;
  /** The current phase's name, in the acting team's colour: "Heroes · your pick". */
  phase: ReactNode;
  tone?: TeamKey | null;
  deadline?: string | null;
  actions?: ReactNode;
  back?: { to: string; label: string };
}

/** The phone room top (ds.phone_room_top): mark back to Play, No. 413 over the phase, the clock. */
export function PhoneRoomTop({ number, phase, tone = null, deadline, actions, back = BACK_TO_PLAY }: PhoneRoomTopProps) {
  return (
    <>
      <SkipLink to="#stage">Skip to the match</SkipLink>
      <header className="flex min-h-14 items-center gap-2.5 border-b border-line px-3.5 py-1.5">
        <Link to={back.to} aria-label={back.label} className="flex h-11 items-center rounded-full px-1">
          <Mark size={20} />
        </Link>
        <div className="flex min-w-0 flex-col">
          <b className="font-display text-body">{number}</b>
          <span className={cn("truncate text-micro font-bold", tone ? TEAM_CLASS[tone].text : "text-foreground")}>{phase}</span>
        </div>
        <div className="ml-auto flex items-center gap-2">
          {actions}
          {deadline ? <Countdown deadline={deadline} size="phone" tone={tone} /> : null}
        </div>
      </header>
    </>
  );
}
