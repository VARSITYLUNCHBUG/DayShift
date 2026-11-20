// Signing in without Discord: the DEBUG-only dev login (/auth/dev/, WEB_DEV_LOGIN). The browser
// context's cookie jar is shared by page.request, so a sign-in through the API signs the pages in.
import { expect } from "@playwright/test";
import type { APIRequestContext, Browser, BrowserContext, Page } from "@playwright/test";

import type { ControlPlayer } from "./control";

async function csrfToken(request: APIRequestContext, context: BrowserContext): Promise<string> {
  const page = await request.get("/auth/dev/");
  expect(page.status(), "the dev login is on (WEB_DEV_LOGIN and DEBUG)").toBe(200);
  const cookie = (await context.cookies()).find((each) => each.name === "csrftoken");
  if (!cookie) throw new Error("The dev login set no CSRF cookie.");
  return cookie.value;
}

/** Sign this page's context in as an existing player, by id. Nothing is navigated. */
export async function signInAs(page: Page, player: Pick<ControlPlayer, "id">): Promise<void> {
  const context = page.context();
  const token = await csrfToken(page.request, context);
  const response = await page.request.post("/auth/dev/", {
    form: { csrfmiddlewaretoken: token, player: String(player.id), next: "/" },
    maxRedirects: 0,
  });
  expect(response.status(), `dev login as player ${player.id}`).toBe(302);
}

/** A fresh browser context signed in as this player, with a page open on `path`. */
export async function openAs(
  browser: Browser,
  player: Pick<ControlPlayer, "id">,
  path = "/",
  options: Parameters<Browser["newContext"]>[0] = {},
): Promise<{ context: BrowserContext; page: Page }> {
  const context = await browser.newContext(options);
  const page = await context.newPage();
  await signInAs(page, player);
  await page.goto(path);
  return { context, page };
}

/** Who the session says is signed in (`/api/session/`), or null. */
export async function sessionPlayer(page: Page): Promise<{ id: string; name: string } | null> {
  const response = await page.request.get("/api/session/");
  expect(response.ok()).toBe(true);
  const body = (await response.json()) as { signed_in: boolean; player: { id: string; name: string } | null };
  return body.signed_in ? body.player : null;
}
