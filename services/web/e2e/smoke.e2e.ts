// The pre-commit set (@smoke): the shell loads, sign-in works, the queue answers over the socket,
// unknown pages say so, and the two pages everyone sees first pass axe. Under a minute.
import { sessionPlayer, signInAs } from "./support/auth";
import { expectNoA11yViolations } from "./support/axe";
import { expect, test } from "./support/fixtures";
import { JOIN_QUEUE, LEAVE_QUEUE } from "./support/names";

const JOIN = JOIN_QUEUE;
const LEAVE = LEAVE_QUEUE;

test.describe("smoke", { tag: "@smoke" }, () => {
  test("the built app renders the sign-in screen with no errors in the page", async ({ page, pageErrors }) => {
    const response = await page.goto("/signin");
    expect(response?.status()).toBe(200);
    // A broken bundle leaves #root empty: the screen must actually render.
    await expect(page.locator("#root")).not.toBeEmpty();
    await expect(page.getByRole("main")).toBeVisible();
    await expect(page.getByRole("link", { name: /sign in with discord/i })).toBeVisible();
    // The fixture fails every test on an uncaught page error; this one says so up front.
    expect(pageErrors.map((error) => error.message)).toEqual([]);
  });

  test("signed out, every page goes to sign-in, which offers Discord, Steam and the dev login", async ({ page }) => {
    await page.goto("/matches");
    await expect(page).toHaveURL(/\/signin/);
    await expect(page.getByRole("link", { name: /sign in with discord/i })).toBeVisible();
    await expect(page.getByRole("link", { name: /sign in with steam/i })).toBeVisible();
    await expect(page.getByRole("link", { name: /dev login/i })).toBeVisible();
  });

  test("the dev login signs a new player in, and Play shows the queue", async ({ page }) => {
    await page.goto("/signin");
    await page.getByRole("link", { name: /dev login/i }).click();
    await expect(page.getByRole("heading", { name: "Dev sign-in" })).toBeVisible();
    await page.getByRole("textbox", { name: "Name" }).fill("Smoke Tester");
    await page.getByRole("button", { name: "Sign in", exact: true }).click();

    await expect(page).not.toHaveURL(/\/(signin|auth)\b/);
    await expect(page.getByRole("button", { name: JOIN })).toBeVisible();
    const session = await page.request.get("/api/session/");
    expect(await session.json()).toMatchObject({ signed_in: true, player: { name: "Smoke Tester" } });
  });

  test("join and leave the queue, and see another player join live", async ({ page, me, control }) => {
    await page.goto("/");
    await page.getByRole("button", { name: JOIN }).click();
    await expect(page.getByRole("button", { name: LEAVE })).toBeVisible();
    await expect.poll(async () => (await control.player(me.id)).queued).toBe(true);
    await expect(page.getByRole("img", { name: "1 of 12 in the queue" })).toBeVisible();

    // Someone else joins through the services: the page hears it over the socket, no reload.
    const other = await control.createPlayer("Queuemate");
    await control.joinQueue([other.id]);
    // Only you see your place, so the page shows the count: it goes from 1 to 2 of 12.
    await expect(page.getByRole("img", { name: "2 of 12 in the queue" })).toBeVisible();

    // Leaving holds your place for a few minutes, and Play offers it back.
    await page.getByRole("button", { name: LEAVE }).click();
    await expect(page.getByRole("heading", { name: "Your place is held" })).toBeVisible();
    await expect(page.getByRole("button", { name: /^Rejoin/ })).toBeVisible();
    await expect.poll(async () => (await control.player(me.id)).queued).toBe(false);
  });

  test("an unknown page says so and leads back to Play", async ({ page, me }) => {
    expect((await sessionPlayer(page))?.id).toBe(String(me.id));
    await page.goto("/no-such-page");
    await expect(page.getByRole("heading", { name: /can.t find that page|nothing here|not found/i })).toBeVisible();
    await page.getByRole("link", { name: /back to play/i }).click();
    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByRole("button", { name: JOIN })).toBeVisible();
  });

  test("axe: sign-in and Play have no serious or critical violations", async ({ page, control }) => {
    await page.goto("/signin");
    await expect(page.getByRole("link", { name: /sign in with discord/i })).toBeVisible();
    await expectNoA11yViolations(page, { label: "sign-in" });

    const player = await control.createPlayer("Axe");
    await signInAs(page, player);
    await page.goto("/");
    await expect(page.getByRole("button", { name: JOIN })).toBeVisible();
    await expectNoA11yViolations(page, { label: "Play" });
  });
});
