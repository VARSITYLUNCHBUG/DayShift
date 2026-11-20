// A match's record from GET /api/matches/<id>/: the tiles, the draft order and each team's
// players with their heroes, awards and rating changes. The result screen (3.6) and the page of
// a past match (5.2) both show it.
import { Card, Chip } from "@heroui/react";

import { HeroCard } from "../../components/HeroCard";
import { PlayerAvatar } from "../../components/PlayerAvatar";
import { SIDE_NAME, SideChip } from "../../components/SideChip";
import { StatTile } from "../../components/StatTile";
import { dayAndTime, number, percent, signed } from "../../lib/format";
import { clock, useServerNow } from "../../../live/hooks";
import type { Award, DraftPick, MatchDetail, ResultPlayer, Side, Team, TeamResult } from "../../../live/types";

export const AWARD_LABEL: Record<Award, string> = { mvp: "MVP", key: "Key" };

const AWARD_CLASS: Record<Award, string> = {
  mvp: "bg-warning-soft text-warning-soft-foreground",
  key: "bg-accent-soft text-accent-soft-foreground",
};

export const WIN_TONE: Record<Side, { card: string; line: string }> = {
  hk: { card: "border-team-hk/40 bg-team-hk-soft text-team-hk-soft-foreground", line: "text-team-hk" },
  am: { card: "border-team-am/40 bg-team-am-soft text-team-am-soft-foreground", line: "text-team-am" },
};

export function deltaClass(delta: number | undefined): string {
  if (delta === undefined || delta === 0) return "text-muted";
  return delta > 0 ? "text-success" : "text-danger";
}

export function teamOf(detail: MatchDetail, team: Team): TeamResult | undefined {
  return detail.teams.find((t) => t.team === team);
}

/** The team's name, or "Team A" before it has a captain. */
export function recordTeamName(detail: MatchDetail, team: Team): string {
  return teamOf(detail, team)?.name ?? `Team ${team}`;
}

/** The viewer's own line, when they played. */
export function myLine(detail: MatchDetail, myId: string | null): ResultPlayer | undefined {
  if (!myId) return undefined;
  return detail.teams.flatMap((t) => t.players).find((p) => p.id === myId);
}

/** The winner's forecast chance, when the ratings made one. */
export function winnerChance(detail: MatchDetail): number | null {
  if (detail.win_chance_a === null || !detail.winner) return null;
  return detail.winner === "A" ? detail.win_chance_a : 1 - detail.win_chance_a;
}

/** "31:52": the game's length, from the scoreboard or deadlock-api. */
export function length(detail: MatchDetail): string | null {
  return detail.duration_s ? clock(detail.duration_s) : null;
}

/** 5.2's tiles: the winner (unless the page already says), the length, when, and the game's ID. */
export function RecordTiles({ detail, showWinner = true }: { detail: MatchDetail; showWinner?: boolean }) {
  const now = useServerNow(60_000);
  const winner = detail.winner;
  const side = winner ? (teamOf(detail, winner)?.side ?? null) : null;
  const chance = winnerChance(detail);
  const when = detail.started_at ?? detail.ended_at;
  return (
    <section aria-label="The match" className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {showWinner && winner ? (
        <Card className={`gap-1 border p-4.5 ${side ? WIN_TONE[side].card : "border-border"}`}>
          <span className="text-sm opacity-85">{side ? `Winner · ${SIDE_NAME[side]}` : "Winner"}</span>
          <span className="text-xl font-bold">{recordTeamName(detail, winner)}</span>
          {chance !== null ? (
            <Chip size="sm" variant="soft" color={chance < 0.5 ? "warning" : "default"} className="mt-1 self-start font-semibold">
              {chance < 0.5 ? `Upset · ${percent(chance)} to win` : `${percent(chance)} to win`}
            </Chip>
          ) : null}
        </Card>
      ) : null}
      {!showWinner && chance !== null ? (
        <Tile label="Forecast" value={percent(chance)} hint={chance < 0.5 ? "An upset" : "The favourite won"} />
      ) : null}
      <Tile label="Length" value={length(detail) ?? "–"} />
      <Tile label="Played" value={when ? dayAndTime(when, now) : "–"} />
      <Tile label="Deadlock ID" value={detail.deadlock_match_id ?? "–"} />
    </section>
  );
}

function Tile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return <StatTile label={label} value={value} hint={hint} size="sm" />;
}

/** Every ban and pick in the order the captains made them. */
export function DraftOrder({ detail }: { detail: Pick<MatchDetail, "draft" | "teams"> }) {
  if (detail.draft.length === 0) return null;
  const sides: Partial<Record<Team, Side | null>> = Object.fromEntries(detail.teams.map((t) => [t.team, t.side]));
  const names: Partial<Record<Team, string | null>> = Object.fromEntries(detail.teams.map((t) => [t.team, t.name]));
  return (
    <Card aria-labelledby="draft-order" className="gap-3 border border-border p-5">
      <h2 id="draft-order" className="text-base font-bold">
        Draft
      </h2>
      <ol className="grid grid-cols-3 gap-1.5 text-xs sm:grid-cols-6 lg:grid-cols-9">
        {detail.draft.map((step, index) => (
          <DraftStep key={`${index}-${step.champion.id}`} step={step} side={sides[step.team] ?? null} team={names[step.team] ?? `Team ${step.team}`} />
        ))}
      </ol>
    </Card>
  );
}

