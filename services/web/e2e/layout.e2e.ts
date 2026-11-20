// Every page fits every screen: from a 320 px phone to a laptop, nothing scrolls sideways,
// nothing sticks out of the screen, and every control is at least 24 px square (WCAG 2.2's
// target size, 2.5.8), links in running text aside. Each width walks the pages around the room,
// a finished match's record and postgame, and the room through each phase on the way to the game.
// Each page's screenshot is attached, to look over.
import type { Page, TestInfo } from "@playwright/test";

import { expect, test } from "./support/fixtures";
import { openRoom, popLobby } from "./support/match";
import { finishedMatchWithPostgame } from "./support/postgame";

const WIDTHS = (process.env.LAYOUT_WIDTHS ?? "320,390,768,1280").split(",").map(Number);

interface Fit {
  sideways: boolean;
  outside: string[];
  small: string[];
}

/** What doesn't fit at this width. Content inside its own scroller (a wide table, the pick
 * strip) may run past the edge: it scrolls there, not the page. */
async function fitOf(page: Page): Promise<Fit> {
  return page.evaluate(() => {
    const width = document.documentElement.clientWidth;
    const describe = (element: Element) => {
      const name = element.getAttribute("aria-label") ?? element.textContent.trim().slice(0, 40);
      const box = element.getBoundingClientRect();
      return `<${element.tagName.toLowerCase()}> "${name}" ${Math.round(box.width)}×${Math.round(box.height)} at ${Math.round(box.left)}`;
    };
    const scrolls = (element: Element) => {
      for (let up = element.parentElement; up && up !== document.body; up = up.parentElement) {
        if (getComputedStyle(up).overflowX !== "visible") return true;
      }
      return false;
    };
    const shown = (element: Element) => {
      const box = element.getBoundingClientRect();
      const style = getComputedStyle(element);
      // Screen-reader-only text is a clipped pixel: not on the screen at all.
      return box.width > 1 && box.height > 1 && style.visibility !== "hidden" && !element.closest(".sr-only, [data-live-announcer]");
    };
    const outside: string[] = [];
    for (const element of document.querySelectorAll("body *")) {
      if (!shown(element) || scrolls(element)) continue;
      const box = element.getBoundingClientRect();
      if (box.right > width + 1 || box.left < -1) outside.push(describe(element));
    }
    const small: string[] = [];
    const controls = "a[href], button, input:not([type=hidden]), select, textarea, summary, [role=button], [role=tab], [role=option], [role=slider], [role=checkbox], [role=radio], [role=switch]";
    for (const element of document.querySelectorAll(controls)) {
      if (!shown(element)) continue;
      // A link inside a sentence takes the sentence's line: WCAG exempts it.
      if (element.tagName === "A" && getComputedStyle(element).display === "inline") continue;
      // A radio or checkbox drawn inside its label is pressed through the label.
      if (element.matches("input[type=radio], input[type=checkbox]") && element.closest("label")) continue;
      const box = element.getBoundingClientRect();
      if (box.width < 24 || box.height < 24) small.push(describe(element));
    }
    return { sideways: document.documentElement.scrollWidth > width, outside: outside.slice(0, 8), small: small.slice(0, 8) };
  });
}

/** This page at every width: the page is loaded once, and the window resized around it. */
async function checkFit(page: Page, testInfo: TestInfo, label: string): Promise<void> {
  await page.waitForLoadState("networkidle");
  for (const width of WIDTHS) {
    await page.setViewportSize({ width, height: 844 });
    // Two frames, so the resize has been laid out (and the phone layout swapped in) before measuring.
    await page.evaluate(() => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done))));
    const fit = await fitOf(page);
    const path = testInfo.outputPath(`${width}`, `${label}.png`);
    await page.screenshot({ fullPage: true, path });
    await testInfo.attach(`${width}-${label}.png`, { path, contentType: "image/png" });
    expect.soft(fit.sideways, `${label} at ${width}: the page scrolls sideways`).toBe(false);
    expect.soft(fit.outside, `${label} at ${width}: past the screen's edge`).toEqual([]);
    expect.soft(fit.small, `${label} at ${width}: controls under 24 px`).toEqual([]);
  }
}

test.describe("layout", { tag: "@phone" }, () => {
  test(`every page fits ${WIDTHS.join(", ")} px`, async ({ page, me, control }, testInfo) => {
    test.setTimeout(240_000);
    const finished = await finishedMatchWithPostgame(page, control, me);
    const pages: [string, string][] = [
      ["play", "/"],
      ["matches", "/matches"],
      ["record", `/matches/${finished}`],
      ["timeline", `/matches/${finished}/timeline`],
      ["replay", `/matches/${finished}/replay`],
      ["advanced", `/matches/${finished}/advanced`],
      ["ladder", "/ladder"],
      ["me", "/me"],
      ["share", "/me/share"],
      ["random-draft", "/tools/random-draft"],
      ["scrims", "/tools/scrims"],
      ["welcome", "/welcome"],
      ["link-steam", "/link-steam"],
      ["not-found", "/no-such-page"],
    ];
    for (const [label, path] of pages) {
      await page.goto(path);
      await expect(page.getByRole("main")).toBeVisible();
      await checkFit(page, testInfo, label);
    }

    // A lobby just popped is in its ready check; from there the room moves on phase by phase.
    const { id } = await popLobby(control, me);
    for (const status of ["ready_check", "captain_checkin", "player_draft", "coinflip", "champion_draft", "lobby_code", "in_progress"] as const) {
      if (status !== "ready_check") await control.advance(id, status);
      await openRoom(page, id);
      await checkFit(page, testInfo, `room-${status}`);
    }

    await page.context().clearCookies();
    await page.goto("/signin");
    await expect(page.getByRole("link", { name: /Sign in with Discord/ })).toBeVisible();
    await checkFit(page, testInfo, "signin");
  });
});
