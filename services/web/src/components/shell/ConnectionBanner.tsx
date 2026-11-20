import { useContext, useEffect, useState, useSyncExternalStore } from "react";

import { LiveContext } from "../../live/context";
import type { ConnectionState, LiveSocket } from "../../live/LiveSocket";
import { Banner } from "../Banner";
import { Button } from "../Button";

/** Shown after this long without the live connection (P03, proposed). */
export const RECONNECTING_AFTER_MS = 3_000;
/** Then it says you're offline and offers Reload. */
export const OFFLINE_AFTER_MS = 20_000;

const noopSubscribe = () => () => {};
const always = (): ConnectionState => "open";

function useOptionalConnection(live: LiveSocket | null): ConnectionState {
  return useSyncExternalStore(live ? live.subscribeState : noopSubscribe, live ? live.getState : always);
}

/** How long the live connection has been down, in steps: fine, reconnecting, offline. */
export function useConnectionTrouble(): "ok" | "reconnecting" | "offline" {
  const live = useContext(LiveContext);
  const state = useOptionalConnection(live);
  const down = state === "reconnecting" || state === "connecting";
  const [level, setLevel] = useState<"ok" | "reconnecting" | "offline">("ok");

  useEffect(() => {
    if (!down) return;
    const soon = setTimeout(() => setLevel("reconnecting"), RECONNECTING_AFTER_MS);
    const later = setTimeout(() => setLevel("offline"), OFFLINE_AFTER_MS);
    return () => {
      clearTimeout(soon);
      clearTimeout(later);
      // Back online: the next drop starts from the beginning again.
      setLevel("ok");
    };
  }, [down]);

  return down ? level : "ok";
}

/** The reconnecting and offline banner, under the top bar or room header. */
export function ConnectionBanner() {
  const trouble = useConnectionTrouble();
  if (trouble === "reconnecting") {
    return <Banner kind="warn">Reconnecting. Your place and picks are safe. Trying again…</Banner>;
  }
  if (trouble === "offline") {
    return (
      <Banner
        kind="warn"
        title="You're offline."
        action={
          <Button kind="ghost" size="sm" onPress={() => window.location.reload()}>
            Reload
          </Button>
        }
      >
        Check your connection. We&apos;ll keep trying in the background.
      </Banner>
    );
  }
  return null;
}
