import { createContext, useContext } from "react";
import type { ReactNode } from "react";

import { cn } from "../../lib/cn";
import { useIsPhone } from "../../lib/useMediaQuery";
import { SkipLink } from "../Navigation";
import { ConnectionBanner } from "./ConnectionBanner";
import { PhoneTabs, PhoneTop, TopBar } from "./TopBar";
import type { ShellUser } from "./TopBar";
import { ArtCredit } from "./ArtCredit";

const InsideAppShell = createContext(false);

/** Whether something is already drawn inside an AppShell (for wrappers that add one if not). */
export function useInsideAppShell(): boolean {
  return useContext(InsideAppShell);
}

interface Props {
  me: ShellUser | null;
  /** The status chip (what you're in right now). On phones it moves to the top of the content. */
  status?: ReactNode;
  /** A banner for the app's state (paused, restarting); the connection banner is built in. */
  banner?: ReactNode;
  children: ReactNode;
  /** Narrower pages (sign-in, link Steam). */
  width?: "app" | "narrow";
}

/** Every page that isn't a match (ds.app_page, P01): top bar, banner slot, a centred main up to
 * 1360. On phones: its own top bar and the tab bar (P08). */
export function AppShell({ me, status, banner, children, width = "app" }: Props) {
  const phone = useIsPhone();
  return (
    <InsideAppShell value>
    <div className="flex min-h-dvh flex-col">
      <SkipLink />
      {phone ? <PhoneTop /> : <TopBar me={me} status={status} />}
      <ConnectionBanner />
      {banner}
      <main
        id="main"
        tabIndex={-1}
        className={cn(
          "mx-auto box-border flex w-full flex-1 flex-col outline-none",
          width === "app" ? "max-w-app" : "max-w-dialog",
          phone ? "gap-3.5 px-4 pt-4 pb-24" : "gap-8 px-8 pt-10 pb-14",
        )}
      >
        {phone && status ? <div className="flex">{status}</div> : null}
        {children}
      </main>
      <ArtCredit className={phone && me ? "pb-18" : undefined} />
      {phone && me ? <PhoneTabs /> : null}
    </div>
    </InsideAppShell>
  );
}
