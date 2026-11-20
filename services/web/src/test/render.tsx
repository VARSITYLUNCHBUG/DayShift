import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router";

import type { Session } from "../api/session";
import { HeroRouter } from "../app/HeroRouter";
import { SESSION_KEY } from "../api/session";
import { FIXTURE_NOW } from "../match/fixtures";
import type { AckScript } from "../live/FakeServer";
import { FakeServer } from "../live/FakeServer";
import { LiveProvider } from "../live/LiveProvider";
import type { AnySnap, Topic } from "../live/types";

export const SIGNED_IN: Session = {
  signed_in: true,
  player: {
    id: "1",
    name: "P1",
    avatar: null,
    steam: [],
  },
  dev_login: false,
  invite_url: null,
  kofi_url: null,
};

interface Options {
  snaps?: Partial<Record<Topic, AnySnap>>;
  playerId?: string;
  serverTime?: string;
  answer?: (name: string, args: Record<string, unknown>) => AckScript;
  /** The URL to start at, and the route pattern the element sits on (for useParams). */
  route?: string;
  path?: string;
  session?: Session | null;
  /** Leave the live connection out (pages that don't use it). */
  live?: boolean;
}

/** Renders inside everything a page expects: a router, the query client and a live connection
 * answered by a FakeServer. */
export function renderPage(ui: ReactElement, options: Options = {}) {
  const server = new FakeServer({
    auto: true,
    snaps: options.snaps ?? {},
    playerId: options.playerId ?? "1",
    serverTime: options.serverTime ?? FIXTURE_NOW,
    answer: options.answer,
  });
  const socket = server.socket();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  if (options.session !== null) client.setQueryData(SESSION_KEY, options.session ?? SIGNED_IN);
  const body = options.path ? (
    <Routes>
      <Route path={options.path} element={ui} />
    </Routes>
  ) : (
    ui
  );
  const result = render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[options.route ?? "/"]}>
        <HeroRouter>
          {options.live === false ? body : <LiveProvider socket={socket}>{body}</LiveProvider>}
        </HeroRouter>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { ...result, server, socket, client };
}
