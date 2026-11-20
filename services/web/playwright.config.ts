/// <reference types="node" />
// The web UI's end-to-end suite (e2e/). scripts/web-e2e.sh starts the stack and sets BASE_URL;
// e2e/README.md says how to run it. Test files end in .e2e.ts, so Vitest never picks them up.
import { defineConfig, devices } from "@playwright/test";

const baseURL = process.env.BASE_URL ?? "http://127.0.0.1:8000";

export default defineConfig({
  testDir: "./e2e",
  testMatch: /.*\.e2e\.ts$/,
  outputDir: "./test-results/artifacts",
  // One league per stack: the queue and the live matches are shared by every test, so the tests
  // run one at a time and each starts from a reset league (e2e/support/fixtures.ts).
  workers: 1,
  fullyParallel: false,
  forbidOnly: true,
  retries: 0,
  timeout: 30_000,
  expect: { timeout: 7_500 },
  reporter: [["list"], ["html", { outputFolder: "./test-results/report", open: "never" }]],
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
    locale: "en-GB",
    timezoneId: "UTC",
    actionTimeout: 7_500,
    navigationTimeout: 15_000,
  },
  projects: [
    {
      // The pre-commit set: quick checks of the shell, sign-in and the queue.
      name: "smoke",
      grep: /@smoke/,
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } },
    },
    {
      name: "desktop",
      grepInvert: /@phone/,
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } },
    },
    {
      // Pixel-like: 390×844, touch. Only the tests written for the phone layout.
      name: "phone",
      grep: /@phone/,
      use: {
        ...devices["Pixel 7"],
        viewport: { width: 390, height: 844 },
        deviceScaleFactor: 2,
        isMobile: true,
        hasTouch: true,
      },
    },
  ],
});
