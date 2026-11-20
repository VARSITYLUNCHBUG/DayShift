// /dev/screens/pages (development builds only): every page outside the match room, drawn from
// Django's fixtures (completed.http-*.json and the live snapshots) with no server behind it.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import type { ReactNode } from "react";
import { Link, Route, Routes } from "react-router";

import type { MeSnap } from "../api/live";
import { SESSION_KEY } from "../api/session";
import type { Session } from "../api/session";
import type { PostgameBody } from "../api/types";
import { LiveStatus } from "../app/LiveStatus";
import { ReadyUp } from "../app/notices/ReadyUp";
import { Lockup } from "../components/Brand";
import { AppShell } from "../components/shell/AppShell";
import { FakeServer } from "../live/FakeServer";
import { LiveProvider } from "../live/LiveProvider";
import type { AnySnap } from "../live/types";
import { LadderPage } from "../screens/ladder/Ladder";
import { MatchesPage } from "../screens/matches/Matches";
import { LinkSteamPage } from "../screens/me/LinkSteam";
import { MePage } from "../screens/me/Me";
import { ShareCardPage } from "../screens/me/ShareCard";
import NotFoundPage from "../screens/NotFound";
import { ServerError } from "../screens/errors/PageError";
import { PlayPage } from "../screens/play/Play";
import { PostgamePage } from "../screens/postgame/PostgamePage";
import { SignInPage } from "../screens/signin/SignIn";
import { RandomDraftPage, ScrimsPage } from "../screens/tools/Tools";
import { WelcomePage } from "../screens/welcome/Welcome";
import { http, HTTP_VIEWER, live, PAGES_NOW } from "../screens/fixtures";

const ID = http.match().id;

type Scene = "queued" | "idle" | "cooldown" | "ready" | "pending";

function meFor(scene: Scene): MeSnap {
  if (scene === "cooldown") {
    const me = live.meCooldown();
    // The fixture's cooldown ended at its own clock; keep it running for the gallery.
    if (me.cooldown) me.cooldown.until = new Date(Date.now() + 14 * 60_000).toISOString();
    return me;
  }
  if (scene === "ready") return live.meReady();
  const me = live.meQueued();
  if (scene === "idle") me.queue = { in_queue: false, position: null, joined_at: null, place: null };
  return me;
}

/** A query client already holding every answer, and a fake live server. */
function Data({ scene = "queued", children }: { scene?: Scene; children: ReactNode }) {
  const [setup] = useState(() => {
    const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false, refetchInterval: false } } });
    const session: Session = {
      signed_in: true,
      player: { id: HTTP_VIEWER.id, name: HTTP_VIEWER.name, avatar: null, steam: [{ name: "P3Plays", proven: false, verified: false }] },
      dev_login: true,
      invite_url: "https://discord.gg/example",
    };
    client.setQueryData(SESSION_KEY, session);
    const list = (status: "live" | "recent") => ({ pages: [status === "live" ? { matches: [], next_cursor: null } : http.matches()], pageParams: [null] });
    for (const mine of [true, false]) {
      client.setQueryData(["matches", "list", "recent", mine], list("recent"));
      client.setQueryData(["matches", "list", "live", mine], list("live"));
    }
    client.setQueryData(["matches", ID], http.match());
    const body: PostgameBody = scene === "pending" ? { status: "pending", reason: "no-match-id" } : http.postgame();
    client.setQueryData(["matches", ID, "postgame"], body);
    client.setQueryData(["seasons"], http.seasons());
    client.setQueryData(["me", null], http.me());
    client.setQueryData(["ladder", null], { pages: [http.ladder()], pageParams: [0] });
    const me = meFor(scene);
    const snaps: Record<string, AnySnap> = { me: me, queue: live.queue(), live: live.live() };
    if (scene === "ready" && me.match) {
      // The ready check the gallery's Ready Up shows: half the room has pressed Ready.
      snaps[`match:${me.match.id}`] = { ...(JSON.parse(JSON.stringify(readyMatch(me))) as object) } as AnySnap;
    }
    const server = new FakeServer({ auto: true, playerId: me.player.id, serverTime: new Date().toISOString(), snaps });
    return { client, socket: server.socket() };
  });
  return (
    <QueryClientProvider client={setup.client}>
      <LiveProvider socket={setup.socket}>{children}</LiveProvider>
    </QueryClientProvider>
  );
}

function readyMatch(me: MeSnap) {
  return {
    id: me.match?.id ?? "1",
    status: "ready_check",
    kind: "ranked",
    mode_name: "3-ban draft",
    deadline_at: new Date(Date.now() + 38_000).toISOString(),
    players: Array.from({ length: 12 }, (_, i) => ({
      id: i === 0 ? me.player.id : String(100 + i),
      name: i === 0 ? me.player.name : `P${100 + i}`,
      avatar_url: null,
      is_ready: i > 0 && i % 3 !== 0,
    })),
  };
}

