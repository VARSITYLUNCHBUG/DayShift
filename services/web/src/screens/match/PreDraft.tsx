// Before the draft: the ready check and its refill (B01, B02), the captain vote (B03) and the
// captains' check-in (B04).
import { useState } from "react";
import { ToggleButton } from "react-aria-components/ToggleButton";

import { Button } from "../../components/Button";
import { Countdown } from "../../components/Countdown";
import { Icon } from "../../components/Icon";
import { InlineAlert } from "../../components/InlineAlert";
import { Panel } from "../../components/Layout";
import { PlayerTile } from "../../components/PlayerTile";
import { notify } from "../../components/toast";
import { cn } from "../../lib/cn";
import { byName, number, plural } from "../../lib/format";
import type { MatchPlayer } from "../../live/protocol.gen";
import { useMatchAction } from "../../match/live";
import { StageHead } from "./Parts";
import { Room, useMe } from "./Room";
import type { MatchScreenProps } from "./types";

// --- Ready check -------------------------------------------------------------------------------

export function ReadyCheck({ match }: MatchScreenProps) {
  const { myId } = useMe(match);
  const act = useMatchAction();
  const me = match.players.find((p) => p.id === myId);
  const ready = match.players.filter((p) => p.is_ready);
  const waiting = match.players.filter((p) => !p.is_ready).sort(byName);
  const refills = match.subs.filter((s) => s.reason === "missed_ready");
  const seats = match.players.length + refills.length;
  const iAmReady = me?.is_ready ?? false;
  const canReady = match.viewer.is_player && me !== undefined && !iAmReady;
  const press = () => {
    act.run("lobby.ready", { match_id: match.id }).catch(notify.error);
  };
  const readyButton = match.viewer.is_player ? (
    <Button
      size="lg"
      kind={iAmReady ? "ghost" : "primary"}
      icon={iAmReady ? "check" : undefined}
      isDisabled={!canReady}
      onPress={press}
      isPending={act.pending === "lobby.ready"}
      pendingLabel="Sending…"
    >
      {iAmReady ? "You're ready" : "Ready"}
    </Button>
  ) : null;
  const waitNames = waiting.map((p) => p.name).join(", ");

  return (
    <Room
      match={match}
      now={{
        title: refills.length ? "Refilling a seat" : "Ready check",
        line: `${ready.length} of ${seats} ready · the draft starts when all ${seats} are in`,
        deadline: refills[0]?.deadline_at ?? match.deadline_at,
        announce: canReady ? "to press Ready" : undefined,
      }}
      footer={canReady ? readyButton : undefined}
      rail={
        <Panel as="aside">
          <h2 className="text-card">If you miss it</h2>
          <p className="mt-2 text-caption text-muted">
            Your spot goes to the next player in the queue, and you get a strike and a short queue cooldown. Three clean matches
            take a strike off.
          </p>
        </Panel>
      }
    >
      <section className="flex flex-wrap items-center justify-between gap-6 rounded-panel border border-line-strong bg-surface p-7">
        <div className="flex min-w-0 flex-1 basis-80 flex-col gap-2">
          <span className="text-label font-bold text-muted">Match found · {match.mode_name}</span>
          <h1 className="text-board max-md:text-coin">
            {match.viewer.is_player ? `You're in No. ${match.id}` : `No. ${match.id} is checking in`}
          </h1>
          <p className="text-body text-muted">
            {!match.viewer.is_player
              ? "The 12 press Ready, then the captain vote opens."
              : iAmReady
                ? waiting.length
                  ? `You pressed Ready. Waiting on ${plural(waiting.length, "more player")}.`
                  : "You pressed Ready. Everyone's in."
                : "Press Ready to keep your place."}
          </p>
        </div>
        {readyButton ? <div className="max-md:hidden">{readyButton}</div> : null}
      </section>

      <section aria-labelledby="the-12" className="flex flex-col gap-3">
        <div className="flex items-baseline justify-between gap-3">
          <h2 id="the-12" className="text-section">
            The {seats}
          </h2>
          <span role="status" className="text-label font-bold">
            {ready.length} of {seats} ready
          </span>
        </div>
        <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-3">
          {[...match.players].sort(byName).map((p) => (
            <PlayerTile
              key={p.id}
              name={p.name}
              avatar={p.avatar_url}
              ready={p.is_ready}
              isYou={p.id === myId}
              className={cn("border bg-surface", p.id === myId ? "border-foreground" : "border-line")}
              action={
                <span
                  className={cn("flex items-center gap-1 text-caption font-bold", p.is_ready ? "text-foreground" : "text-muted")}
                >
                  {p.is_ready ? <Icon name="check" size={16} /> : null}
                  {p.is_ready ? "Ready" : "Waiting"}
                </span>
              }
            />
          ))}
          {refills.map((line) => (
            <li
              key={line.id}
              className="flex min-h-14 items-center gap-3 rounded-row border border-dashed border-line-strong px-3 py-2"
            >
              <span className="flex min-w-0 flex-col">
                <b className="truncate">{line.offer ? line.offer.name : "Open seat"}</b>
                <span className="text-caption text-muted">
                  {line.offer ? `Offered ${line.leaving_name}'s seat` : `${line.leaving_name} missed it · asking the queue`}
                </span>
              </span>
              <span className="ml-auto text-caption font-bold text-muted">Refilling</span>
            </li>
          ))}
        </ul>
      </section>

      {waiting.length && iAmReady ? (
        <Panel>
          <h2 className="text-card">Still waiting on {waitNames}</h2>
          <p className="mt-2 text-caption text-muted">
            They have <Countdown deadline={match.deadline_at} /> to press Ready. Nothing for you to do until then. If someone
            misses it, their spot is offered to the queue.
          </p>
        </Panel>
      ) : null}
    </Room>
  );
}

