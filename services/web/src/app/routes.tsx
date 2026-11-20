// Every route, each page its own lazy chunk so the first load carries only the shell. Profiles are
// private: there is no /players/:id, only /me.
import { lazy, Suspense } from "react";
import type { ComponentType, ReactNode } from "react";
import { Route, Routes } from "react-router";

import { Skeleton } from "../components/States";
import { AppLayout } from "./AppLayout";
import { SignedIn } from "./SignedIn";

/** A named export as a lazy page. */
function page<M>(load: () => Promise<M>, pick: (module: M) => ComponentType) {
  return lazy(() => load().then((module) => ({ default: pick(module) })));
}

const SignInPage = page(() => import("../legacy/screens/signin/SignIn"), (m) => m.SignInPage);
const LinkSteamPage = page(() => import("../legacy/screens/LinkSteam"), (m) => m.LinkSteamPage);
const PlayPage = page(() => import("../legacy/screens/play/Play"), (m) => m.PlayPage);
const MatchesPage = page(() => import("../legacy/screens/matches/Matches"), (m) => m.MatchesPage);
const MatchRoute = page(() => import("../legacy/screens/match/MatchRoute"), (m) => m.MatchRoute);
const LadderPage = page(() => import("../legacy/screens/stats/LeaderboardPage"), (m) => m.LeaderboardPage);
const MePage = page(() => import("../legacy/screens/stats/ProfilePage"), (m) => m.MyProfilePage);
const RandomDraftPage = page(() => import("../legacy/screens/tools/RandomDraftPage"), (m) => m.RandomDraftPage);
const ShareCardPage = lazy(() => import("../screens/ShareCard"));
const NotFoundPage = lazy(() => import("../screens/NotFound"));
const PostgameTab = lazy(() => import("../screens/postgame/PostgameTab"));

// The gallery is for development only; the production build leaves it out entirely.
const Gallery = import.meta.env.DEV ? lazy(() => import("../dev/Gallery")) : null;

function PageLoading() {
  return (
    <div className="mx-auto w-full max-w-app p-8">
      <Skeleton label="Loading the page" />
    </div>
  );
}

function Load({ children }: { children: ReactNode }) {
  return <Suspense fallback={<PageLoading />}>{children}</Suspense>;
}

export function AppRoutes() {
  return (
    <Routes>
      <Route
        path="/signin"
        element={
          <Load>
            <SignInPage />
          </Load>
        }
      />
      {Gallery ? (
        <Route
          path="/dev/screens/*"
          element={
            <Load>
              <Gallery />
            </Load>
          }
        />
      ) : null}
      <Route element={<SignedIn />}>
        <Route element={<AppLayout />}>
          <Route index element={<Load><PlayPage /></Load>} />
          <Route path="link-steam" element={<Load><LinkSteamPage /></Load>} />
          <Route path="matches" element={<Load><MatchesPage /></Load>} />
          <Route path="ladder" element={<Load><LadderPage /></Load>} />
          <Route path="me" element={<Load><MePage /></Load>} />
          <Route path="me/share" element={<Load><ShareCardPage /></Load>} />
          <Route path="tools/random-draft" element={<Load><RandomDraftPage /></Load>} />
          <Route path="*" element={<Load><NotFoundPage /></Load>} />
        </Route>
        {/* The match room has its own shell (room header and phase rail). */}
        <Route path="matches/:id" element={<Load><MatchRoute /></Load>} />
        <Route path="matches/:id/timeline" element={<Load><PostgameTab tab="timeline" /></Load>} />
        <Route path="matches/:id/replay" element={<Load><PostgameTab tab="replay" /></Load>} />
        <Route path="matches/:id/advanced" element={<Load><PostgameTab tab="advanced" /></Load>} />
      </Route>
    </Routes>
  );
}
