import { Skeleton } from "@heroui/react";

import { AppShell } from "../../components/AppShell";
import { useTopic } from "../../../live/hooks";
import type { LiveSnap, MeSnap, QueueSnap } from "../../../live/types";
import { CooldownCard } from "./CooldownCard";
import { LiveMatches } from "./LiveMatches";
import { QueueCard } from "./QueueCard";
import { YourMatchCard } from "./YourMatchCard";

/** The home page: a scrim you captain, your live match or else the queue (or the cooldown keeping
 * you out of it), and the live matches. */
export function PlayPage() {
  const { data: me } = useTopic("me");
  const { data: queue } = useTopic("queue");
  const { data: live } = useTopic("live");
  return (
    <AppShell>
      <PlayView me={me} queue={queue} live={live} />
    </AppShell>
  );
}

interface ViewProps {
  me: MeSnap | undefined;
  queue: QueueSnap | undefined;
  live: LiveSnap | undefined;
}

export function PlayView({ me, queue, live }: ViewProps) {
  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6">
      {me?.scrim ? <YourMatchCard match={me.scrim} /> : null}
      {!me || !queue ? (
        <Skeleton className="h-72 w-full rounded-3xl" />
      ) : me.match ? (
        <YourMatchCard match={me.match} />
      ) : me.cooldown ? (
        <CooldownCard cooldown={me.cooldown} />
      ) : (
        <QueueCard me={me} queue={queue} />
      )}
      {live ? (
        <LiveMatches live={live} mine={me?.match?.id ?? null} />
      ) : (
        <Skeleton className="h-28 w-full rounded-2xl" />
      )}
    </div>
  );
}
