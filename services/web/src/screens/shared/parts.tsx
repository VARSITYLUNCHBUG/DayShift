// Small pieces the pages outside the match room share: the back link, match cards, the queue's
// seat pills and strike dots.
import type { ReactNode } from "react";
import { Link } from "react-router";

import type { MatchStatus, Side, Team } from "../../api/types";
import { Icon } from "../../components/Icon";
import { Sticker } from "../../components/Sticker";
import { TEAM_CLASS } from "../../components/team";
import { cn } from "../../lib/cn";
import { FINISHED, STATUS_LABEL, teamLabel } from "./format";

/** Where a match opens: its room while it's on, its record and postgame once it's over. */
export function matchHref(id: string, status: MatchStatus): string {
  return FINISHED.has(status) ? `/matches/${id}/summary` : `/matches/${id}`;
}

/** "‹ Me": the way back up, above a page's title. */
export function BackLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={to} className="-ml-2 inline-flex min-h-11 items-center gap-1.5 self-start rounded-full px-2 text-body font-bold text-muted hover:text-foreground">
      <Icon name="back" size={16} />
      {children}
    </Link>
  );
}

interface TeamsLineProps {
  captains: { A: string | null; B: string | null };
  sides: { A: Side | null; B: Side | null };
  className?: string;
}

/** "Marlow's Team vs Sable's Team", each in its side's colour once the coinflip has said. */
export function TeamsLine({ captains, sides, className }: TeamsLineProps) {
  const name = (team: Team) => {
    const side = sides[team];
    return <span className={cn("font-extrabold", side ? TEAM_CLASS[side].text : "text-foreground")}>{teamLabel(captains[team], team)}</span>;
  };
  // The Hidden King's team first, as everywhere else.
  const [first, second]: [Team, Team] = sides.B === "hk" ? ["B", "A"] : ["A", "B"];
  return (
    <span className={cn("text-body", className)}>
      {name(first)} <span className="font-semibold text-muted">vs</span> {name(second)}
    </span>
  );
}

interface MatchCardProps {
  id: string;
  status: MatchStatus;
  captains: { A: string | null; B: string | null };
  sides: { A: Side | null; B: Side | null };
  /** Under the teams: "Ban 3 of 6 · watch the draft", "Earlier tonight · 33:40". */
  line?: ReactNode;
  /** On the right under the status: "+18", "Won". */
  aside?: ReactNode;
  /** The viewer was on this match's roster. */
  played?: boolean;
  /** A sticker beside the teams ("Won"), in the winner's colour. */
  sticker?: { label: string; side: Side | null } | null;
  size?: "md" | "sm";
}

/** One match in a list (Play's Tonight, Matches): its number, the teams, where it is. The whole
 * card is one link, to the room or the record. */
export function MatchCard({ id, status, captains, sides, line, aside, played = false, sticker, size = "md" }: MatchCardProps) {
  return (
    <Link
      to={matchHref(id, status)}
      className="flex items-start gap-4 rounded-card border border-line bg-surface px-4 py-3.5 transition-state hover:border-line-strong"
    >
      <span className={cn("shrink-0 type-display tabular-nums", size === "md" ? "w-20 text-card" : "w-14 text-body")}>
        <span className="sr-only">Match</span> No. {id}
      </span>
      <span className="flex min-w-0 flex-1 flex-col gap-1">
        <span className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
          <TeamsLine captains={captains} sides={sides} />
          {sticker ? (
            <Sticker tone={sticker.side ?? "raised"} size="sm">
              {sticker.label}
            </Sticker>
          ) : null}
          {played ? (
            <Sticker tone="cream" size="sm" tilt="slight">
              You played
            </Sticker>
          ) : null}
        </span>
        {line ? <span className="text-caption font-medium text-muted tabular-nums">{line}</span> : null}
      </span>
      <span className="flex shrink-0 flex-col items-end gap-1 text-right">
        <b className="text-caption font-extrabold">{STATUS_LABEL[status]}</b>
        {aside ? <span className="text-label font-extrabold tabular-nums">{aside}</span> : null}
      </span>
    </Link>
  );
}

/** The queue's seats, one pill each, filled in order (the priority list is private, so they
 * name nobody). */
export function QueueFill({ count, size, compact = false }: { count: number; size: number; compact?: boolean }) {
  return (
    <div role="img" aria-label={`${count} of ${size} in the queue`} className={cn("grid gap-1.5", compact ? "h-3" : "h-4")} style={{ gridTemplateColumns: `repeat(${size}, minmax(0, 1fr))` }}>
      {Array.from({ length: size }, (_, index) => (
        <span key={index} className={cn("rounded-full border", index < count ? "border-foreground bg-foreground" : "border-line bg-raised")} />
      ))}
    </div>
  );
}

/** Strikes as dots: filled for each one you carry, out of the most that matter. Neutral, never
 * red (red is for leaving, bans, voids and disputes). */
export function StrikeDots({ count, of = 3, label }: { count: number; of?: number; label?: string }) {
  return (
    <span role="img" aria-label={label ?? `${count} ${count === 1 ? "strike" : "strikes"}`} className="inline-flex gap-1.5">
      {Array.from({ length: Math.max(of, count) }, (_, index) => (
        <span key={index} className={cn("size-5 rounded-full border-2", index < count ? "border-foreground bg-foreground" : "border-line-strong")} />
      ))}
    </span>
  );
}

/** A progress bar out of a total, with its words above: "1 of 3 clean matches". */
export function Progress({ value, max, label }: { value: number; max: number; label: string }) {
  const percent = max > 0 ? Math.min(100, Math.max(0, (value / max) * 100)) : 0;
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-caption font-extrabold tabular-nums">{label}</span>
      <div role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={max} aria-valuenow={value} className="h-2.5 rounded-full bg-background">
        <div className="h-full rounded-full bg-foreground" style={{ width: `${percent.toFixed(1)}%` }} />
      </div>
    </div>
  );
}

/** A numbered "what happens next" list. */
export function Steps({ items }: { items: readonly { title: ReactNode; line: ReactNode }[] }) {
  return (
    <ol className="flex flex-col gap-3.5">
      {items.map((item, index) => (
        <li key={index} className="flex items-start gap-3">
          <span aria-hidden="true" className="flex size-7.5 shrink-0 items-center justify-center rounded-full border border-line-strong bg-raised text-label font-extrabold">
            {index + 1}
          </span>
          <span className="flex flex-col gap-0.5">
            <b className="text-body font-extrabold">{item.title}</b>
            <span className="text-label text-muted">{item.line}</span>
          </span>
        </li>
      ))}
    </ol>
  );
}
