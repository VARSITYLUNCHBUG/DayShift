import { Card } from "@heroui/react";

import { HeroCard } from "../../components/HeroCard";
import { SideChip } from "../../components/SideChip";
import { teamName } from "../../lib/format";
import { teamPlayers } from "../../match/draft";
import type { MatchSnap, Side, Team } from "../../../live/types";

interface Props {
  match: MatchSnap;
  team: Team;
  /** Coloured by the team's side (the lobby). */
  tinted?: boolean;
  /** A line of names (the lobby) or a grid of players (in game). */
  players?: "line" | "grid";
  showBans?: boolean;
}

const TINT: Record<Side, { card: string; text: string; muted: string; captain: string }> = {
  hk: {
    card: "border-team-hk/40 bg-team-hk-soft",
    text: "text-team-hk-soft-foreground",
    muted: "text-team-hk-soft-foreground/80",
    captain: "bg-team-hk-soft text-team-hk-soft-foreground",
  },
  am: {
    card: "border-team-am/40 bg-team-am-soft",
    text: "text-team-am-soft-foreground",
    muted: "text-team-am-soft-foreground/80",
    captain: "bg-team-am-soft text-team-am-soft-foreground",
  },
};

/** A drafted team: name, side, heroes, players and bans, after the draft is done. */
export function TeamSummary({ match, team, tinted = false, players = "line", showBans = false }: Props) {
  const side = match.sides[team];
  const tint = side ? TINT[side] : null;
  const roster = teamPlayers(match, team);
  const heroes = match.draft.filter((d) => d.team === team && d.action === "pick" && d.champion);
  const bans = match.draft.filter((d) => d.team === team && d.action === "ban");
  const chance = match.win_chance_a === null ? null : team === "A" ? match.win_chance_a : 1 - match.win_chance_a;
  const headingId = `summary-${match.id}-${team}`;
  const coloured = tinted && tint;

  return (
    <Card
      aria-labelledby={headingId}
      className={`min-w-0 flex-1 basis-96 gap-4 border p-5.5 ${coloured ? tint.card : "border-border"}`}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id={headingId} className={`text-lg font-bold ${coloured ? tint.text : ""}`}>
          {teamName(match.team_names, team)}
        </h2>
        {chance !== null ? (
          <span className={`text-sm tabular-nums ${coloured ? tint.muted : "text-muted"}`}>{Math.round(chance * 100)}%</span>
        ) : null}
        {!tinted && side ? <SideChip side={side} /> : null}
      </div>
      {tinted && side ? (
        <div>
          <SideChip side={side} />
        </div>
      ) : null}

      {heroes.length > 0 ? (
        <ul aria-label="Heroes" className="grid grid-cols-3 gap-2 sm:grid-cols-6">
          {heroes.map((entry) =>
            entry.champion ? (
              <li key={entry.champion.id}>
                <HeroCard champion={entry.champion} tone={side ?? undefined} compact />
              </li>
            ) : null,
          )}
        </ul>
      ) : null}

      {players === "line" ? (
        <p className={`text-sm leading-relaxed ${coloured ? tint.text : ""}`}>
          {roster.map((p) => (p.is_captain ? `${p.name} (C)` : p.name)).join(" · ")}
        </p>
      ) : (
        <ul aria-label="Players" className="grid grid-cols-2 gap-1.5 text-sm">
          {roster.map((p) => (
            <li
              key={p.id}
              className={`truncate rounded-xl px-3 py-2.5 ${p.is_captain ? `font-semibold ${tint ? tint.captain : "bg-surface-secondary"}` : "bg-background"}`}
            >
              {p.name}
              {p.is_captain ? <span className="ml-1.5 text-xs opacity-80">C</span> : null}
            </li>
          ))}
        </ul>
      )}

      {showBans && bans.length > 0 ? (
        <span className={`text-sm ${coloured ? tint.muted : "text-muted"}`}>
          Bans: {bans.map((b) => b.champion?.name ?? b.label).join(", ")}
        </span>
      ) : null}
    </Card>
  );
}

/** Both teams, under the draft's name: the lobby and its code. */
export function Teams({ match, tinted = false, showName = true }: { match: MatchSnap; tinted?: boolean; showName?: boolean }) {
  return (
    <section aria-label="Teams" className="flex flex-col gap-3">
      {showName ? <span className="text-sm text-muted">{match.draft_name} · GLHF</span> : null}
      <div className="flex flex-wrap gap-5">
        <TeamSummary match={match} team="A" tinted={tinted} showBans />
        <TeamSummary match={match} team="B" tinted={tinted} showBans />
      </div>
    </section>
  );
}
