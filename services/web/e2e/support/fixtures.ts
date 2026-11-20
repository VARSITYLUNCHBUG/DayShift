// The suite's `test`: every test starts from a reset league (the dev fixtures, an empty queue, no
// matches), so no test sees another's players or matches. The league is one per stack, which is
// why playwright.config.ts runs one worker. An uncaught error in the page fails the test too.
import { expect, test as base } from "@playwright/test";

import { signInAs } from "./auth";
import { Control } from "./control";
import type { ControlPlayer } from "./control";

interface TestFixtures {
  /** Resets the league before the test. Automatic. */
  freshLeague: undefined;
  /** The uncaught errors thrown in `page` (each one fails the test at its end). Automatic. */
  pageErrors: Error[];
  /** A new player, signed in on `page`. The page isn't navigated. */
  me: ControlPlayer;
}

interface WorkerFixtures {
  control: Control;
}

export const test = base.extend<TestFixtures, WorkerFixtures>({
  control: [
    // Playwright reads a fixture's dependencies from this pattern; this one has none.
    // eslint-disable-next-line no-empty-pattern
    async ({}, provide, workerInfo) => {
      const baseURL = workerInfo.project.use.baseURL;
      if (!baseURL) throw new Error("No baseURL: run the suite through scripts/web-e2e.sh.");
      const control = await Control.open(baseURL);
      await provide(control);
      await control.dispose();
    },
    { scope: "worker" },
  ],
  freshLeague: [
    async ({ control }, provide) => {
      await control.reset();
      await provide(undefined);
    },
    { auto: true },
  ],
  pageErrors: [
    async ({ page }, provide) => {
      const errors: Error[] = [];
      page.on("pageerror", (error) => errors.push(error));
      await provide(errors);
      expect(errors.map((error) => error.stack ?? error.message), "uncaught errors in the page").toEqual([]);
    },
    { auto: true },
  ],
  me: async ({ control, page }, provide) => {
    const player = await control.createPlayer("Tester");
    await signInAs(page, player);
    await provide(player);
  },
});

export { expect };