function InShell({ children }: { children: ReactNode }) {
  return (
    <AppShell me={{ name: HTTP_VIEWER.name }} status={<LiveStatus />}>
      {children}
    </AppShell>
  );
}

const PAGES: { path: string; label: string; board: string; element: ReactNode }[] = [
  { path: "play", label: "Play: in the queue", board: "A05", element: <Data><InShell><PlayPage /></InShell></Data> },
  { path: "play-idle", label: "Play: the queue", board: "A04", element: <Data scene="idle"><InShell><PlayPage /></InShell></Data> },
  { path: "play-cooldown", label: "Play: cooldown", board: "A07", element: <Data scene="cooldown"><InShell><PlayPage /></InShell></Data> },
  { path: "ready-up", label: "Ready Up", board: "A08", element: <Data scene="ready"><InShell><PlayPage /><ReadyUp /></InShell></Data> },
  { path: "signin", label: "Sign in", board: "A01", element: <Data><SignInPage /></Data> },
  { path: "link-steam", label: "Link Steam", board: "A03", element: <Data><InShell><LinkSteamPage /></InShell></Data> },
  { path: "matches", label: "Matches", board: "E01", element: <Data><InShell><MatchesPage /></InShell></Data> },
  { path: `matches/${ID}/summary`, label: "Postgame: summary", board: "R07", element: <Data><PostgamePage /></Data> },
  { path: `matches/${ID}/timeline`, label: "Postgame: timeline", board: "R08", element: <Data><PostgamePage /></Data> },
  { path: `matches/${ID}/replay`, label: "Postgame: replay", board: "R09", element: <Data><PostgamePage /></Data> },
  { path: `matches/${ID}/advanced`, label: "Postgame: advanced", board: "R10", element: <Data><PostgamePage /></Data> },
  { path: `pending/${ID}/summary`, label: "Postgame: stats pending", board: "R11", element: <Data scene="pending"><PostgamePage /></Data> },
  { path: "ladder", label: "Ladder", board: "E03", element: <Data><InShell><LadderPage /></InShell></Data> },
  { path: "me", label: "Me", board: "E04", element: <Data><InShell><MePage /></InShell></Data> },
  { path: "me/share", label: "Share card", board: "E05", element: <Data><InShell><ShareCardPage /></InShell></Data> },
  { path: "tools/random-draft", label: "Random draft", board: "E06", element: <Data><InShell><RandomDraftPage /></InShell></Data> },
  { path: "tools/scrims", label: "Scrims", board: "E07", element: <Data><InShell><ScrimsPage /></InShell></Data> },
  { path: "welcome", label: "New player", board: "E10", element: <Data><InShell><WelcomePage /></InShell></Data> },
  { path: "not-found", label: "Not found", board: "E09", element: <Data><InShell><NotFoundPage /></InShell></Data> },
  { path: "error", label: "Server error", board: "E09", element: <Data><InShell><ServerError onRetry={() => window.location.reload()} /></InShell></Data> },
];

function Index() {
  return (
    <div className="mx-auto flex max-w-app flex-col gap-6 px-8 py-10">
      <header className="flex items-center gap-4">
        <Lockup size={22} />
        <span className="text-label font-bold text-muted">· Pages · development only · fixtures at {PAGES_NOW}</span>
      </header>
      <h1 className="text-title">Pages outside the match room</h1>
      <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {PAGES.map((page) => (
          <li key={page.path}>
            <Link to={page.path} className="flex min-h-11 items-center justify-between gap-3 rounded-card border border-line bg-surface px-4 py-3 hover:border-line-strong">
              <b className="text-body font-extrabold">{page.label}</b>
              <span className="text-caption font-bold text-muted">{page.board}</span>
            </Link>
          </li>
        ))}
      </ul>
      <Link to="/dev/screens" className="self-start text-label font-bold underline">
        Back to the components
      </Link>
    </div>
  );
}

export default function PagesGallery() {
  return (
    <Routes>
      <Route index element={<Index />} />
      {PAGES.map((page) =>
        page.path.includes(`/${ID}/`) ? (
          <Route key={page.path} path={page.path.replace(`/${ID}/`, "/:id/").replace(/\/(summary|timeline|replay|advanced)$/, "/:tab")} element={page.element} />
        ) : (
          <Route key={page.path} path={page.path} element={page.element} />
        ),
      )}
    </Routes>
  );
}
