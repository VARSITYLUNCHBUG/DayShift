// Changing a match once it's under way: a player swap both ways, a sub through the queue, and an
// early leave that the other captain agrees to.
import type { BrowserContext } from "@playwright/test";

import { openAs } from "./support/auth";
import { expect, test } from "./support/fixtures";
import { accessibleName, choose, matchAt, otherTeam, teamIds, teamOf } from "./support/match";

const contexts: BrowserContext[] = [];
test.afterEach(async () => {
  await Promise.all(contexts.splice(0).map((context) => context.close()));
});

test("a captain asks for a swap and the other captain accepts", async ({ page, me, control }) => {
  const { id, rival } = await matchAt(control, me, "coinflip");
  await page.goto(`/matches/${id}`);
  await page.getByRole("button", { name: "Request a player swap" }).click();
  const give = page.getByRole("radiogroup", { name: "One of yours" }).getByRole("radio").first();
  const take = page.getByRole("radiogroup", { name: "For one of theirs" }).getByRole("radio").first();
  const giveName = await accessibleName(give);
  const takeName = await accessibleName(take);
  await choose(give);
  await choose(take);
  await page.getByRole("button", { name: `Offer ${giveName} for ${takeName}` }).click();
  await expect(page.getByRole("region", { name: "Swap a player" }).getByRole("status")).toContainText(`You asked to swap ${giveName} for ${takeName}`);

  await control.act(id, "accept_swap", { player: rival.id });
  const myTeam = page.getByRole("region", { name: `${me.name}'s Team`, exact: true });
  const theirTeam = page.getByRole("region", { name: `${rival.name}'s Team`, exact: true });
  await expect(myTeam.getByRole("listitem").filter({ hasText: takeName })).toBeVisible();
  await expect(theirTeam.getByRole("listitem").filter({ hasText: giveName })).toBeVisible();
  await expect(myTeam.getByRole("listitem").filter({ hasText: giveName })).toHaveCount(0);
});

test("the other captain asks for a swap and the browser captain answers it", async ({ page, me, control }) => {
  const { id, rival } = await matchAt(control, me, "coinflip");
  await page.goto(`/matches/${id}`);
  const asked = await control.act(id, "swap", { player: rival.id });
  const swap = asked.swaps.find((each) => each.status === "pending");
  if (!swap) throw new Error("No pending swap.");
  const giveName = asked.players.find((p) => p.id === swap.give)?.name ?? "";
  const takeName = asked.players.find((p) => p.id === swap.take)?.name ?? "";

  const sheet = page.getByRole("dialog", { name: `${rival.name} asks to swap ${giveName} for ${takeName}` })
    .or(page.getByRole("region", { name: `${rival.name} asks to swap ${giveName} for ${takeName}` }));
  await expect(sheet).toBeVisible();
  await sheet.getByRole("button", { name: "Accept the swap" }).click();
  await control.waitForMatch(id, (m) => m.swaps.some((each) => each.id === swap.id && each.status === "accepted"), "the swap is accepted");
  await expect(page.getByRole("region", { name: `${me.name}'s Team`, exact: true }).getByRole("listitem").filter({ hasText: giveName })).toBeVisible();
});

test("a sub: the captain asks, the other captain approves, the spot goes to the queue and is taken", async ({ page, me, control }) => {
  const { id, match, rival } = await matchAt(control, me, "in_progress");
  const mine = teamOf(match, me.id);
  const leavingId = teamIds(match, mine).find((pid) => pid !== me.id);
  const leaving = match.players.find((p) => p.id === leavingId);
  if (!leaving) throw new Error("No teammate.");
  await page.goto(`/matches/${id}`);

  await page.getByRole("button", { name: "Need a sub" }).click();
  const ask = page.getByRole("dialog", { name: "Need a sub?" });
  await choose(ask.getByRole("radio", { name: new RegExp(`^${leaving.name}\\b`) }));
  await ask.getByRole("button", { name: `Send to ${rival.name}` }).click();
  await expect(ask).toBeHidden();
  await control.act(id, "approve_sub", { player: rival.id });

  await page.getByRole("button", { name: "Name a sub" }).click();
  const name = page.getByRole("dialog", { name: "Name a sub" });
  await name.getByRole("button", { name: "Offer it to the queue" }).click();
  await expect(name).toBeHidden();

  const sub = await control.createPlayer("Sub");
  await control.joinQueue([sub.id]);
  await control.act(id, "accept_sub", { player: "offered" });
  await expect(page.getByRole("alertdialog", { name: "Sub found" })).toContainText(`${sub.name} is in for ${leaving.name}`);
  const after = await control.waitForMatch(id, (m) => !m.on_hold, "the match runs again");
  expect(after.teams[mine]).toContain(sub.id);
  expect(after.teams[mine]).not.toContain(leaving.id);
});

test("an early leave: one captain reports it, the other agrees, the match is void", async ({ page, me, control, browser }) => {
  const { id, match, rival } = await matchAt(control, me, "in_progress");
  const theirs = otherTeam(teamOf(match, me.id));
  const leaverId = teamIds(match, theirs).find((pid) => pid !== rival.id);
  const leaver = match.players.find((p) => p.id === leaverId);
  if (!leaver) throw new Error("No player on the other team.");
  const other = await openAs(browser, rival, `/matches/${id}`);
  contexts.push(other.context);

  await page.goto(`/matches/${id}`);
  await page.getByRole("button", { name: "Report an early leave" }).click();
  const dialog = page.getByRole("dialog", { name: "Who left early?" });
  await choose(dialog.getByRole("radio", { name: new RegExp(`^${leaver.name}\\b`) }));
  await dialog.getByRole("button", { name: `Report ${leaver.name}` }).click();
  await expect(dialog).toBeHidden();

  const claim = other.page.getByText(`${me.name} says ${leaver.name} left early`);
  await expect(claim).toBeVisible();
  await other.page.getByRole("button", { name: "Agree: void the match" }).click();
  await control.waitForMatch(id, (m) => m.status === "voided", "the match is void");
  await expect(page.getByText("This match didn't happen")).toBeVisible();
});
