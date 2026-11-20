// A finished match with a postgame. The match is reported with the Deadlock match ID of the
// real deadlock-api metadata in tests/fixtures/deadlock/, and `manage.py build_postgames
// --metadata-file` builds its postgame from that file, so nothing goes to deadlock-api.
import { execFile } from "node:child_process";
import { resolve } from "node:path";
import { promisify } from "node:util";

import { expect } from "@playwright/test";
import type { Page } from "@playwright/test";

import type { Control, ControlPlayer } from "./control";
import { matchAt, teamOf } from "./match";

const run = promisify(execFile);
const REPO = resolve(import.meta.dirname, "../../../..");
export const DEADLOCK_MATCH_ID = "140328807";
const METADATA = resolve(REPO, "tests/fixtures/deadlock/match_140328807_metadata.json.gz");

/** POST the result as the signed-in captain, through the same HTTP API the report form uses. */
async function report(page: Page, matchId: number, winner: "A" | "B"): Promise<void> {
  await page.request.get("/api/session/");
  const csrf = (await page.context().cookies()).find((cookie) => cookie.name === "csrftoken")?.value ?? "";
  const response = await page.request.post(`/api/matches/${matchId}/report/`, {
    headers: { "X-CSRFToken": csrf },
    multipart: { winner, deadlock_match_id: DEADLOCK_MATCH_ID },
  });
  expect(response.status(), await response.text()).toBe(200);
}

export async function finishedMatchWithPostgame(page: Page, control: Control, me: ControlPlayer): Promise<number> {
  const { id, match, rival } = await matchAt(control, me, "in_progress");
  await report(page, id, teamOf(match, me.id));
  await control.act(id, "confirm", { player: rival.id });
  await control.waitForMatch(id, (m) => m.status === "completed", "the match is completed");
  // The stack's environment (DATABASE_URL and the rest) comes from scripts/web-e2e.sh.
  await run("uv", ["run", "--frozen", "python", "manage.py", "build_postgames", "--match", String(id), "--metadata-file", METADATA], {
    cwd: REPO,
    env: process.env,
  });
  return id;
}
