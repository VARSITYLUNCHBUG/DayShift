import { Card, Chip } from "@heroui/react";

import { useMatchDetail } from "../../../api/matches";
import { ButtonLink } from "../../components/ButtonLink";
import { HeroCard } from "../../components/HeroCard";
import { MatchShell } from "../../components/MatchShell";
import { PlayerAvatar } from "../../components/PlayerAvatar";
import { SIDE_NAME, SideChip } from "../../components/SideChip";
import { number, signed, teamName } from "../../lib/format";
import { teamPlayers } from "../../match/draft";
import { usePlayerId } from "../../../live/hooks";
import type { MatchDetail, MatchPlayer, MatchSnap, Team } from "../../../live/types";
import {
  AwardsCard,
  deltaClass,
  DraftOrder,
  length,
  myLine,
  RecordTiles,
  TeamRecord,
  WIN_TONE,
} from "../matches/MatchRecord";
import { ScoreNames } from "./ScoreNames";
import type { MatchScreenProps } from "./types";

/** The header's "Queue again": back to Play, where the queue is. */
export function QueueAgain() {
  return (
    <ButtonLink to="/" size="sm" className="h-11 px-4.5 font-bold">
      Queue again
    </ButtonLink>
  );
}

/** 3.6 Result: who won, the viewer's own rating change, the awards, and each team's heroes and
 * changes. The snapshot has the outcome; the match's record (GET /api/matches/<id>/) adds the
 * awards, stat lines, ratings before and after, the length and the draft order (5.2). */
export function Completed({ match }: MatchScreenProps) {
  const myId = usePlayerId();
  const { data: detail } = useMatchDetail(match.id);
  const winner = match.result.winner;
  const side = winner ? match.sides[winner] : null;
  const tone = side ? WIN_TONE[side] : null;
  const myTeam = match.viewer.is_player ? match.viewer.team : null;
  const mine = detail ? myLine(detail, myId) : undefined;
  // The record's change includes later corrections (awards, say); the snapshot's is the live one.
  const myDelta = mine?.delta ?? (myId && myTeam ? match.result.deltas[myId] : undefined);
  const heading = winner && myTeam ? (myTeam === winner ? "Victory" : "Defeat") : "Result";
  const line = [
    winner ? `${teamName(match.team_names, winner)} won` : null,
    side ? SIDE_NAME[side] : null,
    detail ? length(detail) : null,
    match.draft_name || null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <MatchShell match={match} width="wide" actions={<QueueAgain />}>
      <section aria-label="Result" className="flex flex-wrap gap-5">
        <Card
          className={`min-w-0 flex-2 basis-105 flex-row flex-wrap items-center justify-between gap-5 border p-7 ${tone ? tone.card : "border-border"}`}
        >
          <div className="flex flex-col gap-1.5">
            <span className={`text-sm font-semibold ${tone ? tone.line : "text-muted"}`}>{line}</span>
            <h1 className="text-5xl font-bold tracking-tight">{heading}</h1>
          </div>
          {myDelta !== undefined ? (
            <div className="flex flex-col items-end gap-1">
              <span className={`text-4xl font-bold tabular-nums ${deltaClass(myDelta)}`}>{signed(myDelta)}</span>
              <span className="text-sm opacity-85 tabular-nums">
                {mine ? `${number(mine.rating_before)} → ${number(mine.rating_after)}` : "Your rating"}
              </span>
              {mine ? <span className="sr-only">Your rating</span> : null}
            </div>
          ) : null}
        </Card>
        {detail ? <AwardsCard detail={detail} /> : null}
        {match.gif_url ? (
          <Card className="min-w-0 flex-1 basis-65 items-center justify-center overflow-hidden border border-border p-0">
            <img src={match.gif_url} alt={match.draft_name || "The draft's gif"} className="max-h-60 w-full object-cover" />
          </Card>
        ) : null}
      </section>

      {match.scoreboard ? <ScoreNames match={match} scoreboard={match.scoreboard} /> : null}

      {detail ? <Record detail={detail} myId={myId} /> : <SnapshotTeams match={match} myId={myId} />}
    </MatchShell>
  );
}

function Record({ detail, myId }: { detail: MatchDetail; myId: string | null }) {
  return (
    <>
      <RecordTiles detail={detail} showWinner={false} />
      <DraftOrder detail={detail} />
      <div className="flex flex-wrap gap-5">
        {detail.teams.map((team) => (
          <TeamRecord key={team.team} team={team} won={detail.winner ? detail.winner === team.team : null} myId={myId} />
        ))}
      </div>
    </>
  );
}

/** Before the record loads (or if it can't): the teams as the snapshot has them. */
function SnapshotTeams({ match, myId }: { match: MatchSnap; myId: string | null }) {
  return (
    <div className="flex flex-wrap gap-5">
      <TeamResult match={match} team="A" myId={myId} />
      <TeamResult match={match} team="B" myId={myId} />
    </div>
  );
}

function TeamResult({ match, team, myId }: { match: MatchSnap; team: Team; myId: string | null }) {
  const side = match.sides[team];
  const won = match.result.winner === team;
  const heroes = match.draft.filter((d) => d.team === team && d.action === "pick" && d.champion);
  const headingId = `result-${match.id}-${team}`;
  const name = teamName(match.team_names, team);
  return (
    <Card aria-labelledby={headingId} className="min-w-0 flex-1 basis-105 gap-4 border border-border p-5.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id={headingId} className="text-lg font-bold">
          {name}
        </h2>
        <span className="flex items-center gap-2">
          {side ? <SideChip side={side} /> : null}
          <Chip size="sm" variant="soft" color={won ? "success" : "default"} className="font-semibold">
            {won ? "Won" : "Lost"}
          </Chip>
        </span>
      </div>
      {heroes.length > 0 ? (
        <ul aria-label={`${name} heroes`} className="grid grid-cols-3 gap-2 sm:grid-cols-6">
          {heroes.map((entry) =>
            entry.champion ? (
              <li key={entry.champion.id}>
                <HeroCard champion={entry.champion} tone={side ?? undefined} compact />
              </li>
            ) : null,
          )}
        </ul>
      ) : null}
      <ul aria-label={`${name} players`} className="flex flex-col gap-1 text-sm">
        {teamPlayers(match, team).map((p) => (
          <PlayerLine key={p.id} player={p} delta={match.result.deltas[p.id]} isYou={p.id === myId} />
        ))}
      </ul>
    </Card>
  );
}

function PlayerLine({ player, delta, isYou }: { player: MatchPlayer; delta: number | undefined; isYou: boolean }) {
  return (
    <li
      className={`flex items-center gap-2.5 rounded-xl px-3 py-2 ${isYou ? "bg-accent-soft text-accent-soft-foreground" : "bg-background"}`}
    >
      <PlayerAvatar name={player.name} url={player.avatar_url} />
      <span className={`min-w-0 truncate ${isYou ? "font-bold" : ""}`}>{player.name}</span>
      {player.is_captain ? <span className="text-xs opacity-70">C</span> : null}
      {isYou ? <span className="sr-only">(you)</span> : null}
      <span className={`ml-auto font-semibold tabular-nums ${deltaClass(delta)}`}>
        {delta === undefined ? "–" : signed(delta)}
      </span>
    </li>
  );
}
