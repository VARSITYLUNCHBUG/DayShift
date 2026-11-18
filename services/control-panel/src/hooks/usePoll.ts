import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

export interface Poll<T> {
  data: T | undefined;
  error: Error | null;
  refresh: () => void;
}

/**
 * Call `load` now and every `intervalMs` while the tab is visible. To poll something else,
 * remount the component (give it a `key`).
 */
export function usePoll<T>(load: (signal: AbortSignal) => Promise<T>, intervalMs: number): Poll<T> {
  const [data, setData] = useState<T | undefined>(undefined);
  const [error, setError] = useState<Error | null>(null);
  const [tick, setTick] = useState(0);
  const loadRef = useRef(load);

  useLayoutEffect(() => {
    loadRef.current = load;
  });

  useEffect(() => {
    // One controller for the whole loop: aborting it cancels the request in flight too.
    const stop = new AbortController();
    const stopped = () => stop.signal.aborted;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const run = async () => {
      if (document.visibilityState !== "hidden") {
        try {
          const value = await loadRef.current(stop.signal);
          if (stopped()) return;
          setData(value);
          setError(null);
        } catch (err) {
          if (stopped()) return;
          setError(err instanceof Error ? err : new Error(String(err)));
        }
      }
      if (!stopped()) timer = setTimeout(() => void run(), intervalMs);
    };

    void run();
    return () => {
      stop.abort();
      if (timer) clearTimeout(timer);
    };
  }, [intervalMs, tick]);

  const refresh = useCallback(() => {
    setTick((t) => t + 1);
  }, []);

  return { data, error, refresh };
}
