// The pages around the match room: the postgame tabs, privacy, the share card, and axe on each.
import { expectNoA11yViolations } from "./support/axe";
import { expect, test } from "./support/fixtures";
import { finishedMatchWithPostgame } from "./support/postgame";

test("the postgame: Summary, Timeline, Replay (scrubbing) and Advanced all render", async ({ page, me, control }) => {
  test.setTimeout(60_000);
  const id = await finishedMatchWithPostgame(page, control, me);

  await page.goto(`/matches/${id}`);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expectNoA11yViolations(page, { label: "postgame summary" });

  for (const [tab, path] of [["Timeline", "timeline"], ["Replay", "replay"], ["Advanced", "advanced"]] as const) {
    // The result links to each tab ("Postgame: timeline", "Replay", "Advanced"), and each tab to the others.
    const name = new RegExp(`\\b${tab}$`, "i");
    await page.getByRole("link", { name }).or(page.getByRole("tab", { name })).first().click();
    await expect(page).toHaveURL(new RegExp(`/matches/${id}/${path}$`));
    await expect(page.getByRole("main")).not.toBeEmpty();
    if (tab === "Replay") {
      const scrubber = page.getByRole("slider").first();
      await expect(scrubber).toBeVisible();
      const before = await scrubber.getAttribute("aria-valuenow");
      await scrubber.focus();
      await page.keyboard.press("End");
      await expect(scrubber).not.toHaveAttribute("aria-valuenow", before ?? "");
    }
    if (tab === "Advanced") await expect(page.getByRole("table").first()).toBeVisible();
    await expectNoA11yViolations(page, { label: `postgame ${tab}` });
  }
});

test("privacy: Me is yours, the ladder links to nobody, and the API keeps others' data", async ({ page, me, control }) => {
  const other = await control.createPlayer("Someone");
  await page.goto("/me");
  await expect(page.getByRole("heading", { level: 1, name: me.name })).toBeVisible();
  await expect(page.getByText("Only you see this")).toBeVisible();
  await expectNoA11yViolations(page, { label: "Me" });

  await page.goto("/ladder");
  const ladder = page.getByRole("table");
  await expect(ladder.getByRole("rowheader", { name: other.name })).toBeVisible();
  await expect(ladder.getByRole("link")).toHaveCount(0);
  await expectNoA11yViolations(page, { label: "Ladder" });

  const mine = await page.request.get("/api/me/");
  expect(mine.status()).toBe(200);
  expect(JSON.stringify(await mine.json())).toContain(me.name);
  for (const path of [`/api/players/${other.id}/`, `/api/players/${other.id}/profile/`, `/api/me/?player=${other.id}`]) {
    const response = await page.request.get(path);
    if (response.status() === 200) {
      expect(JSON.stringify(await response.json()), `${path} must not hand over ${other.name}`).not.toContain(other.name);
    } else {
      expect([403, 404]).toContain(response.status());
    }
  }
  const ladderRows = await (await page.request.get("/api/ladder/")).json() as { rows?: Record<string, unknown>[] };
  for (const row of ladderRows.rows ?? []) expect(row).not.toHaveProperty("id");
});

test("the share card: the toggles change the image, and Download gives a PNG", async ({ page, me }) => {
  await page.goto("/me/share");
  await expect(page.getByRole("heading", { level: 1, name: "Your share card" })).toBeVisible();
  const card = page.getByRole("img", { name: /^Your share card/ });
  await expect(card).toBeVisible();
  const before = await card.getAttribute("src");
  await page.getByRole("checkbox", { name: /^Rating and tier/ }).uncheck({ force: true });
  await expect(page.getByRole("checkbox", { name: /^Rating and tier/ })).not.toBeChecked();
  await expect(card).not.toHaveAttribute("src", before ?? "");
  await expect(card).not.toHaveAccessibleName(/1,200|Diamond|Gold|Silver|Bronze/);
  await expectNoA11yViolations(page, { label: "share card" });

  const download = page.waitForEvent("download");
  await page.getByRole("link", { name: "Download PNG" }).click();
  const file = await download;
  expect(file.suggestedFilename()).toMatch(/\.png$/);
  const path = await file.path();
  const { readFile } = await import("node:fs/promises");
  const bytes = await readFile(path);
  expect([...bytes.subarray(0, 8)]).toEqual([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  expect(me.id).toBeGreaterThan(0);
});

test("axe: the other main pages have no serious or critical violations", async ({ page, me }) => {
  expect(me.id).toBeGreaterThan(0);
  for (const path of ["/", "/matches", "/tools/random-draft"]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expectNoA11yViolations(page, { label: path });
  }
});
