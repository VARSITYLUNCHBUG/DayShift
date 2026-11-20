import { Spinner } from "@heroui/react";
import { useQueryClient } from "@tanstack/react-query";
import { lazy, Suspense, useCallback } from "react";
import { Navigate, Outlet, useLocation, useNavigate } from "react-router";

import type { Session } from "../api/session";
import { SESSION_KEY, useSession } from "../api/session";
import { Button } from "../components/Button";
import { ErrorState } from "../components/States";
import { LiveProvider } from "../live/LiveProvider";

// The notices that can show over any page: Ready Up, spot offers and the player's own toasts. They
// load with the first signed-in page, not with the app shell.
const GlobalNotices = lazy(() => import("./GlobalNotices"));

/** Every page that needs a signed-in player sits under this: it opens the live connection and
 * hosts the notices that can show on any page. Signed out, it sends the player to /signin and
 * back afterwards. */
export function SignedIn() {
  const session = useSession();
  const location = useLocation();
  const navigate = useNavigate();
  const client = useQueryClient();

  // The socket closed 4401: the session is gone. Mark it so without asking again, so /signin
  // shows its buttons instead of bouncing back here.
  const here = `${location.pathname}${location.search}`;
  const signedOut = useCallback(() => {
    client.setQueryData<Session>(SESSION_KEY, (old) => (old ? { ...old, signed_in: false, player: null } : old));
    void navigate(`/signin?${new URLSearchParams({ next: here, expired: "1" }).toString()}`, { replace: true });
  }, [client, navigate, here]);

  if (session.isPending) {
    return (
      <div className="flex min-h-dvh items-center justify-center">
        <Spinner aria-label="Loading" />
      </div>
    );
  }
  if (session.isError) {
    return (
      <main id="main" className="mx-auto flex min-h-dvh max-w-dialog items-center px-4">
        <ErrorState
          title="We can't reach DayShift"
          action={
            <Button kind="ghost" onPress={() => void session.refetch()}>
              Try again
            </Button>
          }
        >
          Check your connection. If it keeps happening, DayShift may be restarting.
        </ErrorState>
      </main>
    );
  }
  if (!session.data.signed_in) {
    const next = `${location.pathname}${location.search}`;
    const query = next === "/" ? "" : `?${new URLSearchParams({ next }).toString()}`;
    return <Navigate to={`/signin${query}`} replace />;
  }
  return (
    <LiveProvider onSignedOut={signedOut}>
      <Outlet />
      <Suspense>
        <GlobalNotices />
      </Suspense>
    </LiveProvider>
  );
}
