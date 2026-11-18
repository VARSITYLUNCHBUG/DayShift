import { Button } from "@heroui/react";
import { useMemo, useState } from "react";

import type { SimState } from "../../api";
import { SimpleSelect } from "../../components/SimpleSelect";
import { describeError } from "../../hooks/useAction";
import type { EventLog } from "../../hooks/useEventLog";
import { ChannelList, type Target } from "./ChannelList";
import { EventLogPanel } from "./EventLogPanel";
import { Messages } from "./Messages";

/** Screen 3: the simulated guild as the bot sees it, clickable as any fake user. */
export function DiscordScreen({
  simState,
  error,
  eventLog,
  onChanged,
}: {
  simState: SimState | undefined;
  error: Error | null;
  eventLog: EventLog;
  onChanged: () => void;
}) {
  const [target, setTarget] = useState<Target | null>(null);
  const [actorId, setActorId] = useState<string | null>(null);
  const humans = (simState?.members ?? []).filter((m) => !m.isBot);
  const actor = humans.find((m) => m.id === actorId) ?? null;
  const nameOf = useMemo(() => new Map((simState?.members ?? []).map((m) => [m.id, m.name])), [simState?.members]);

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <SimpleSelect
          className="w-80"
          ariaLabel="Act as user"
          placeholder="Act as… (pick a fake user)"
          value={actorId}
          onChange={setActorId}
          options={humans.map((m) => ({ id: m.id, label: `${m.name} · ${m.id}` }))}
        />
        {actor ? (
          <Button size="sm" variant="tertiary" onPress={() => { setTarget({ kind: "dm", id: actor.id, name: actor.name }); }}>
            Open their DMs
          </Button>
        ) : null}
        {error ? <span role="alert" className="text-danger">Simulator: {describeError(error)}</span> : null}
      </div>
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 lg:grid-cols-[220px_minmax(0,1fr)_380px]">
        {simState ? (
          <ChannelList state={simState} target={target} onSelect={setTarget} />
        ) : (
          <div className="rounded-lg bg-surface p-3 text-muted">Waiting for the simulator…</div>
        )}
        {target ? (
          <Messages
            key={`${target.kind}:${target.id}`}
            target={target}
            actorId={actorId}
            nameOf={nameOf}
            onChanged={onChanged}
          />
        ) : (
          <div className="rounded-lg bg-surface p-3 text-muted">Pick a channel or a DM on the left.</div>
        )}
        <EventLogPanel log={eventLog} />
      </div>
    </div>
  );
}
