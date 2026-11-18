import { Button, Chip, Label, Modal, Radio, RadioGroup } from "@heroui/react";
import { useMemo, useState } from "react";

import { ACTIONS, control, type Action, type Match, type PlayerRef, type Via } from "../../api";
import { AreaField } from "../../components/Field";
import { JsonBlock } from "../../components/JsonBlock";
import { SimpleSelect } from "../../components/SimpleSelect";
import { Toggle } from "../../components/Toggle";
import { describeError, type Run } from "../../hooks/useAction";
import { actionLabel, argsFor, validActions, type ActionChoice } from "../../lib/actions";

// Always made through the services: nobody has a button for it (SERVICE_ONLY in devtools/autopilot.py).
const SERVICE_ONLY = new Set<Action>(["void"]);
const SELECTORS = ["acting", "captain:A", "captain:B", "host", "other_captain", "offered", "requester"];

const pretty = (value: unknown) => JSON.stringify(value, null, 2);
const refKey = (ref: PlayerRef) => String(ref);

/**
 * One action as one player. It offers only what the match's phase allows, and who can do it,
 * with the arguments filled in; "Every action" lifts that for testing the league's refusals.
 */
export function ActModal({ match, run, via, onClose }: { match: Match; run: Run; via: Via; onClose: () => void }) {
  const valid = useMemo(() => validActions(match), [match]);
  const [everything, setEverything] = useState(valid.length === 0);
  const everyPlayer = useMemo(() => [...match.players.map((p) => p.id), ...SELECTORS], [match.players]);
  const choices: ActionChoice[] = everything
    ? ACTIONS.map((action) => ({ action, label: actionLabel(action), actors: everyPlayer, onTurn: false }))
    : valid;

  const first = choices[0];
  const [action, setAction] = useState<Action | null>(first?.action ?? null);
  const choice = choices.find((c) => c.action === action) ?? null;
  // The match moved on while this was open (the poll brought a new phase), and the chosen action
  // is no longer one it allows: say so, and don't send it.
  const stale = action !== null && choice === null;
  const [actor, setActor] = useState<string | null>(first?.actors[0] !== undefined ? refKey(first.actors[0]) : null);
  const [args, setArgs] = useState(() => (first ? pretty(argsFor(first.action, match, first.actors[0] ?? null)) : "{}"));
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<unknown>(undefined);

  const nameOf = (ref: PlayerRef) => {
    const p = match.players.find((x) => x.id === ref);
    if (!p) return String(ref);
    return `${p.name}${p.team ? ` (${p.team}${p.isCaptain ? ", captain" : ""})` : ""}`;
  };
  const toRef = (key: string | null): PlayerRef | null => (key === null ? null : /^\d+$/.test(key) ? Number(key) : key);

  // Once the chosen player has acted (one captain checked in, say), move on to whoever is next.
  const nextActor = choice?.actors[0];
  if (nextActor !== undefined && !choice?.actors.some((ref) => refKey(ref) === actor)) {
    setActor(refKey(nextActor));
    if (action) setArgs(pretty(argsFor(action, match, nextActor)));
  }

  const choose = (next: Action, list: ActionChoice[] = choices) => {
    const picked = list.find((c) => c.action === next);
    const who = picked?.actors[0] ?? null;
    setAction(next);
    setActor(who === null ? null : refKey(who));
    setArgs(pretty(argsFor(next, match, who)));
    setResult(undefined);
  };

  const chooseActor = (key: string) => {
    setActor(key);
    if (action) setArgs(pretty(argsFor(action, match, toRef(key))));
  };

  const toggleEverything = (on: boolean) => {
    setEverything(on);
    const list = on ? ACTIONS.map((a) => ({ action: a, label: actionLabel(a), actors: everyPlayer, onTurn: false })) : valid;
    const keep = list.find((c) => c.action === action) ?? list[0];
    if (keep) choose(keep.action, list);
  };

  const submit = async () => {
    if (!action || stale) return;
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(args || "{}") as Record<string, unknown>;
    } catch (err) {
      setError(`Args aren't JSON: ${describeError(err)}`);
      return;
    }
    setError(null);
    const player = toRef(actor);
    const out = await run(`Act: ${action}`, () =>
      control.act(match.id, { action, args: parsed, via, ...(player === null ? {} : { player_id: player }) }),
    );
    if (out !== undefined) setResult(out);
  };

  return (
    <Modal.Backdrop isOpen onOpenChange={(open) => { if (!open) onClose(); }}>
      <Modal.Container size="lg" scroll="inside">
        <Modal.Dialog>
          <Modal.CloseTrigger />
          <Modal.Header>
            <Modal.Heading>Act as a player in match #{match.id}</Modal.Heading>
          </Modal.Header>
          <Modal.Body className="flex flex-col gap-4">
            <div className="flex flex-wrap items-start gap-6">
              <RadioGroup
                className="min-w-64 flex-1"
                value={action}
                onChange={(value) => { choose(value as Action); }}
                variant="secondary"
              >
                <Label>{everything ? "Every action" : "What this phase allows"}</Label>
                {choices.map((c) => (
                  <Radio key={c.action} value={c.action}>
                    <Radio.Content>
                      <Radio.Control>
                        <Radio.Indicator />
                      </Radio.Control>
                      <span className="flex items-center gap-2">
                        {c.label}
                        <span className="mono text-xs text-muted">{c.action}</span>
                        {c.onTurn ? <Chip size="sm" color="accent" variant="soft">waiting for this</Chip> : null}
                      </span>
                    </Radio.Content>
                  </Radio>
                ))}
                {choices.length === 0 ? <p className="text-muted">The match is over: nothing to do.</p> : null}
              </RadioGroup>
              <div className="flex min-w-56 flex-1 flex-col gap-3">
                {choice && choice.actors.length > 0 ? (
                  <SimpleSelect
                    label="As"
                    value={actor}
                    onChange={chooseActor}
                    options={choice.actors.map((ref) => ({ id: refKey(ref), label: nameOf(ref) }))}
                  />
                ) : choice ? (
                  <p className="text-muted">Made by nobody in the match: staff, or deadlock-api.</p>
                ) : null}
                <Toggle label="Every action and player" isSelected={everything} onChange={toggleEverything} />
                <p className="text-xs text-muted">
                  Sent via {action && SERVICE_ONLY.has(action) ? "service (no button for this)" : via}.
                </p>
              </div>
            </div>
            <AreaField label="Args (JSON)" value={args} onChange={setArgs} rows={4} />
            {stale ? (
              <p role="alert" className="text-warning">
                Match #{match.id} is now {match.status}: <span className="mono">{action}</span> isn&apos;t something it allows any
                more. Pick an action again.
              </p>
            ) : null}
            {error ? <p role="alert" className="text-danger">{error}</p> : null}
            {result !== undefined ? <JsonBlock value={result} /> : null}
          </Modal.Body>
          <Modal.Footer>
            <Button slot="close" variant="tertiary">Close</Button>
            <Button isDisabled={!action || stale} onPress={() => void submit()}>Send action</Button>
          </Modal.Footer>
        </Modal.Dialog>
      </Modal.Container>
    </Modal.Backdrop>
  );
}
