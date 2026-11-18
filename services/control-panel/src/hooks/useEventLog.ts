import { useCallback, useEffect, useState } from "react";

import { sim, subscribeEvents, type SimEvent, type StreamStatus } from "../api";

const MAX_EVENTS = 1000;

export interface EventLog {
  events: SimEvent[];
  status: StreamStatus;
  clear: () => void;
}

/** The simulator's live event stream, kept app-wide so switching tabs loses nothing. */
export function useEventLog(): EventLog {
  const [events, setEvents] = useState<SimEvent[]>([]);
  const [status, setStatus] = useState<StreamStatus>("connecting");

  useEffect(
    () =>
      subscribeEvents(
        sim.eventsUrl(),
        (event) => {
          setEvents((list) => {
            const next = list.length >= MAX_EVENTS ? list.slice(list.length - MAX_EVENTS + 1) : list.slice();
            next.push(event);
            return next;
          });
        },
        setStatus,
      ),
    [],
  );

  const clear = useCallback(() => {
    setEvents([]);
  }, []);

  return { events, status, clear };
}
