import { Button, Chip, Kbd, Spinner } from "@heroui/react";
import { useEffect, useMemo, useRef, useState } from "react";

import { control, type Scenario, type ScenarioStep } from "../api";
import { AreaField, Field } from "../components/Field";
import { JsonBlock } from "../components/JsonBlock";
import { Panel } from "../components/Panel";
import { Toggle } from "../components/Toggle";
import { describeError } from "../hooks/useAction";
import { useHotkeys } from "../hooks/useHotkeys";
import { usePoll } from "../hooks/usePoll";
import {
  describeExpectation,
  describeOutcome,
  expectationOf,
  meets,
  outcomeOf,
  stepBody,
  stepCall,
  stepTitle,
  type Outcome,
} from "../lib/scenario";

type StepStatus = "pending" | "running" | "ok" | "mismatch" | "error";

interface StepRun {
  status: StepStatus;
  outcome?: Outcome;
  seconds?: number | null;
  result?: unknown;
}

/** idle: nothing running; running: going through steps; paused: stopped mid-run, resumable. */
type Mode = "idle" | "running" | "paused";

const loadScenarios = () => control.scenarios();
const CUSTOM = "__custom__";

function parseSteps(text: string): ScenarioStep[] | string {
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch (err) {
    return `Steps are not JSON: ${describeError(err)}`;
  }
  if (!Array.isArray(value) || !value.every((s) => s !== null && typeof s === "object" && !Array.isArray(s))) {
    return "Steps must be a JSON list of objects";
  }
  return value as ScenarioStep[];
}

const STATUS_COLOR: Record<StepStatus, "default" | "accent" | "success" | "warning" | "danger"> = {
  pending: "default",
  running: "accent",
  ok: "success",
  mismatch: "warning",
  error: "danger",
};

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Screen 4: run named scenarios as runbooks. Step through them one call at a time, or run them
 * with a pause you can take at any point (and breakpoints), and see what each step expected
 * against what it did.
 */
