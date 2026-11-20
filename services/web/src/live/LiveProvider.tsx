import { useEffect, useState } from "react";
import type { ReactNode } from "react";

import { LiveContext } from "./context";
import { LiveSocket, liveUrl } from "./LiveSocket";

interface Props {
  children: ReactNode;
  /** A socket made elsewhere (tests, the screen gallery). Otherwise one to /ws/ is made here. */
  socket?: LiveSocket;
  onSignedOut?: () => void;
}

/** Owns the tab's one live connection while signed in. */
export function LiveProvider({ children, socket, onSignedOut }: Props) {
  const [live] = useState(() => socket ?? new LiveSocket({ url: liveUrl() }));

  useEffect(() => {
    if (onSignedOut) live.setSignedOutHandler(onSignedOut);
  }, [live, onSignedOut]);

  useEffect(() => {
    live.start();
    return () => {
      live.stop();
    };
  }, [live]);

  return <LiveContext value={live}>{children}</LiveContext>;
}
