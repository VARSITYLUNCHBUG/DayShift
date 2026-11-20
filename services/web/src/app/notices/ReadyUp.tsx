// Ready Up (A08): the queue filled. Pops over any page except the match's own room, which shows
// its ready check itself. It can't be dismissed with Esc or a click outside: you answer it.
import { useState } from "react";
import { useLocation, useNavigate } from "react-router";

import { useMatchSnap, useMe, usePageAction } from "../../api/live";
import type { MatchSnap } from "../../api/live";
import { Avatar } from "../../components/Avatar";
import { Button } from "../../components/Button";
import { Dialog } from "../../components/Dialog";
import { InlineAlert } from "../../components/InlineAlert";
import { errorText, notify } from "../../components/toast";
import { cn } from "../../lib/cn";
import { matchNo } from "../../screens/shared/format";

interface ViewProps {
  match: MatchSnap;
  playerId: string;
  onSkip: () => void;
}

export function ReadyUpView({ match, playerId, onSkip }: ViewProps) {
  const action = usePageAction();
  const [error, setError] = useState<string | null>(null);
  const players = [...match.players].sort((a, b) => (a.id === playerId ? -1 : b.id === playerId ? 1 : 0));
  const ready = match.players.filter((p) => p.is_ready).length;
  return (
    <Dialog
      isOpen
      mustAnswer
      eyebrow={`${matchNo(match.id)} · ${match.mode_name}`}
      title="Ready Up"
      deadline={match.deadline_at}
      announce="to ready up"
      actions={
        <>
          <Button
            size="lg"
            autoFocus
            className="flex-1"
            isPending={action.pending === "lobby.ready"}
            pendingLabel="Readying…"
            onPress={() => {
              setError(null);
              action.run("lobby.ready", { match_id: match.id }).catch((reason: unknown) => setError(errorText(reason)));
            }}
          >
            Ready
          </Button>
          <Button kind="ghost" size="lg" onPress={onSkip}>
            Not this time
          </Button>
        </>
      }
    >
      <p>The queue filled. Press Ready to take your seat in {matchNo(match.id)}.</p>
      <b className="text-label font-extrabold text-foreground tabular-nums">
        {ready} of {match.players.length} ready
      </b>
      <ul className="grid grid-cols-2 gap-1.5 sm:grid-cols-3" aria-label="Who's ready">
        {players.map((p) => {
          const you = p.id === playerId;
          return (
            <li
              key={p.id}
              className={cn(
                "flex min-h-11 items-center gap-2 rounded-small border px-2.5 py-1.5",
                you ? "border-foreground" : p.is_ready ? "border-line bg-raised" : "border-line bg-background",
              )}
            >
              <Avatar name={p.name} src={p.avatar_url} size="sm" ready={p.is_ready} />
              <span className={cn("min-w-0 truncate text-caption font-bold", p.is_ready || you ? "text-foreground" : "text-muted")}>
                {p.name}
                {you ? " (you)" : ""}
              </span>
              <span className="sr-only">{p.is_ready ? ", ready" : ", not yet"}</span>
            </li>
          );
        })}
      </ul>
      {error ? <InlineAlert title="You're not ready yet">{error}</InlineAlert> : null}
      <p className="text-caption">
        Not this time counts as a missed ready check: a strike and a short cooldown, and your seat goes to the next player. It&apos;s the same check
        as the one in Discord.
      </p>
    </Dialog>
  );
}

/** Mounted once under the live connection. */
export function ReadyUp() {
  const me = useMe();
  const location = useLocation();
  const navigate = useNavigate();
  const [skipped, setSkipped] = useState<string | null>(null);
  const current = me.data?.match;
  const id = current?.status === "ready_check" ? current.id : null;
  const snap = useMatchSnap(id);
  const match = snap.data;
  const playerId = me.data?.player.id ?? "";
  if (!id || !match || match.status !== "ready_check") return null;
  // The room has its own ready check (B01).
  if (location.pathname === `/matches/${id}` || location.pathname.startsWith(`/matches/${id}/`)) return null;
  const mine = match.players.find((p) => p.id === playerId);
  if (!mine || mine.is_ready || skipped === id) return null;
  return (
    <ReadyUpView
      key={id}
      match={match}
      playerId={playerId}
      onSkip={() => {
        setSkipped(id);
        notify.info(
          "You're sitting this one out",
          `When the clock runs out it counts as a missed ready check: a strike and a short cooldown. Changed your mind? Open ${matchNo(id)} and press Ready.`,
          { label: "Open", onPress: () => void navigate(`/matches/${id}`) },
        );
      }}
    />
  );
}