// --- Captain vote ------------------------------------------------------------------------------

export function CaptainVote({ match }: MatchScreenProps) {
  const { myId } = useMe(match);
  const act = useMatchAction();
  // Null until the player changes their choice: until then it shows the vote they cast.
  const [edited, setEdited] = useState<string[] | null>(null);
  const [full, setFull] = useState(false);
  const canVote = match.viewer.is_player;
  const limit = match.votes_per_player;
  const cast = match.viewer.votes;
  const chosen = edited ?? cast;
  const unchanged = match.viewer.has_voted && chosen.length === cast.length && chosen.every((id) => cast.includes(id));
  const voted = match.players.filter((p) => p.has_voted).length;
  const players = [...match.players].sort(
    (a, b) => Number(b.captain_ok) - Number(a.captain_ok) || b.rating - a.rating || byName(a, b),
  );

  const toggle = (id: string, on: boolean) => {
    if (!on) {
      setFull(false);
      setEdited(chosen.filter((c) => c !== id));
      return;
    }
    if (chosen.length >= limit) {
      setFull(true);
      return;
    }
    setEdited([...chosen, id]);
  };
  const vote = () => {
    act.run("lobby.vote", { match_id: match.id, candidate_ids: chosen }).then(() => setEdited(null), notify.error);
  };
  const voteButton = canVote ? (
    <Button
      size="lg"
      isDisabled={chosen.length === 0 || unchanged}
      onPress={vote}
      isPending={act.pending === "lobby.vote"}
      pendingLabel="Sending…"
    >
      {match.viewer.has_voted
        ? unchanged
          ? "Vote in"
          : "Change my vote"
        : chosen.length
          ? `Vote for ${plural(chosen.length, "captain")}`
          : "Vote"}
    </Button>
  ) : null;
  const words = limit === 1 ? "a captain" : `up to ${limit === 2 ? "two" : limit} captains`;

  return (
    <Room
      match={match}
      now={{
        title: "Captain vote",
        line: `${voted} of ${match.players.length} voted · closes early when everyone has`,
        deadline: match.deadline_at,
        announce: canVote && !match.viewer.has_voted ? "to vote" : undefined,
      }}
      footer={voteButton}
      rail={
        <Panel as="aside">
          <h2 className="text-card">How it&apos;s decided</h2>
          <p className="mt-2 text-caption text-muted">
            The {limit === 1 ? "one" : "two"} with the most votes captain. Rating breaks a tie and fills a gap if too few get
            votes.
            {match.captain_min_games > 0
              ? ` Captains need ${plural(match.captain_min_games, "completed match", "completed matches")}.`
              : ""}
          </p>
        </Panel>
      }
    >
      <StageHead
        eyebrow="Captains"
        title={canVote ? `Vote for ${words}` : "Captain vote"}
        lead={
          canVote
            ? "Press a name to choose, press it again to take it back, then send your vote. You can change it until the vote closes."
            : "The players are choosing two captains."
        }
        action={voteButton}
      />
      {canVote && match.viewer.has_voted && unchanged ? (
        <p role="status" className="flex items-center gap-1.5 text-label font-bold">
          <Icon name="check" size={16} /> Your vote is in.
        </p>
      ) : null}
      {full ? (
        <InlineAlert kind="info" title={`You've used ${limit === 2 ? "both votes" : plural(limit, "vote")}`}>
          Take one back first, then vote for someone else.
        </InlineAlert>
      ) : null}
      <ul aria-label="Candidates" className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 xl:grid-cols-3">
        {players.map((p) => (
          <li key={p.id}>
            <Candidate
              player={p}
              isYou={p.id === myId}
              isSelected={chosen.includes(p.id)}
              onToggle={canVote ? (on) => toggle(p.id, on) : undefined}
            />
          </li>
        ))}
      </ul>
    </Room>
  );
}

