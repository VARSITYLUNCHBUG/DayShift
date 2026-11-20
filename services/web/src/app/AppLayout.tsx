import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useRef } from "react";
import type { SyntheticEvent } from "react";
import { Outlet } from "react-router";

import { prefetchPath } from "../api/queries";
import { useSessionPlayer } from "../api/session";
import { AppShell } from "../components/shell/AppShell";
import { LiveStatus } from "./LiveStatus";
import { PAGE_CHUNKS } from "./chunks";

/** Warms a link's page (its chunk and its data) when the pointer rests on it or it takes focus:
 * one listener for the whole shell, so the shared nav needs no changes. */
export function usePrefetchLinks() {
  const client = useQueryClient();
  const seen = useRef(new Set<string>());
  return useCallback(
    (event: SyntheticEvent) => {
      const link = event.target instanceof Element ? event.target.closest("a[href]") : null;
      if (!(link instanceof HTMLAnchorElement) || link.origin !== window.location.origin) return;
      const path = link.pathname.replace(/\/$/, "") || "/";
      if (seen.current.has(path)) return;
      seen.current.add(path);
      const chunk = path in PAGE_CHUNKS ? PAGE_CHUNKS[path as keyof typeof PAGE_CHUNKS] : /^\/matches\/\d+\/\w+$/.test(path) ? PAGE_CHUNKS.postgame : null;
      void chunk?.().catch(() => undefined);
      prefetchPath(client, path);
      // Let a later hover ask again once the data may have moved on.
      setTimeout(() => seen.current.delete(path), 30_000);
    },
    [client],
  );
}

/** The layout route for every signed-in page that isn't a match: the DayShift app shell. */
export function AppLayout() {
  const player = useSessionPlayer();
  const prefetch = usePrefetchLinks();
  return (
    <div className="contents" onPointerOver={prefetch} onFocus={prefetch}>
      <AppShell me={player ? { name: player.name, avatar: player.avatar } : null} status={<LiveStatus />}>
        <Outlet />
      </AppShell>
    </div>
  );
}