export function ScenariosScreen({ onChanged }: { onChanged: () => void }) {
  const scenarios = usePoll(loadScenarios, 30000);
  const [selected, setSelected] = useState<string | null>(null);
  const [text, setText] = useState("[]");
  const [runs, setRuns] = useState<StepRun[]>([]);
  const [mode, setMode] = useState<Mode>("idle");
  const [breakpoints, setBreakpoints] = useState<Set<number>>(new Set());
  const [stopOnMismatch, setStopOnMismatch] = useState(true);
  const [delay, setDelay] = useState("0");
  const [message, setMessage] = useState<string | null>(null);
  // Read by the run loop between steps, so a press of Pause lands before the next call.
  const pauseRequested = useRef(false);
  const pausing = () => pauseRequested.current;
  // Also read between steps, so a breakpoint or the stop toggle changed mid-run counts at once.
  const breakpointsNow = useRef(breakpoints);
  const stopOnMismatchNow = useRef(stopOnMismatch);
  useEffect(() => {
    breakpointsNow.current = breakpoints;
    stopOnMismatchNow.current = stopOnMismatch;
  }, [breakpoints, stopOnMismatch]);

  const parsed = useMemo(() => parseSteps(text), [text]);
  const steps = typeof parsed === "string" ? [] : parsed;
  const firstUndone = runs.findIndex((r) => r.status !== "ok" && r.status !== "mismatch");
  const cursor = firstUndone === -1 ? runs.length : firstUndone;
  const done = cursor >= steps.length;
  const current: Scenario | undefined = scenarios.data?.find((s) => s.name === selected);
  const busy = mode === "running";

  const choose = (name: string, scenario?: Scenario) => {
    if (busy) return;
    setSelected(name);
    setText(JSON.stringify(scenario?.steps ?? [], null, 2));
    setRuns([]);
    setBreakpoints(new Set());
    setMode("idle");
    setMessage(null);
  };

  const edit = (value: string) => {
    // The run loop holds the steps it started with.
    if (busy) return;
    setText(value);
    setRuns([]);
    setMode("idle");
  };

  const mark = (index: number, run: StepRun) => {
    setRuns((prev) => steps.map((_, i) => (i === index ? run : (prev[i] ?? { status: "pending" }))));
  };

  /** Run one step on the server. Resolves to whether the run may go on. */
  const runStep = async (index: number): Promise<boolean> => {
    const step = steps[index];
    if (!step) return false;
    mark(index, { status: "running" });
    const expected = expectationOf(step);
    let goOn: boolean;
    try {
      const result = await control.runSteps(steps, index, 1);
      const ran = result.ran.find((r) => r.index === index);
      if (!ran) {
        // The server ran nothing for this step: that's a failure, not an HTTP 0 that "passes".
        mark(index, { status: "error", result });
        setMessage(`Step ${index + 1}: the server's answer has no result for it.`);
        onChanged();
        return false;
      }
      const outcome = outcomeOf(ran.status, ran.response);
      const ok = meets(expected, outcome);
      const failed = outcome.http >= 400 && !ok;
      mark(index, { status: ok ? "ok" : failed ? "error" : "mismatch", outcome, seconds: ran.seconds, result: ran.response });
      goOn = ok || (!failed && !stopOnMismatchNow.current);
      if (!goOn) setMessage(`Step ${index + 1}: expected ${describeExpectation(expected)}, got ${describeOutcome(outcome)}.`);
    } catch (err) {
      mark(index, { status: "error", result: { error: describeError(err) } });
      setMessage(`Step ${index + 1}: ${describeError(err)}`);
      goOn = false;
    }
    onChanged();
    return goOn;
  };

  const step = async () => {
    if (busy || done) return;
    setMessage(null);
    setMode("running");
    await runStep(cursor);
    setMode(cursor + 1 >= steps.length ? "idle" : "paused");
  };

  /** Run from the cursor until the end, a pause, a breakpoint or a step that goes wrong. */
  const run = async () => {
    if (busy || done) return;
    pauseRequested.current = false;
    setMessage(null);
    setMode("running");
    const wait = Math.max(0, Number.parseFloat(delay) || 0) * 1000;
    for (let i = cursor; i < steps.length; i++) {
      if (i !== cursor && (pausing() || breakpointsNow.current.has(i))) {
        setMessage(pausing() ? `Paused before step ${i + 1}.` : `Breakpoint: paused before step ${i + 1}.`);
        setMode("paused");
        return;
      }
      if (!(await runStep(i))) {
        setMode("paused");
        return;
      }
      if (wait && i + 1 < steps.length) await sleep(wait);
    }
    setMessage("Every step ran.");
    setMode("idle");
  };

  const pause = () => {
    pauseRequested.current = true;
  };

  const rewind = () => {
    if (busy) return;
    setRuns([]);
    setMode("idle");
    setMessage(null);
  };

  const toggleBreakpoint = (index: number) => {
    setBreakpoints((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  };

  useHotkeys({
    n: () => void step(),
    p: () => { if (busy) pause(); else void run(); },
    r: rewind,
  });

  const counts = runs.reduce<Record<StepStatus, number>>(
    (acc, r) => ({ ...acc, [r.status]: acc[r.status] + 1 }),
    { pending: 0, running: 0, ok: 0, mismatch: 0, error: 0 },
  );

  return (
    <div className="flex flex-col gap-4 lg:flex-row lg:items-start">
      <Panel className="w-full lg:w-72 lg:shrink-0" title="Scenarios">
        {scenarios.error ? <p role="alert" className="text-danger">{describeError(scenarios.error)}</p> : null}
        <ul className="flex flex-col gap-0.5" aria-label="Scenarios">
          {[...(scenarios.data ?? []).map((s) => ({ id: s.name, scenario: s })), { id: CUSTOM, scenario: undefined as Scenario | undefined }].map(
            ({ id, scenario }) => (
              <li key={id}>
                <button
                  type="button"
                  aria-current={selected === id ? "true" : undefined}
                  disabled={busy}
                  className={`w-full rounded-sm px-2 py-1 text-left outline-none focus-visible:ring-2 focus-visible:ring-focus disabled:opacity-60 ${
                    selected === id ? "bg-accent-soft text-accent-soft-foreground" : "hover:bg-surface-hover"
                  }`}
                  onClick={() => { choose(id, scenario); }}
                >
                  {scenario ? (
                    <>
                      <div className="mono">{scenario.name}</div>
                      {scenario.description ? <div className="text-xs text-muted">{scenario.description}</div> : null}
                      <div className="text-xs text-muted">{scenario.steps.length} steps</div>
                    </>
                  ) : (
                    <>
                      <div>Custom steps…</div>
                      <div className="text-xs text-muted">write your own list</div>
                    </>
                  )}
                </button>
              </li>
            ),
          )}
        </ul>
        {!scenarios.data && !scenarios.error ? <Spinner size="sm" /> : null}
      </Panel>

      {selected === null ? (
        <p className="text-muted">Pick a scenario to see its steps.</p>
      ) : (
        <div className="flex min-w-0 flex-1 flex-col gap-4">
          <Panel
            title={selected === CUSTOM ? "Custom steps" : (current?.name ?? selected)}
            actions={
              <>
                <span className="text-muted" aria-live="polite">
                  {mode === "running" ? "running" : mode === "paused" ? "paused" : "ready"} · step {Math.min(cursor + 1, steps.length)} / {steps.length}
                </span>
                <Button size="sm" isDisabled={busy || done} onPress={() => void step()}>
                  Next step
                  <Kbd><Kbd.Content>N</Kbd.Content></Kbd>
                </Button>
                {busy ? (
                  <Button size="sm" variant="secondary" onPress={pause}>
                    Pause
                    <Kbd><Kbd.Content>P</Kbd.Content></Kbd>
                  </Button>
                ) : (
                  <Button size="sm" variant="secondary" isDisabled={done} onPress={() => void run()}>
                    {mode === "paused" ? "Resume" : "Run"}
                    <Kbd><Kbd.Content>P</Kbd.Content></Kbd>
                  </Button>
                )}
                <Button size="sm" variant="tertiary" isDisabled={busy} onPress={rewind}>
                  Rewind
                  <Kbd><Kbd.Content>R</Kbd.Content></Kbd>
                </Button>
              </>
            }
          >
            {current?.description ? <p className="mb-2 text-muted">{current.description}</p> : null}
            <div className="mb-3 flex flex-wrap items-end gap-4">
              <Toggle label="Stop when a step doesn't do what it expects" isSelected={stopOnMismatch} onChange={setStopOnMismatch} />
              <Field className="w-44" label="Seconds between steps" type="number" value={delay} onChange={setDelay} />
              <span className="text-xs text-muted">
                {counts.ok} as expected · {counts.mismatch} different · {counts.error} failed
              </span>
            </div>
            {message ? <p role="status" className="mb-2">{message}</p> : null}
            <ol className="flex flex-col gap-1" aria-label="Steps">
              {steps.map((s, i) => {
                const stepRun = runs[i];
                const status = stepRun?.status ?? "pending";
                const expected = expectationOf(s);
                const isBreak = breakpoints.has(i);
                return (
                  <li
                    key={i}
                    aria-current={i === cursor ? "step" : undefined}
                    className={`rounded-md border p-2 ${i === cursor && !done ? "border-accent" : "border-separator"}`}
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <button
                        type="button"
                        aria-pressed={isBreak}
                        aria-label={`${isBreak ? "Remove the breakpoint at" : "Pause before"} step ${i + 1}`}
                        title="Breakpoint: a run pauses before this step"
                        className={`mono w-7 rounded-sm text-right outline-none focus-visible:ring-2 focus-visible:ring-focus ${
                          isBreak ? "bg-danger text-danger-foreground" : "text-muted hover:bg-surface-hover"
                        }`}
                        onClick={() => { toggleBreakpoint(i); }}
                      >
                        {i + 1}
                      </button>
                      <span className="font-semibold">{stepTitle(s) ?? stepCall(s)}</span>
                      <span className="mono min-w-0 flex-1 truncate text-muted">
                        {stepTitle(s) ? `${stepCall(s)} ` : ""}
                        {stepBody(s)}
                      </span>
                      <Chip size="sm" variant="soft" color={STATUS_COLOR[status]}>
                        {status === "mismatch" ? "different" : status}
                      </Chip>
                    </div>
                    <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 pl-9 text-xs">
                      <dt className="text-muted">expected</dt>
                      <dd>{describeExpectation(expected)}</dd>
                      {stepRun?.outcome ? (
                        <>
                          <dt className="text-muted">actual</dt>
                          <dd className={status === "ok" ? "text-success" : status === "mismatch" ? "text-warning" : "text-danger"}>
                            {describeOutcome(stepRun.outcome)}
                            {stepRun.seconds != null ? <span className="text-muted"> in {stepRun.seconds.toFixed(1)} s</span> : null}
                          </dd>
                        </>
                      ) : null}
                    </dl>
                    {stepRun?.result !== undefined ? (
                      // Open by default only when the step went wrong: that answer says why.
                      <details className="mt-1 pl-9" open={status === "error" || status === "mismatch"}>
                        <summary className="cursor-pointer text-xs text-muted outline-none focus-visible:ring-2 focus-visible:ring-focus">
                          response
                        </summary>
                        <JsonBlock value={stepRun.result} className="mt-1" />
                      </details>
                    ) : null}
                  </li>
                );
              })}
              {steps.length === 0 ? <li className="text-muted">No steps.</li> : null}
            </ol>
          </Panel>
          <Panel title="Steps (JSON, editable)">
            <p className="mb-2 text-xs text-muted">
              Each step is <span className="mono">{"{title?, method, path, body?, expect?}"}</span>; <span className="mono">expect</span> is{" "}
              <span className="mono">{'{"status": "player_draft", "http": 409}'}</span>, both optional.
            </p>
            <AreaField label="Steps" value={text} onChange={edit} rows={12} />
            {typeof parsed === "string" ? <p role="alert" className="mt-2 text-danger">{parsed}</p> : null}
          </Panel>
        </div>
      )}
    </div>
  );
}