function Candidate({
  player,
  isYou,
  isSelected,
  onToggle,
}: {
  player: MatchPlayer;
  isYou: boolean;
  isSelected: boolean;
  onToggle?: (on: boolean) => void;
}) {
  const blocked = !player.captain_ok;
  const detail = blocked
    ? player.captain_note || "Can't captain yet"
    : player.rating > 0
      ? `${number(player.rating)} rating`
      : null;
  const body = (
    <>
      <PlayerTile
        as="div"
        name={player.name}
        avatar={player.avatar_url}
        isYou={isYou}
        line={detail}
        className="min-w-0 flex-1 px-0 py-0"
      />
      {player.has_voted ? <span className="text-micro font-bold text-muted">Voted</span> : null}
      {isSelected ? <span className="text-micro font-extrabold">Your vote</span> : null}
    </>
  );
  const frame = cn(
    "flex min-h-16 w-full items-center gap-3 rounded-card border-2 bg-surface px-3.5 py-2.5 text-left outline-none transition-state",
    isSelected ? "border-foreground bg-raised" : "border-line",
    blocked && "opacity-60",
  );
  if (!onToggle) return <div className={frame}>{body}</div>;
  return (
    <ToggleButton
      isSelected={isSelected}
      isDisabled={blocked}
      onChange={onToggle}
      aria-label={blocked ? `${player.name}, can't captain: ${detail ?? ""}` : `Vote for ${player.name}`}
      className={cn(frame, blocked ? "cursor-not-allowed" : "cursor-pointer")}
    >
      {body}
    </ToggleButton>
  );
}

// --- Captain check-in --------------------------------------------------------------------------

export function CaptainCheckIn({ match }: MatchScreenProps) {
  const { myId } = useMe(match);
  const act = useMatchAction();
  const captains = match.players.filter((p) => p.is_captain).sort(byName);
  const isCaptain = match.viewer.is_captain;
  const done = match.viewer.checked_in;
  const checkIn = () => {
    act.run("lobby.checkin", { match_id: match.id }).catch(notify.error);
  };
  const button = isCaptain ? (
    <Button
      size="lg"
      kind={done ? "ghost" : "primary"}
      icon={done ? "check" : undefined}
      isDisabled={done}
      onPress={checkIn}
      isPending={act.pending === "lobby.checkin"}
      pendingLabel="Sending…"
    >
      {done ? "You're checked in" : "I'm here"}
    </Button>
  ) : null;
  const ins = captains.filter((p) => p.checked_in).length;
  return (
    <Room
      match={match}
      now={{
        title: isCaptain && !done ? "Your check-in" : "Captains check in",
        line: `${ins} of ${captains.length} captains in · then the player draft starts`,
        deadline: match.deadline_at,
        announce: isCaptain && !done ? "to check in" : undefined,
      }}
      footer={isCaptain && !done ? button : undefined}
    >
      <StageHead
        eyebrow="Captains"
        title={isCaptain ? (done ? "You're checked in" : "You're a captain. Check in") : "The captains are checking in"}
        lead={
          isCaptain
            ? "Press I'm here so the draft knows you're at your keyboard. No check-in in time and the next in line captains instead."
            : "When both captains are in, the player draft starts."
        }
        action={button}
      />
      <ul aria-label="Captains" className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
        {captains.map((p) => (
          <PlayerTile
            key={p.id}
            name={p.name}
            avatar={p.avatar_url}
            isYou={p.id === myId}
            line="Captain"
            className="border border-line bg-surface"
            action={
              <span
                className={cn("flex items-center gap-1 text-caption font-bold", p.checked_in ? "text-foreground" : "text-muted")}
              >
                {p.checked_in ? <Icon name="check" size={16} /> : null}
                {p.checked_in ? "Checked in" : "Not yet"}
              </span>
            }
          />
        ))}
      </ul>
    </Room>
  );
}
