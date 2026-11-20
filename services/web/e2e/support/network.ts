// A switch for the live connection. Chromium's offline mode keeps an open websocket, so the suite
// routes /ws/ through Playwright: online, frames pass straight to the server; offline, the open
// sockets close (1001, going away) and new ones are refused, the way a dropped network looks.
import type { Page, WebSocketRoute } from "@playwright/test";

export interface LiveSwitch {
  goOffline(): Promise<void>;
  goOnline(): Promise<void>;
}

export async function liveSwitch(page: Page): Promise<LiveSwitch> {
  let online = true;
  const open = new Set<WebSocketRoute>();
  await page.routeWebSocket(/\/ws\/?$/, (ws) => {
    if (!online) {
      void ws.close({ code: 1001, reason: "offline" });
      return;
    }
    open.add(ws);
    ws.connectToServer();
    ws.onClose(() => open.delete(ws));
  });
  return {
    async goOffline() {
      online = false;
      await page.context().setOffline(true);
      await Promise.all([...open].map((ws) => ws.close({ code: 1001, reason: "offline" })));
      open.clear();
    },
    async goOnline() {
      online = true;
      await page.context().setOffline(false);
    },
  };
}
