import type { ReactNode } from "react";

import { useSessionPlayer } from "../../api/session";
import { AppShell as DayShiftAppShell, useInsideAppShell } from "../../components/shell/AppShell";

export const GUIDE_URL = "https://github.com/VARSITYLUNCHBUG/dl-mm-discord/wiki";

/** The old screens wrap themselves in this. Inside the router's DayShift layout it only keeps the
 * old screens' vertical rhythm; anywhere else (a past match under /matches/:id) it draws the
 * DayShift AppShell itself. */
export function AppShell({ children }: { children: ReactNode }) {
  const inside = useInsideAppShell();
  const player = useSessionPlayer();
  const body = <div className="flex flex-col gap-6">{children}</div>;
  if (inside) return body;
  return <DayShiftAppShell me={player ? { name: player.name, avatar: player.avatar } : null}>{body}</DayShiftAppShell>;
}
