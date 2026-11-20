import { Card, Chip } from "@heroui/react";

import { byName, number, teamName } from "../lib/format";
import type { MatchSnap, Team } from "../../live/types";
import { HeroCard } from "./HeroCard";
import { PlayerTile } from "./PlayerTile";
import { SideChip } from "./SideChip";

interface Props {
  match: MatchSnap;
  team: Team;
  /** The team whose turn it is, or the viewer's own. */
  highlight?: boolean;
  /** Show the team's bans and hero picks (the hero draft and after). */
  showHeroes?: boolean;
  /** Seats on the team: empty ones show as dashed rows (the player draft). */
  seats?: number;
}

/** One team: name, side, win chance or average rating, bans, hero picks and players. */
export function TeamPanel({ match, team, highlight = false, showHeroes = false, seats = 0 }: Props) {
  const players = match.players
    .filter((p) => p.team === team)
    .sort((a, b) => Number(b.is_captain) - Number(a.is_captain) || byName(a, b));
  const side = match.sides[team];
  const bans = match.draft.filter((d) => d.team === team && d.action === "ban");
  const picks = match.draft.filter((d) => d.team === team && d.action === "pick");
  const pickSlots = side ? match.champion_steps.filter((s) => s.side === side && s.action === "pick").length : 0;
  const banSlots = side ? match.champion_steps.filter((s) => s.side === side && s.action === "ban").length : 0;
  const chance = match.win_chance_a === null ? null : team === "A" ? match.win_chance_a : 1 - match.win_chance_a;
  const rated = players.filter((p) => p.rating > 0);
  const average = rated.length ? Math.round(rated.reduce((sum, p) => sum + p.rating, 0) / rated.length) : null;
  const headingId = `team-${match.id}-${team}`;

  return (
    <Card
      aria-labelledby={headingId}
      className={`min-w-0 flex-1 basis-64 gap-3.5 p-4.5 ${highlight ? "border border-accent" : "border border-border"}`}
    >
      <div className="flex flex-col gap-2">
        <div className="flex items-baseline justify-between gap-2">
          <h2 id={headingId} className={`text-base font-bold ${highlight ? "text-accent-soft-foreground" : ""}`}>
            {teamName(match.team_names, team)}
          </h2>
          <span className="text-sm text-muted tabular-nums">
            {chance !== null ? `${Math.round(chance * 100)}%` : average !== null ? number(average) : null}
          </span>
        </div>
        {side ? <SideChip side={side} /> : null}
      </div>

      {showHeroes && banSlots > 0 ? (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="mr-1 text-xs text-muted">Bans</span>
          {bans.map((ban) => (
            <Chip key={ban.label} size="sm" color="danger" variant="soft" className="font-semibold line-through">
              {ban.champion?.name ?? ban.label}
            </Chip>
          ))}
          {Array.from({ length: Math.max(0, banSlots - bans.length) }, (_, i) => (
            <span key={i} className="rounded-full border border-dashed border-default px-2.5 py-0.5 text-xs text-muted">
              {ordinal(bans.length + i + 1)}
            </span>
          ))}
        </div>
      ) : null}

      {showHeroes && pickSlots > 0 ? (
        <ul className="grid grid-cols-3 gap-1.5" aria-label="Heroes">
          {Array.from({ length: pickSlots }, (_, i) => {
            const pick = picks[i];
            return (
              <li key={i}>
                {pick?.champion ? (
                  <HeroCard champion={pick.champion} tone={side ?? undefined} compact />
                ) : (
                  <span className="block aspect-3/4 rounded-lg border border-dashed border-default" />
                )}
              </li>
            );
          })}
        </ul>
      ) : null}

      <ul className="flex flex-col gap-1" aria-label="Players">
        {players.map((p) => (
          <li key={p.id}>
            <PlayerTile
              dense
              name={p.name}
              detail={p.is_captain ? "C" : p.rating > 0 ? number(p.rating) : undefined}
            />
          </li>
        ))}
        {Array.from({ length: Math.max(0, seats - players.length) }, (_, i) => (
          <li key={`seat-${i}`} aria-label="Open seat" className="h-9 rounded-xl border border-dashed border-default" />
        ))}
      </ul>
    </Card>
  );
}

function ordinal(n: number): string {
  return n === 1 ? "1st" : n === 2 ? "2nd" : n === 3 ? "3rd" : `${n}th`;
}
