import { Button, Chip, Spinner } from "@heroui/react";
import { useState } from "react";

import { control, type ControlState, type LobbyMode, type Via } from "../../api";
import { Field } from "../../components/Field";
import { Panel } from "../../components/Panel";
import { SimpleSelect } from "../../components/SimpleSelect";
import { describeError, useAction, type Run } from "../../hooks/useAction";
import { useNow } from "../../hooks/useNow";
import { statusColor, statusLabel } from "../../lib/match";
import { MatchCard } from "./MatchCard";

function QueuePanel({ state, run }: { state: ControlState | undefined; run: Run }) {
  const [count, setCount] = useState("1");
  const queue = state?.queue ?? [];
  const size = state?.lobbySize ?? 12;
  return (
    <Panel
      title={`Queue (${queue.length} / ${size})`}
      actions={
        <Button size="sm" onPress={() => void run("Fill queue", () => control.fillQueue(), `Queue filled to ${size}`)}>
          Fill to {size}
        </Button>
      }
    >
      <div className="flex flex-col gap-3">
        <div className="flex items-end gap-2">
          <Field className="w-24" label="Join idle" type="number" value={count} onChange={setCount} />
          <Button
            size="sm"
            variant="secondary"
            onPress={() => void run("Join queue", () => control.joinQueue({ count: Math.max(1, Number.parseInt(count, 10) || 1) }))}
          >
            Join
          </Button>
        </div>
        <ol className="flex flex-col gap-0.5">
          {queue.map((p, i) => (
            <li key={p.id} className="flex items-center gap-2">
              <span className="mono w-5 text-right text-muted">{i + 1}</span>
              <span className="flex-1 truncate">{p.name}</span>
              {p.rating !== null ? <span className="mono text-muted">{Math.round(p.rating)}</span> : null}
              <Button
                size="sm"
                variant="ghost"
                isIconOnly
                aria-label={`Take ${p.name} out of the queue`}
                onPress={() => void run("Leave queue", () => control.leaveQueue([p.id]))}
              >
                ✕
              </Button>
            </li>
          ))}
          {queue.length === 0 ? <li className="text-muted">The queue is empty.</li> : null}
        </ol>
      </div>
    </Panel>
  );
}

/** Screen 2: the queue and every live match, with autopilot and timer controls. */
export function MatchesScreen({
  state,
  error,
  botConnected,
  onChanged,
}: {
  state: ControlState | undefined;
  error: Error | null;
  botConnected: boolean | null;
  onChanged: () => void;
}) {
  const { run, pending } = useAction(onChanged);
  const now = useNow(1000);
  const [choice, setChoice] = useState<Via | "auto">("auto");
  // Discord clicks only work while the bot has a session with the simulator.
  const via: Via = choice === "auto" ? (botConnected ? "discord" : "service") : choice;
  const matches = state?.matches ?? [];
  const recent = state?.recent ?? [];

  return (
    <div className="flex flex-col gap-4 lg:flex-row lg:items-start">
      <div className="flex w-full flex-col gap-4 lg:w-80 lg:shrink-0">
        <QueuePanel state={state} run={run} />
        {recent.length ? (
          <Panel title="Recent matches">
            <ul className="flex flex-col gap-0.5">
              {recent.map((m) => (
                <li key={m.id} className="flex items-center gap-2">
                  <span className="mono text-muted">#{m.id}</span>
                  <Chip size="sm" variant="soft" color={statusColor(m.status)}>{statusLabel(m.status)}</Chip>
                  {m.winner ? <span className="text-muted">team {m.winner} won</span> : null}
                </li>
              ))}
            </ul>
          </Panel>
        ) : null}
      </div>
      <div className="flex min-w-0 flex-1 flex-col gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="font-semibold">Live matches ({matches.length})</h2>
          <SimpleSelect
            className="w-60"
            ariaLabel="Players act via"
            value={choice}
            onChange={(v) => { setChoice(v as Via | "auto"); }}
            options={[
              { id: "auto", label: `Auto (now: ${via === "discord" ? "Discord clicks" : "services"})` },
              { id: "discord", label: "Act via Discord clicks" },
              { id: "service", label: "Act via league services" },
            ]}
          />
          {state?.lobbies ? (
            <SimpleSelect
              className="w-64"
              ariaLabel="deadlock-api lobbies"
              value={state.lobbies}
              onChange={(mode) => void run("deadlock-api lobbies", () => control.setLobbies(mode as LobbyMode), `deadlock-api: ${mode === "create" ? "makes lobbies" : "refuses lobbies"}`)}
              options={[
                { id: "create", label: "deadlock-api makes lobbies" },
                { id: "fail", label: "deadlock-api refuses (code by hand)" },
              ]}
            />
          ) : null}
          {pending ? (
            <span className="flex items-center gap-2 text-muted" role="status">
              <Spinner size="sm" /> {pending}…
            </span>
          ) : null}
        </div>
        {error ? <p role="alert" className="text-danger">State: {describeError(error)}</p> : null}
        <div className="flex flex-wrap gap-4">
          {matches.map((m) => (
            <MatchCard key={m.id} match={m} now={now} run={run} via={via} />
          ))}
        </div>
        {state && matches.length === 0 ? (
          <p className="text-muted">No live matches. Fill the queue to pop one.</p>
        ) : null}
      </div>
    </div>
  );
}
