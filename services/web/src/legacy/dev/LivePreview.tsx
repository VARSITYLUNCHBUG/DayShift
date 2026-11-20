import { useState } from "react";
import type { ReactNode } from "react";

import type { AckScript } from "../../live/FakeServer";
import { FakeServer } from "../../live/FakeServer";
import { LiveProvider } from "../../live/LiveProvider";
import type { AnySnap, Topic } from "../../live/types";
import { FIXTURE_NOW } from "./fixtures";

export interface PreviewOptions {
  snaps: Partial<Record<Topic, AnySnap>>;
  playerId?: string;
  serverTime?: string;
  answer?: (name: string, args: Record<string, unknown>) => AckScript;
}

/** A live connection that answers from fixtures instead of Django: the screen gallery and tests
 * render real screens through it. */
export function LivePreview({ children, ...options }: PreviewOptions & { children: ReactNode }) {
  const [socket] = useState(() =>
    new FakeServer({
      auto: true,
      serverTime: FIXTURE_NOW,
      answer: () => ({ ok: false, error: "This is the screen gallery: nothing was sent." }),
      ...options,
    }).socket(),
  );
  return <LiveProvider socket={socket}>{children}</LiveProvider>;
}
