import { Button, Card, Chip, ProgressBar, Spinner } from "@heroui/react";

import { notify } from "../../components/toast";
import { useAction, useCountdown, useElapsed } from "../../../live/hooks";
import type { MeSnap, QueueSnap } from "../../../live/types";

interface Props {
  me: MeSnap;
  queue: QueueSnap;
}

/** 1.4 and 1.5: the queue, who's in it, and Join / Leave. */
export function QueueCard({ me, queue }: Props) {
  const action = useAction();
  const inQueue = me.queue.in_queue;
  const more = Math.max(0, queue.size - queue.count);
  const join = () => {
    action.run(inQueue ? "queue.leave" : "queue.join", {}).catch(notify.error);
  };
  return (
    <Card
      aria-labelledby="queue-count"
      className={`gap-5.5 rounded-3xl border p-5 sm:p-7 ${inQueue ? "border-accent" : "border-border"}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex flex-col gap-1.5">
          <span className="text-sm text-muted">{more > 0 ? `Queue · ${more} more to start` : "Queue"}</span>
          <h1 id="queue-count" className="text-5xl font-bold tracking-tight tabular-nums">
            {queue.count} <span className="text-muted">/ {queue.size}</span>
          </h1>
        </div>
        <PlaceChip me={me} queue={queue} />
      </div>
      <ProgressBar aria-label="Queue" value={queue.count} maxValue={queue.size} size="lg">
        <ProgressBar.Track>
          <ProgressBar.Fill />
        </ProgressBar.Track>
      </ProgressBar>
      {queue.players.length > 0 ? (
        <ol aria-label="In queue" className="grid grid-cols-2 gap-1.5 text-sm sm:grid-cols-3 lg:grid-cols-6">
          {queue.players.map((player, index) => {
            const isMe = player.id === me.player.id;
            return (
              <li
                key={player.id}
                aria-current={isMe ? "true" : undefined}
                className={`flex min-w-0 gap-2.5 rounded-xl px-3 py-2.5 ${isMe ? "bg-accent-soft font-semibold" : "bg-surface-secondary"}`}
              >
                <span className={`w-5 shrink-0 tabular-nums ${isMe ? "text-accent-soft-foreground" : "text-muted"}`}>
                  {index + 1}
                </span>
                <span className="truncate">{player.name}</span>
              </li>
            );
          })}
        </ol>
      ) : null}
      <Button
        size="lg"
        fullWidth
        variant={inQueue ? "danger-soft" : "primary"}
        onPress={join}
        isPending={action.pending}
        className={`h-15 text-lg font-bold ${inQueue ? "border border-danger/30" : ""}`}
      >
        {({ isPending }) => (
          <>
            {isPending ? <Spinner color="current" size="sm" /> : null}
            {inQueue ? "Leave queue" : "Join queue"}
          </>
        )}
      </Button>
    </Card>
  );
}

/** "#7 of 9 · 4:03" while queued (the time waited); "Place held · 2:41" while holding a place. */
function PlaceChip({ me, queue }: Props) {
  const waited = useElapsed(me.queue.in_queue ? me.queue.joined_at : null);
  const held = useCountdown(me.queue.in_queue ? null : (me.queue.place?.held_until ?? null));
  if (me.queue.in_queue && me.queue.position !== null) {
    const text = `#${me.queue.position} of ${queue.count}${waited ? ` · ${waited}` : ""}`;
    return (
      <Chip size="lg" color="accent" variant="soft" className="font-semibold tabular-nums">
        {text}
      </Chip>
    );
  }
  if (held && !held.waiting) {
    return (
      <Chip size="lg" color="warning" variant="soft" className="font-semibold tabular-nums">
        {`Place held · ${held.label}`}
      </Chip>
    );
  }
  return null;
}
