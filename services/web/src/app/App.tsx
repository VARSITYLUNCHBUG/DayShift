import { QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy, Suspense } from "react";
import { BrowserRouter } from "react-router";

import { isSignedOut } from "../api/queries";
import { SESSION_KEY } from "../api/session";
import { AnnouncerProvider } from "../components/Announcer";
import { ThemeProvider } from "../theme/ThemeContext";
import { HeroRouter } from "./HeroRouter";
import { AppRoutes } from "./routes";

// Toasts only matter once something happens, so their region (and its share of React Aria) loads
// after the first paint. The queue itself is a module-level singleton, so nothing is lost.
const ToastRegion = lazy(() => import("../components/ToastRegion"));

const queryClient: QueryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: true } },
  // Any read that finds the session gone asks for the session again, and SignedIn sends the
  // player to sign in (and back afterwards).
  queryCache: new QueryCache({
    onError: (error, query) => {
      if (isSignedOut(error) && query.queryKey[0] !== SESSION_KEY[0]) void queryClient.invalidateQueries({ queryKey: SESSION_KEY });
    },
  }),
});

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <BrowserRouter>
          <HeroRouter>
            <AnnouncerProvider>
              <AppRoutes />
              <Suspense>
                <ToastRegion />
              </Suspense>
            </AnnouncerProvider>
          </HeroRouter>
        </BrowserRouter>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
