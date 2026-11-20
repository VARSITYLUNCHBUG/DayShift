// A whole ranked match, played in the browser as a captain from the queue to the result. The
// other eleven play through the control API (the same services the Discord buttons call).
import { expectNoA11yViolations } from "./support/axe";
import type { ControlMatch } from "./support/control";
import { expect, test } from "./support/fixtures";
import { accessibleName, nameOf, otherTeam, popLobby, room, teamOf } from "./support/match";
import { JOIN_QUEUE } from "./support/names";

test("a whole ranked match as captain: queue, ready, vote, check-in, drafts, lobby, report, result", async ({
  page,
  me,
  control,
}) => {
  test.setTimeout(120_000);
  const stage = room(page);

  // The queue: the browser joins, the control API fills it, and the Ready Up dialog pops live.
  await page.goto("/");
  await page.getByRole("button", { name: JOIN_QUEUE }).click();
  await expect.poll(async () => (await control.player(me.id)).queued).toBe(true);
  const { id, others, rival } = await popLobby(control, me, { meQueued: true });
  const readyUp = page.getByRole("dialog", { name: "Ready Up" });
  await expect(readyUp).toBeVisible();
  await expect(readyUp.getByRole("timer")).toBeVisible();
  await expectNoA11yViolations(page, { label: "Ready Up dialog" });
  await readyUp.getByRole("button", { name: "Ready", exact: true }).click();
  await expect.poll(async () => (await control.match(id)).players.find((p) => p.id === me.id)?.ready).toBe(true);
  await control.act(id, "ready", { players: others.map((p) => p.id) });

  // The captain vote: vote in the browser, the others by script.
  await page.goto(`/matches/${id}`);
  let match: ControlMatch = await control.match(id);
  if (match.status === "captain_phase") {
    await expect(stage.currentPhase("Captains")).toBeVisible();
    await page.getByRole("button", { name: `Vote for ${rival.name}` }).click();
    await page.getByRole("button", { name: /^Vote for \d captains?$/ }).click();
    await expect(page.getByText("Your vote")).toBeVisible();
    match = await control.advance(id, "captain_checkin");
  }

  // Check-in: I'm here, then the other captain.
  expect(match.status).toBe("captain_checkin");
  const mine = teamOf(match, me.id);
  const theirs = otherTeam(mine);
  expect(match.captains[mine]).toBe(me.id);
  await expect(stage.heading).toHaveText(/check in/i);
  await page.getByRole("button", { name: "I'm here" }).click();
  await expect.poll(async () => (await control.match(id)).players.find((p) => p.id === me.id)?.checked_in).toBe(true);
  await control.act(id, "checkin", { player: rival.id });

  // The player draft: the browser picks on its turns; the other captain is driven.
  await expect(stage.currentPhase("Players")).toBeVisible();
  await expectNoA11yViolations(page, { label: "player draft" });
  const picked: string[] = [];
  for (;;) {
    match = await control.match(id);
    if (match.status !== "player_draft") break;
    if (match.turn?.player_ids.includes(me.id)) {
      const pool = page.getByRole("listbox", { name: "Players left: press one to pick" });
      const option = pool.getByRole("option").first();
      // "Bot 18 1,000 rating": the name from the card's own text, then what the captain picks by.
      const name = (await accessibleName(option)).replace(/\s+[\d,]+ rating$/, "").trim();
      await option.click();
      picked.push(name);
      await control.waitForMatch(id, (m) => m.step_index !== match.step_index || m.status !== "player_draft", "my pick lands");
    } else {
      await control.act(id, "pick", { player: "acting" });
    }
  }
  const myTeamName = `${me.name}'s Team`;
  const myTeam = page.getByRole("region", { name: myTeamName, exact: true });
  for (const name of picked) await expect(myTeam.getByRole("listitem").filter({ hasText: name })).toBeVisible();

  // The coinflip and the team sheet: a wish, then the side (the Hidden King either way).
  expect(match.status).toBe("coinflip");
  await expect(stage.currentPhase("Sides")).toBeVisible();
  const wishes = page.getByRole("region", { name: "Your wishes" });
  await wishes.getByRole("listbox", { name: "Heroes to wish for" }).getByRole("option", { name: "Haze" }).click();
  await expect(page.getByRole("region", { name: `${myTeamName} wants` }).getByText("Haze")).toBeVisible();
  await expectNoA11yViolations(page, { label: "coinflip and team sheet" });
  await control.setLobbies("fail");
  if (match.coinflip_winner === mine) {
    await page.getByRole("button", { name: /The Hidden King/ }).click();
    await page.getByRole("button", { name: "Take The Hidden King" }).click();
  } else {
    await control.act(id, "coinflip", { player: rival.id, args: { choice: "archmother" } });
  }

  // The hero draft: the browser bans and picks for its team (Random once), the rival for theirs.
  await expect(stage.currentPhase("Heroes")).toBeVisible();
  await expectNoA11yViolations(page, { label: "hero draft" });
  let usedRandom = false;
  for (;;) {
    match = await control.match(id);
    if (match.status !== "champion_draft") break;
    const step = match.step_index;
    if (match.turn?.team === mine) {
      if (!usedRandom) {
        await page.getByRole("button", { name: "Random" }).click();
        usedRandom = true;
      } else {
        const grid = page.getByRole("listbox", { name: "Heroes: choose one" });
        await grid.getByRole("option", { disabled: false }).first().click();
        await page.getByRole("button", { name: /^(Ban|Lock in) / }).click();
      }
      await control.waitForMatch(id, (m) => m.step_index !== step || m.status !== "champion_draft", `my step ${step} lands`);
    } else {
      expect(match.turn?.team).toBe(theirs);
      await control.act(id, match.turn?.action ?? "pick", { player: "acting" });
    }
  }

  // The lobby: deadlock-api fails here, so the host enters a code.
  if (match.status === "lobby_code" && match.turn?.action === "api_lobby") {
    match = await control.act(id, "api_lobby", { args: { create: false } });
  }
  if (match.status === "lobby_code") {
    await expect(stage.currentPhase("Lobby")).toBeVisible();
    if (match.turn?.player_ids.includes(me.id)) {
      await expect(stage.heading).toHaveText("You host the lobby");
      await page.getByRole("textbox", { name: "Lobby code" }).fill("E2E42");
      await page.getByRole("button", { name: /^Share code with the 12$/ }).click();
    } else {
      await control.act(id, "lobby_code", { player: "host", args: { code: "E2E42" } });
    }
  }
  await expect(stage.currentPhase("Game")).toBeVisible();
  await expect(page.getByRole("region", { name: "Now" })).toContainText("Lobby E2E42");

  // In game: report with a match ID, the other captain confirms, the result.
  await page.getByRole("button", { name: "Report result" }).click();
  await page.getByRole("button", { name: `${myTeamName} won` }).click();
  await page.getByRole("textbox", { name: "Deadlock match ID" }).fill("140328807");
  await expectNoA11yViolations(page, { label: "report form" });
  await page.getByRole("button", { name: `Send: ${myTeamName} won` }).click();
  await expect(stage.heading).toHaveText(`${myTeamName} won`);
  await expect(page.getByRole("region", { name: "Answers" })).toContainText(`${me.name} reported`);
  await control.act(id, "confirm", { player: rival.id });
  await expect(stage.currentPhase("Result")).toBeVisible();
  await expect(page.getByText(/^You won\./)).toBeVisible();
  const final = await control.match(id);
  expect(final.status).toBe("completed");
  expect(final.winner).toBe(mine);
  expect(nameOf(final, rival.id)).toBe(rival.name);
  await expectNoA11yViolations(page, { label: "result" });
});
