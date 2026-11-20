import { Button, Card, Spinner } from "@heroui/react";
import { useState } from "react";

import { MatchShell } from "../../components/MatchShell";
import { PlayerAvatar } from "../../components/PlayerAvatar";
import { TeamPanel } from "../../components/TeamPanel";
import { notify } from "../../components/toast";
import { TurnBanner } from "../../components/TurnBanner";
import { TurnStrip } from "../../components/TurnStrip";
import { byName, number, teamName } from "../../lib/format";
import { playerDraftLine, playerPickSteps, stepIndex, turnTitle } from "../../match/draft";
import { useAction } from "../../../live/hooks";
import type { MatchPlayer, MatchSnap } from "../../../live/types";
import type { MatchScreenProps } from "./types";

/** 2.5 Player draft: the captain on turn picks from the pool; everyone else watches. */
export function PlayerDraft({ match }: MatchScreenProps) {
  const acting = match.viewer.is_acting && match.turn?.action === "player_pick";
  const seats = Math.ceil(match.players.length / 2);
  const turnTeam = match.turn?.team ?? null;
  return (
    <MatchShell match={match} width="wide">
      <TurnBanner
        line={playerDraftLine(match)}
        title={turnTitle(match)}
        deadline={match.deadline_at}
        tone={acting ? "accent" : "default"}
      />
      <TurnStrip steps={playerPickSteps(match)} label="Pick order" />
      <div className="flex flex-wrap items-start gap-5">
        <TeamPanel match={match} team="A" seats={seats} highlight={turnTeam === "A"} />
        <Pool match={match} acting={acting} />
        <TeamPanel match={match} team="B" seats={seats} highlight={turnTeam === "B"} />
      </div>
    </MatchShell>
  );
}

function Pool({ match, acting }: { match: MatchSnap; acting: boolean }) {
  const action = useAction();
  const [picking, setPicking] = useState<string | null>(null);
  const step = stepIndex(match);
  // Still to pick first, then the picked ones by name.
  const players = match.players
    .filter((p) => !p.is_captain)
    .sort((a, b) => Number(a.team !== null) - Number(b.team !== null) || b.rating - a.rating || byName(a, b));

  const pick = (player: MatchPlayer) => {
    if (step === null) return;
    setPicking(player.id);
    action
      .run("draft.pick_player", { match_id: match.id, step_index: step, player_id: player.id })
      .catch(notify.error)
      .finally(() => setPicking(null));
  };

  return (
    <Card aria-labelledby="pool" className="min-w-0 flex-999 basis-130 gap-3 border border-border p-4.5">
      <h2 id="pool" className="text-base font-bold">
        Players
      </h2>
      <ul className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 xl:grid-cols-3">
        {players.map((player) => (
          <li key={player.id}>
            <PoolPlayer
              match={match}
              player={player}
              onPick={acting && player.team === null && step !== null ? () => pick(player) : undefined}
              isPending={picking === player.id}
              isDisabled={action.pending}
            />
          </li>
        ))}
      </ul>
    </Card>
  );
}

interface PoolPlayerProps {
  match: MatchSnap;
  player: MatchPlayer;
  onPick?: () => void;
  isPending: boolean;
  isDisabled: boolean;
}

function PoolPlayer({ match, player, onPick, isPending, isDisabled }: PoolPlayerProps) {
  const taken = player.team !== null;
  const detail = taken ? teamName(match.team_names, player.team ?? "A") : player.rating > 0 ? number(player.rating) : null;
  const body = (
    <>
      <PlayerAvatar name={player.name} url={player.avatar_url} size="md" className="shrink-0" />
      <span className="flex min-w-0 flex-1 flex-col text-left">
        <span className="truncate text-base font-semibold">{player.name}</span>
        {detail ? <span className="truncate text-sm text-muted">{detail}</span> : null}
      </span>
    </>
  );
  const frame = "flex min-h-17 w-full items-center gap-3 rounded-2xl border-2 p-3.5";
  if (!onPick) {
    return <div className={`${frame} ${taken ? "border-border bg-background opacity-60" : "border-border bg-surface-secondary"}`}>{body}</div>;
  }
  return (
    <Button
      variant="tertiary"
      onPress={onPick}
      isPending={isPending}
      isDisabled={isDisabled}
      aria-label={`Pick ${player.name}`}
      className={`h-auto whitespace-normal border-default bg-surface-secondary text-foreground ${frame}`}
    >
      {body}
      <span className="flex shrink-0 items-center gap-1.5 rounded-full bg-accent px-3 py-1.5 text-sm font-semibold text-accent-foreground">
        {isPending ? <Spinner color="current" size="sm" /> : null}
        Pick
      </span>
    </Button>
  );
}
