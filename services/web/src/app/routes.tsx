// Every route, each page its own lazy chunk so the first load carries only the shell. Profiles are
// private: there is no /players/:id, only /me.
import { lazy, Suspense } from "react";
import type { ComponentType, ReactNode } from "react";
import { Route, Routes, useLocation } from "react-router";

import { Skeleton } from "../components/States";
import { PageErrorBoundary } from "../screens/errors/PageError";
import { AppLayout } from "./AppLayout";
import { PAGE_CHUNKS } from "./chunks";
import { SignedIn } from "./SignedIn";

/** A named export as a lazy page. */
function page<M>(load: () => Promise<M>, pick: (module: M) => ComponentType) {
  return lazy(() => load().then((module) => ({ default: pick(module) })));
}


const SignInPage = page(() => import("../screens/signin/SignIn"), (m) => m.SignInPage);
const LinkSteamPage = page(PAGE_CHUNKS["/link-steam"], (m) => m.LinkSteamPage);
const PlayPage = page(PAGE_CHUNKS["/"], (m) => m.PlayPage);
const MatchesPage = page(PAGE_CHUNKS["/matches"], (m) => m.MatchesPage);
const MatchRoute = page(() => import("../screens/match/MatchRoute"), (m) => m.MatchRoute);
const PostgamePage = page(PAGE_CHUNKS.postgame, (m) => m.PostgamePage);
const LadderPage = page(PAGE_CHUNKS["/ladder"], (m) => m.LadderPage);
const MePage = page(PAGE_CHUNKS["/me"], (m) => m.MePage);
const ShareCardPage = page(PAGE_CHUNKS["/me/share"], (m) => m.ShareCardPage);
const RandomDraftPage = page(PAGE_CHUNKS["/tools/random-draft"], (m) => m.RandomDraftPage);
const ScrimsPage = page(PAGE_CHUNKS["/tools/scrims"], (m) => m.ScrimsPage);
const WelcomePage = page(() => import("../screens/welcome/Welcome"), (m) => m.WelcomePage);
const NotFoundPage = lazy(() => import("../screens/NotFound"));

// The gallery is for development only; the production build leaves it out entirely.
const Gallery = import.meta.env.DEV ? lazy(() => import("../dev/Gallery")) : null;

function PageLoading() {
  return (
    <div className="mx-auto w-full max-w-app p-8">
      <Skeleton label="Loading the page" />
    </div>
  );
}

/** A page: loading while its chunk arrives, and a retry if it crashes while drawing. */
function Load({ children }: { children: ReactNode }) {
  const { pathname } = useLocation();
  return (
    <PageErrorBoundary resetKey={pathname}>
      <Suspense fallback={<PageLoading />}>{children}</Suspense>
    </PageErrorBoundary>
  );
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
          <Route path="tools" element={<Load><RandomDraftPage /></Load>} />
          <Route path="tools/random-draft" element={<Load><RandomDraftPage /></Load>} />
          <Route path="tools/scrims" element={<Load><ScrimsPage /></Load>} />
          <Route path="welcome" element={<Load><WelcomePage /></Load>} />
          <Route path="*" element={<Load><NotFoundPage /></Load>} />
        </Route>
        {/* The match room has its own shell (room header and phase rail). A finished match's record
            and postgame pick their shell themselves: the room's for its players, the app's for
            everyone else. */}
        <Route path="matches/:id" element={<Load><MatchRoute /></Load>} />
        <Route path="matches/:id/:tab" element={<Load><PostgamePage /></Load>} />
      </Route>
    </Routes>
  );
}
