import { Check, Lock } from "@gravity-ui/icons";
import { Button, Spinner, ToggleButton } from "@heroui/react";
import { useState } from "react";

import { Countdown } from "../../components/Countdown";
import { EmptyState } from "../../components/EmptyState";
import { MatchShell } from "../../components/MatchShell";
import { PlayerAvatar } from "../../components/PlayerAvatar";
import { notify } from "../../components/toast";
import { byName, number, plural } from "../../lib/format";
import { useAction, usePlayerId, useTopic } from "../../../live/hooks";
import type { MatchPlayer } from "../../../live/types";
import type { MatchScreenProps } from "./types";

/** 2.4 Captain vote. With Auto Captain on the server skips this status, so it only shows a
 * waiting line if it ever arrives. */
export function CaptainVote({ match }: MatchScreenProps) {
  const { data: me } = useTopic("me");
  const myId = usePlayerId();
  const action = useAction();
  // Null until the player changes their choice: until then it shows the vote they cast, which the
  // snapshot sends back, so it survives a reload.
  const [edited, setEdited] = useState<string[] | null>(null);

  if (me?.flags.auto_captain) {
    return (
      <MatchShell match={match}>
        <EmptyState
          title="Picking captains"
          description="Captains are chosen automatically for this match."
          icon={<Spinner size="sm" color="current" />}
        />
      </MatchShell>
    );
  }

  const canVote = match.viewer.is_player;
  const voted = match.players.filter((p) => p.has_voted).length;
  const players = [...match.players].sort(
    (a, b) => Number(b.captain_ok) - Number(a.captain_ok) || b.rating - a.rating || byName(a, b),
  );

  const cast = match.viewer.votes;
  const chosen = edited ?? cast;
  const unchanged = match.viewer.has_voted && chosen.length === cast.length && chosen.every((id) => cast.includes(id));
  const limit = match.votes_per_player;
  const toggle = (id: string, on: boolean) => {
    setEdited((before) => {
      const current = before ?? cast;
      if (!on) return current.filter((c) => c !== id);
      // At the limit, the newest choice replaces the oldest.
      const kept = current.length >= limit ? current.slice(current.length - limit + 1) : current;
      return [...kept, id];
    });
  };

  const vote = () => {
    action
      .run("lobby.vote", { match_id: match.id, candidate_ids: chosen })
      .then(() => setEdited(null))
      .catch(notify.error);
  };

  const line = [
    `Up to ${limit}`,
    `${voted} / ${match.players.length} voted`,
    match.captain_min_games > 0 ? `Captains need ${plural(match.captain_min_games, "match", "matches")}` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <MatchShell match={match} width="wide">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex flex-col gap-1">
          <h1 className="text-3xl font-bold tracking-tight">{canVote ? "Vote for captains" : "Captain vote"}</h1>
          <span className="text-sm text-muted">{line}</span>
        </div>
        <div className="flex items-center gap-4">
          <Countdown deadline={match.deadline_at} className="text-3xl font-bold" />
          {canVote ? (
            <Button
              size="lg"
              isDisabled={chosen.length === 0 || unchanged}
              isPending={action.pending}
              onPress={vote}
              className="h-13 rounded-2xl px-7 font-bold"
            >
              {({ isPending }) => (
                <>
                  {isPending ? <Spinner color="current" size="sm" /> : null}
                  {match.viewer.has_voted ? "Update vote" : "Vote"}
                </>
              )}
            </Button>
          ) : null}
        </div>
      </div>
      {canVote && match.viewer.has_voted ? (
        <span role="status" className="-mt-4 flex items-center gap-1.5 text-sm text-success">
          <Check width={16} height={16} aria-hidden="true" />
          Your vote is in. You can change it until the vote closes.
        </span>
      ) : null}

      <ul aria-label="Candidates" className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {players.map((player) => (
          <li key={player.id}>
            <Candidate
              player={player}
              isYou={player.id === myId}
              isSelected={chosen.includes(player.id)}
              onToggle={canVote ? (on) => toggle(player.id, on) : undefined}
            />
          </li>
        ))}
      </ul>
    </MatchShell>
  );
}

interface CandidateProps {
  player: MatchPlayer;
  isYou: boolean;
  isSelected: boolean;
  /** Left out for spectators, who only watch. */
  onToggle?: (on: boolean) => void;
}

function Candidate({ player, isYou, isSelected, onToggle }: CandidateProps) {
  const name = isYou ? `${player.name} (you)` : player.name;
  const blocked = !player.captain_ok;
  const detail = blocked ? player.captain_note || "Can't captain yet" : player.rating > 0 ? number(player.rating) : null;
  const body = (
    <>
      {blocked ? (
        <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-surface-tertiary text-muted">
          <Lock width={16} height={16} aria-hidden="true" />
        </span>
      ) : (
        <PlayerAvatar name={player.name} url={player.avatar_url} size="md" className="shrink-0" />
      )}
      <span className="flex min-w-0 flex-1 flex-col gap-0.5 text-left">
        <span className={`truncate text-base font-semibold ${blocked ? "text-muted" : ""}`}>{name}</span>
        {detail ? <span className="truncate text-sm text-muted">{detail}</span> : null}
      </span>
      {player.has_voted ? (
        <span className="flex shrink-0 items-center gap-1 text-xs font-semibold text-success">
          <Check width={14} height={14} aria-hidden="true" />
          Voted
        </span>
      ) : null}
    </>
  );
  const frame = `flex min-h-18 w-full items-center gap-3 rounded-2xl border-2 p-4 ${
    isSelected ? "border-accent bg-accent-soft" : blocked ? "border-border bg-background" : "border-border bg-surface"
  }`;
  if (!onToggle) return <div className={frame}>{body}</div>;
  return (
    <ToggleButton
      isSelected={isSelected}
      isDisabled={blocked}
      onChange={onToggle}
      aria-label={
        blocked ? `${name}, can't captain: ${detail}` : `Vote for ${name}${player.has_voted ? " (has voted)" : ""}`
      }
      className={`h-auto whitespace-normal text-foreground ${frame}`}
    >
      {body}
    </ToggleButton>
  );
}
