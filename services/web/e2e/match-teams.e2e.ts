// Who sees what: wishes and the team chat stay inside the team, the lobby chat reaches everyone.
// Each player is a browser context of their own, signed in through the dev login.
import type { BrowserContext } from "@playwright/test";

import { openAs } from "./support/auth";
import { expect, test } from "./support/fixtures";
import { matchAt, otherTeam, room, say, teamIds, teamOf } from "./support/match";

const contexts: BrowserContext[] = [];
test.afterEach(async () => {
  await Promise.all(contexts.splice(0).map((context) => context.close()));
});

test("wishes and the team chat reach teammates and nobody on the other team", async ({ page, me, control, browser }) => {
  const { id, match } = await matchAt(control, me, "coinflip");
  const mine = teamOf(match, me.id);
  const [mateId] = teamIds(match, mine).filter((pid) => pid !== me.id);
  const [foeId] = teamIds(match, otherTeam(mine)).filter((pid) => pid !== match.captains[otherTeam(mine)]);
  if (mateId === undefined || foeId === undefined) throw new Error("Both teams should have players.");
  const mate = await openAs(browser, { id: mateId }, `/matches/${id}`);
  const foe = await openAs(browser, { id: foeId }, `/matches/${id}`);
  contexts.push(mate.context, foe.context);

  await page.goto(`/matches/${id}`);
  const myTeamName = `${me.name}'s Team`;
  await page.getByRole("listbox", { name: "Heroes to wish for" }).getByRole("option", { name: "Haze" }).click();
  await expect(page.getByRole("region", { name: `${myTeamName} wants` }).getByText("Haze")).toBeVisible();
  await say(room(page).teamChat, "Push mid at ten");

  // The teammate sees both, live.
  await expect(mate.page.getByRole("region", { name: `${myTeamName} wants` }).getByText("Haze")).toBeVisible();
  await expect(room(mate.page).teamChat.getByText("Push mid at ten")).toBeVisible();

  // The other team sees neither: their own sheet and chat only. Their page has caught up with
  // the same live state (the team chat answers them), so absence means it was never sent.
  await say(room(foe.page).teamChat, "We have a plan too");
  await expect(foe.page.getByRole("region", { name: `${myTeamName} wants` })).toHaveCount(0);
  await expect(foe.page.getByText("Push mid at ten")).toHaveCount(0);
  // (Their own sheet lists only their team: Haze is nobody's wish there.)
  await expect(foe.page.getByRole("region", { name: / wants$/ }).getByText("Haze")).toHaveCount(0);
  await expect(page.getByText("We have a plan too")).toHaveCount(0);

  // And it works the other way round.
  await expect(mate.page.getByText("We have a plan too")).toHaveCount(0);
});

test("the lobby chat reaches all twelve", async ({ page, me, control, browser }) => {
  const { id, match } = await matchAt(control, me, "player_draft");
  const others = match.players.filter((p) => p.id !== me.id).map((p) => p.id);
  const first = await openAs(browser, { id: others[0] ?? 0 }, `/matches/${id}`);
  const last = await openAs(browser, { id: others.at(-1) ?? 0 }, `/matches/${id}`);
  contexts.push(first.context, last.context);

  await page.goto(`/matches/${id}`);
  await say(room(page).lobbyChat, "glhf everyone");
  await expect(room(first.page).lobbyChat.getByText("glhf everyone")).toBeVisible();
  await expect(room(last.page).lobbyChat.getByText("glhf everyone")).toBeVisible();
  await say(room(last.page).lobbyChat, "you too");
  await expect(room(page).lobbyChat.getByText("you too")).toBeVisible();
});