const STEP_CLASS: Record<Side | "ban", string> = {
  ban: "bg-danger-soft text-danger-soft-foreground",
  hk: "bg-team-hk-soft text-team-hk-soft-foreground",
  am: "bg-team-am-soft text-team-am-soft-foreground",
};

function DraftStep({ step, side, team }: { step: DraftPick; side: Side | null; team: string }) {
  const tone = step.action === "ban" ? STEP_CLASS.ban : side ? STEP_CLASS[side] : "bg-surface-secondary";
  const verb = step.action === "ban" ? "Ban" : "Pick";
  return (
    <li aria-label={`${team}: ${verb.toLowerCase()} ${step.champion.name}`} className={`flex flex-col gap-0.5 rounded-lg p-2 ${tone}`}>
      <span className={`font-bold ${step.action === "ban" ? "line-through" : ""}`}>{step.champion.name}</span>
      <span className="truncate opacity-80">{verb}</span>
    </li>
  );
}

/** One team: its heroes, then each player with their award, stat line and rating change. */
export function TeamRecord({ team, won, myId }: { team: TeamResult; won: boolean | null; myId: string | null }) {
  const headingId = `record-${team.team}`;
  const name = team.name ?? `Team ${team.team}`;
  return (
    <Card aria-labelledby={headingId} className="min-w-0 flex-1 basis-105 gap-4 border border-border p-5.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id={headingId} className="text-lg font-bold">
          {name}
        </h2>
        <span className="flex items-center gap-2">
          {team.side ? <SideChip side={team.side} /> : null}
          {won !== null ? (
            <Chip size="sm" variant="soft" color={won ? "success" : "default"} className="font-semibold">
              {won ? "Won" : "Lost"}
            </Chip>
          ) : null}
        </span>
      </div>
      {team.picks.length > 0 ? (
        <ul aria-label={`${name} heroes`} className="grid grid-cols-3 gap-2 sm:grid-cols-6">
          {team.picks.map((hero) => (
            <li key={hero.id}>
              <HeroCard champion={hero} tone={team.side ?? undefined} compact />
            </li>
          ))}
        </ul>
      ) : null}
      <ul aria-label={`${name} players`} className="flex flex-col gap-1 text-sm">
        {team.players.map((p) => (
          <RecordLine key={p.id} player={p} isYou={p.id === myId} />
        ))}
      </ul>
      {team.average_rating !== null ? (
        <p className="text-xs text-muted tabular-nums">Average rating {number(Math.round(team.average_rating))}</p>
      ) : null}
    </Card>
  );
}

function RecordLine({ player, isYou }: { player: ResultPlayer; isYou: boolean }) {
  return (
    <li
      className={`flex items-center gap-2.5 rounded-xl px-3 py-2 ${isYou ? "bg-accent-soft text-accent-soft-foreground" : "bg-background"}`}
    >
      <PlayerAvatar name={player.name} url={player.avatar_url} />
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="flex min-w-0 items-center gap-1.5">
          <span className={`truncate ${isYou ? "font-bold" : "font-medium"}`}>
            {player.name}
          </span>
          {player.is_captain ? <span className="text-xs opacity-70">C</span> : null}
          {player.award ? (
            <Chip size="sm" variant="soft" className={`font-bold ${AWARD_CLASS[player.award]}`}>
              {AWARD_LABEL[player.award]}
            </Chip>
          ) : null}
          {isYou ? <span className="sr-only">(you)</span> : null}
        </span>
        {player.stat_line ? <span className="truncate text-xs text-muted">{player.stat_line}</span> : null}
      </span>
      <span className="flex flex-col items-end">
        <span className={`font-semibold tabular-nums ${deltaClass(player.delta)}`}>{signed(player.delta)}</span>
        <span className="text-xs text-muted tabular-nums">{number(player.rating_after)}</span>
      </span>
    </li>
  );
}

/** The awards, MVP first. */
export function awardWinners(detail: MatchDetail): { player: ResultPlayer; award: Award }[] {
  const all = detail.teams.flatMap((t) => t.players).filter((p): p is ResultPlayer & { award: Award } => p.award !== null);
  return all
    .sort((a, b) => (a.award === b.award ? 0 : a.award === "mvp" ? -1 : 1))
    .map((player) => ({ player, award: player.award }));
}

export function AwardsCard({ detail }: { detail: MatchDetail }) {
  const winners = awardWinners(detail);
  if (winners.length === 0) return null;
  return (
    <Card aria-label="Awards" className="min-w-0 flex-1 basis-65 justify-center gap-3.5 border border-border p-5.5">
      {winners.map(({ player, award }) => (
        <span key={player.id} className="flex items-center gap-3">
          <Chip size="sm" variant="soft" className={`font-bold ${AWARD_CLASS[award]}`}>
            {AWARD_LABEL[award]}
          </Chip>
          <span className="text-base font-semibold">
            {player.name}
          </span>
        </span>
      ))}
    </Card>
  );
}
