import { Card, Chip } from "@heroui/react";

import { ButtonLink } from "../../components/ButtonLink";
import { MatchShell } from "../../components/MatchShell";
import { teamName } from "../../lib/format";
import type { MatchSnap, ResultResponse, Side } from "../../../live/types";
import { QueueAgain } from "./Result";
import { ScoreNames } from "./ScoreNames";
import { Teams } from "./TeamSummary";
import type { MatchScreenProps } from "./types";

const CLAIM_CLASS: Record<Side, string> = { hk: "text-team-hk", am: "text-team-am" };

/** 3.7 Result disputed: staff decide. Each captain's answer, as they gave it. */
export function Disputed({ match }: MatchScreenProps) {
  const answers = match.result.responses;
  return (
    <MatchShell match={match} actions={<QueueAgain />}>
      <div className="flex flex-wrap items-start justify-center gap-5">
        <Card aria-labelledby={`review-${match.id}`} className="w-full max-w-120 gap-4 border border-border p-7">
          <Chip color="warning" variant="soft" size="sm" className="self-start font-bold">
            Disputed
          </Chip>
          <h1 id={`review-${match.id}`} className="text-2xl font-bold">
            Staff are reviewing
          </h1>
          {answers.length > 0 ? (
            <dl className="flex flex-col gap-2 text-sm">
              {answers.map((answer) => (
                <div key={answer.player_id} className="flex justify-between gap-3">
                  <dt className="text-muted">{answer.name}</dt>
                  <dd className={`m-0 font-semibold ${claimClass(match, answer)}`}>{claimText(match, answer)}</dd>
                </div>
              ))}
            </dl>
          ) : (
            <p className="text-sm text-muted">No captain reported a result in time.</p>
          )}
          <p className="text-sm text-muted">Ratings won&apos;t change until staff decide.</p>
          <ButtonLink to="/" size="lg" fullWidth className="mt-2 h-12 rounded-xl font-bold">
            Queue again
          </ButtonLink>
        </Card>
        {match.scoreboard ? <ScoreNames match={match} scoreboard={match.scoreboard} /> : null}
      </div>
      <Teams match={match} />
    </MatchShell>
  );
}

function claimText(match: MatchSnap, answer: ResultResponse): string {
  if (answer.winner) return `${teamName(match.team_names, answer.winner)} won`;
  return "Disputed";
}

function claimClass(match: MatchSnap, answer: ResultResponse): string {
  const side = answer.winner ? match.sides[answer.winner] : null;
  return side ? CLAIM_CLASS[side] : "text-danger";
}
