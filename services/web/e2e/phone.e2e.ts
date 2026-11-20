// The phone layout (the `phone` project, 390×844 with touch): the room's one action stays in
// reach, the chat is a full-screen view, and nothing scrolls sideways at 390 or 320 wide.
import type { Locator, Page } from "@playwright/test";

import { expect, test } from "./support/fixtures";
import { matchAt, openRoom, say } from "./support/match";
import { JOIN_QUEUE } from "./support/names";

test.describe("phone", { tag: "@phone" }, () => {
  async function inViewport(page: Page, locator: Locator): Promise<boolean> {
    const box = await locator.boundingBox();
    const viewport = page.viewportSize();
    if (!box || !viewport) return false;
    return box.y >= 0 && box.y + box.height <= viewport.height + 1;
  }

  async function scrollsSideways(page: Page): Promise<boolean> {
    return page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
  }

  test("the room's action is sticky: in reach at the top and the bottom of the page", async ({ page, me, control }) => {
    const { id } = await matchAt(control, me, "in_progress");
    await openRoom(page, id);
    const action = page.getByRole("button", { name: "Report result" });
    await expect(action).toBeVisible();
    expect(await inViewport(page, action), "in view at the top").toBe(true);
    await page.mouse.wheel(0, 5000);
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(0);
    expect(await inViewport(page, action), "in view after scrolling").toBe(true);
    await action.tap();
    await expect(page.getByRole("button", { name: /^Send/ })).toBeVisible();
  });

  test("the chat opens full screen, sends, and goes back to the room", async ({ page, me, control }) => {
    const { id } = await matchAt(control, me, "player_draft");
    await openRoom(page, id);
    await page.getByRole("button", { name: /^Lobby chat/ }).tap();
    const chat = page.getByRole("dialog", { name: "Lobby chat" });
    await expect(chat).toBeVisible();
    const box = await chat.boundingBox();
    const viewport = page.viewportSize();
    expect(box && viewport && box.width >= viewport.width - 1 && box.height >= viewport.height - 1, "fills the screen").toBe(true);
    await say(chat, "on my phone");
    await chat.getByRole("button", { name: "Back to the match" }).tap();
    await expect(chat).toBeHidden();
    await expect(page.getByRole("region", { name: "Now" })).toBeVisible();
  });

  for (const width of [390, 320]) {
    test(`nothing scrolls sideways at ${width} px: Play and every room phase on the way to the game`, async ({ page, me, control }) => {
      await page.setViewportSize({ width, height: 800 });
      await page.goto("/");
      await expect(page.getByRole("button", { name: JOIN_QUEUE })).toBeVisible();
      expect(await scrollsSideways(page), "Play").toBe(false);

      const { id } = await matchAt(control, me, "captain_checkin");
      for (const status of ["player_draft", "coinflip", "champion_draft", "in_progress"] as const) {
        await control.advance(id, status);
        await openRoom(page, id);
        expect(await scrollsSideways(page), status).toBe(false);
      }
    });
  }
});
