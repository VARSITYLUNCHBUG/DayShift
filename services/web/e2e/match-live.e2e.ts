// The room is live: another player's move shows without a reload, and a dropped connection says
// so, then catches up when it comes back.
import type { Page } from "@playwright/test";

import type { Control } from "./support/control";
import { expect, test } from "./support/fixtures";
import { matchAt, openRoom } from "./support/match";
import { liveSwitch } from "./support/network";

/** Hand the turn to the other captain: if the browser player is on the clock, pick for them. */
async function rivalOnTheClock(control: Control, id: number, meId: number): Promise<void> {
  const match = await control.match(id);
  if (match.turn?.player_ids.includes(meId)) await control.act(id, "pick", { player: meId });
}

function pickOrder(page: Page) {
  return page.getByRole("list", { name: "Pick order" });
}

test("the other captain's pick shows up without a reload", async ({ page, me, control }) => {
  const { id, rival } = await matchAt(control, me, "player_draft");
  await rivalOnTheClock(control, id, me.id);
  await openRoom(page, id);
  const pool = page.getByRole("listbox", { name: /^Players left/ });
  const before = await pool.getByRole("option").count();

  const after = await control.act(id, "pick", { player: rival.id });
  const pickedId = after.teams[after.captains.A === rival.id ? "A" : "B"]?.find((pid) => pid !== rival.id);
  const picked = after.players.find((p) => p.id === pickedId);
  if (!picked) throw new Error("The rival picked nobody.");

  await expect(pool.getByRole("option")).toHaveCount(before - 1);
  await expect(pool.getByRole("option", { name: new RegExp(`^${picked.name}\\b`) })).toHaveCount(0);
  await expect(page.getByRole("region", { name: `${rival.name}'s Team` }).getByRole("listitem").filter({ hasText: picked.name })).toBeVisible();
  await expect(pickOrder(page).getByRole("listitem", { name: new RegExp(`${rival.name}: ${picked.name}`) })).toBeVisible();
});

test("a dropped connection shows the banner, and the room catches up when it's back", async ({ page, me, control }) => {
  const { id, rival } = await matchAt(control, me, "player_draft");
  await rivalOnTheClock(control, id, me.id);
  const network = await liveSwitch(page);
  await openRoom(page, id);
  const banner = page.getByText(/^Reconnecting\. Your place and picks are safe/);
  await expect(banner).toBeHidden();

  await network.goOffline();
  // The banner waits a few seconds before it shows, so a blip doesn't flash it.
  await expect(banner).toBeVisible({ timeout: 15_000 });
  const after = await control.act(id, "pick", { player: rival.id });
  const pickedId = after.teams[after.captains.A === rival.id ? "A" : "B"]?.find((pid) => pid !== rival.id);
  const picked = after.players.find((p) => p.id === pickedId);
  if (!picked) throw new Error("The rival picked nobody.");
  const rivalTeam = page.getByRole("region", { name: `${rival.name}'s Team` });
  // Offline, the room can't have heard about it.
  await expect(rivalTeam.getByRole("listitem").filter({ hasText: picked.name })).toHaveCount(0);

  await network.goOnline();
  await expect(banner).toBeHidden({ timeout: 15_000 });
  await expect(page.getByRole("region", { name: `${rival.name}'s Team` }).getByRole("listitem").filter({ hasText: picked.name })).toBeVisible();
});
