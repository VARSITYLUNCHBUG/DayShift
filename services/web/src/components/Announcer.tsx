import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";

type Announce = (message: string) => void;

const AnnounceContext = createContext<Announce>(() => {});

/** The page's one polite live region (#announce, F07): turn changes, "10 seconds left to pick",
 * "8 of 12 ready". Timers and toasts don't talk on their own; they come through here. */
export function AnnouncerProvider({ children }: { children: ReactNode }) {
  const [message, setMessage] = useState("");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const announce = useCallback<Announce>((next) => {
    // Clear first so the same words twice in a row are read twice.
    setMessage("");
    if (timer.current !== null) clearTimeout(timer.current);
    timer.current = setTimeout(() => setMessage(next), 50);
  }, []);

  useEffect(
    () => () => {
      if (timer.current !== null) clearTimeout(timer.current);
    },
    [],
  );

  const value = useMemo(() => announce, [announce]);
  return (
    <AnnounceContext value={value}>
      {children}
      <div id="announce" aria-live="polite" aria-atomic="true" className="sr-only">
        {message}
      </div>
    </AnnounceContext>
  );
}

/** Say something politely through the shared live region. */
export function useAnnounce(): Announce {
  return useContext(AnnounceContext);
}
