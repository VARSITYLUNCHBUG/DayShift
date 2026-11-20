import { Outlet } from "react-router";

import { useSessionPlayer } from "../api/session";
import { AppShell } from "../components/shell/AppShell";
import { LiveStatus } from "./LiveStatus";

/** The layout route for every signed-in page that isn't a match: the DayShift app shell. */
export function AppLayout() {
  const player = useSessionPlayer();
  return (
    <AppShell me={player ? { name: player.name, avatar: player.avatar } : null} status={<LiveStatus />}>
      <Outlet />
    </AppShell>
  );
}
