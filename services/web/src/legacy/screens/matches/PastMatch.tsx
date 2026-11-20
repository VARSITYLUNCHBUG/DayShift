import { Button, Chip, Spinner } from "@heroui/react";

import { isNotFound, useMatchDetail } from "../../../api/matches";
import { AppShell } from "../../components/AppShell";
import { ButtonLink } from "../../components/ButtonLink";
import { EmptyState } from "../../components/EmptyState";
import { MatchShell } from "../../components/MatchShell";
import { StatusChip } from "../../components/StatusChip";
import { usePlayerId } from "../../../live/hooks";
import type { MatchDetail } from "../../../live/types";
import { DraftOrder, RecordTiles, TeamRecord } from "./MatchRecord";

/** 5.2: a match the live connection doesn't serve, from its record (GET /api/matches/<id>/). */
export function PastMatch({ id }: { id: string }) {
  const { data, error, isPending, refetch } = useMatchDetail(id);
  if (isPending) {
    return (
      <div className="flex min-h-dvh items-center justify-center">
        <Spinner aria-label="Loading the match" />
      </div>
    );
  }
  if (isNotFound(error) || (!data && !error)) return <MatchNotFound />;
  if (!data) {
    return (
      <AppShell>
        <EmptyState
          title="Couldn't load the match"
          description="Check your connection and try again."
          action={
            <Button variant="secondary" onPress={() => void refetch()}>
              Try again
            </Button>
          }
        />
      </AppShell>
    );
  }
  return <PastMatchView detail={data} />;
}

export function PastMatchView({ detail }: { detail: MatchDetail }) {
  const myId = usePlayerId();
  const title = detail.draft_name ? `Match ${detail.id} · ${detail.draft_name}` : `Match ${detail.id}`;
  return (
    <MatchShell match={detail} width="wide" backTo="/matches" backLabel="Back to Matches">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-bold">{title}</h1>
        <StatusChip status={detail.status} />
        <Chip size="sm" variant="secondary">
          {detail.mode_name}
        </Chip>
      </div>
      <RecordTiles detail={detail} />
      <DraftOrder detail={detail} />
      <div className="flex flex-wrap gap-5">
        {detail.teams.map((team) => (
          <TeamRecord
            key={team.team}
            team={team}
            won={detail.winner ? detail.winner === team.team : null}
            myId={myId}
          />
        ))}
      </div>
    </MatchShell>
  );
}

export function MatchNotFound() {
  return (
    <AppShell>
      <EmptyState
        title="Match not found"
        action={
          <ButtonLink to="/matches" variant="secondary">
            Back to Matches
          </ButtonLink>
        }
      />
    </AppShell>
  );
}
