// React's view of the live connection. Screens use these, never the socket directly.
import { useCallback, useContext, useEffect, useRef, useState, useSyncExternalStore } from "react";

import type { ActionArgs, ActionName } from "./actions";
import { LiveContext } from "./context";
import type { ConnectionState, LiveSocket, TopicSnapshot } from "./LiveSocket";
import type { AckMessage, Topic, TopicData } from "./types";

export function useLive(): LiveSocket {
  const live = useContext(LiveContext);
  if (!live) throw new Error("useLive needs a LiveProvider above it.");
  return live;
}

export function useConnectionState(): ConnectionState {
  const live = useLive();
  return useSyncExternalStore(live.subscribeState, live.getState);
}

/** The signed-in player's id, as the socket's `hello` said. */
export function usePlayerId(): string | null {
  const live = useLive();
  return useSyncExternalStore(live.subscribeState, live.getPlayerId);
}

/** - `idle`: no topic asked for. `loading`: waiting for the first snapshot.
 *  - `live`: up to date. `stale`: the last snapshot, while the connection is down.
 *  - `gone`: the server says there's no such thing (or it isn't visible to you). */
export type TopicState = "idle" | "loading" | "live" | "stale" | "gone";

export interface TopicResult<T extends Topic> {
  data: TopicData<T> | undefined;
  state: TopicState;
}

const NOTHING: TopicSnapshot = Object.freeze({ data: undefined, gone: false });
const noop = () => () => {};

/** The latest snapshot of a topic, kept up to date. Pass null to watch nothing. */
export function useTopic<T extends Topic>(topic: T | null): TopicResult<T> {
  const live = useLive();
  const subscribe = useCallback(
    (listener: () => void) => (topic === null ? noop() : live.subscribe(topic, listener)),
    [live, topic],
  );
  const snapshot = useSyncExternalStore(subscribe, () =>
    topic === null ? NOTHING : live.getTopic(topic),
  );
  const connection = useConnectionState();
  const data = snapshot.data as TopicData<T> | undefined;
  let state: TopicState;
  if (topic === null) state = "idle";
  else if (snapshot.gone) state = "gone";
  else if (data === undefined) state = "loading";
  else state = connection === "open" ? "live" : "stale";
  return { data, state };
}

export interface ActionHandle {
  /** Sends the action; settles with its ack. Rejects with ActionRefused or ConnectionLost. */
  run: <N extends ActionName>(name: N, args: ActionArgs[N]) => Promise<AckMessage>;
  pending: boolean;
  error: string | null;
}

/** Runs actions over the socket and tracks the one in flight. */
export function useAction(): ActionHandle {
  const live = useLive();
  const [inFlight, setInFlight] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const run = useCallback(
    <N extends ActionName>(name: N, args: ActionArgs[N]): Promise<AckMessage> => {
      setError(null);
      setInFlight((n) => n + 1);
      return live.act(name, args).then(
        (ack) => {
          if (mounted.current) setInFlight((n) => n - 1);
          return ack;
        },
        (reason: unknown) => {
          if (mounted.current) {
            setInFlight((n) => n - 1);
            setError(reason instanceof Error ? reason.message : String(reason));
          }
          throw reason;
        },
      );
    },
    [live],
  );

  return { run, pending: inFlight > 0, error };
}

/** Server time in ms, refreshed every `everyMs`. Works without a LiveProvider (local clock). */
export function useServerNow(everyMs = 1000): number {
  const live = useContext(LiveContext);
  const read = useCallback(() => (live ? live.serverNow() : Date.now()), [live]);
  const [now, setNow] = useState(read);
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    const tick = () => {
      const current = read();
      setNow(current);
      // Line ticks up with whole seconds of server time, so every countdown changes together.
      timer = setTimeout(tick, everyMs - (current % everyMs) + 5);
    };
    tick();
    // `hello` corrects the clock: show the corrected time straight away, not at the next tick.
    const unsubscribe = live?.subscribeState(() => setNow(read()));
    return () => {
      clearTimeout(timer);
      unsubscribe?.();
    };
  }, [live, read, everyMs]);
  return now;
}

export interface Countdown {
  /** Milliseconds left, never below zero. */
  remainingMs: number;
  /** Whole seconds left, rounded up, so "0:00" shows only once the time is really up. */
  seconds: number;
  /** "2:41", or "1:02:03" past an hour. */
  label: string;
  /** Past zero: the server hasn't moved on yet. */
  waiting: boolean;
  /** The most time left seen for this deadline, for progress bars that start full. */
  totalMs: number;
}

/** Counts down to an ISO deadline using the server's clock. Null deadline counts nothing. */
export function useCountdown(deadline: string | null | undefined): Countdown | null {
  const now = useServerNow();
  const end = deadline ? Date.parse(deadline) : Number.NaN;
  const remainingMs = Number.isNaN(end) ? 0 : Math.max(0, end - now);
  const [longest, setLongest] = useState<{ deadline: string; ms: number } | null>(null);
  const seen = longest !== null && longest.deadline === deadline ? longest.ms : null;
  if (deadline && (seen === null || remainingMs > seen)) {
    // Adjusting state while rendering, keyed by the deadline (React's documented pattern).
    setLongest({ deadline, ms: remainingMs });
  }
  if (!deadline || Number.isNaN(end)) return null;
  const seconds = Math.ceil(remainingMs / 1000);
  const totalMs = Math.max(seen ?? 0, remainingMs);
  return { remainingMs, seconds, label: clock(seconds), waiting: remainingMs <= 0, totalMs };
}

/** Time since an ISO moment by the server's clock, as "24:10". */
export function useElapsed(since: string | null | undefined): string | null {
  const now = useServerNow();
  const start = since ? Date.parse(since) : Number.NaN;
  if (Number.isNaN(start)) return null;
  return clock(Math.max(0, Math.floor((now - start) / 1000)));
}

export function clock(totalSeconds: number): string {
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  const ss = String(seconds).padStart(2, "0");
  if (hours > 0) return `${hours}:${String(minutes).padStart(2, "0")}:${ss}`;
  return `${minutes}:${ss}`;
}
