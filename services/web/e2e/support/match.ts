// Getting a match to where a test starts, fast: the control API fills the lobby and plays the
// other players through the services, and the browser player is made a captain by scripting the
// captain vote. Everything else in a match test happens in the browser.
import { expect } from "@playwright/test";
import type { Locator, Page } from "@playwright/test";

import type { Control, ControlMatch, ControlPlayer, MatchStatus, Team } from "./control";

export interface Lobby {
  id: number;
  /** The eleven others, in the order they joined. */
  others: ControlPlayer[];
  /** The other captain (when `captain` was asked for). */
  rival: ControlPlayer;
}

/**
 * `me` and eleven new players pop a lobby. With `captain` (the default), `me` and the first of the
 * others get the two highest ratings: new players can't be voted for (they need five matches), so
 * the captains are appointed by rating, with no vote. `meQueued` says the browser already joined.
 */
export async function popLobby(
  control: Control,
  me: ControlPlayer,
  options: { captain?: boolean; meQueued?: boolean } = {},
): Promise<Lobby> {
  const captain = options.captain ?? true;
  if (captain) await control.updatePlayer(me.id, { rating: 2000 });
  const rival = await control.createPlayer("Rival", captain ? 1900 : 1200);
  const { players } = await control.createPlayers(10, { name_prefix: "Bot", rating: captain ? 1000 : 1200 });
  if (!options.meQueued) await control.joinQueue([me.id]);
  const { match_id } = await control.joinQueue([rival.id, ...players.map((p) => p.id)]);
  if (match_id === null) throw new Error("Twelve in the queue should pop a lobby.");
  await control.script(match_id, { coinflip: "archmother" });
  return { id: match_id, others: [rival, ...players], rival };
}

/** A lobby with `me` as a captain, advanced (everyone acting through the services) to `status`. */
export async function matchAt(control: Control, me: ControlPlayer, status: MatchStatus): Promise<Lobby & { match: ControlMatch }> {
  const lobby = await popLobby(control, me);
  let match = await control.advance(lobby.id, status);
  expect(match.status, `the match reached ${status}`).toBe(status);
  // deadlock-api's lobby is made; a captain presses Start match, so the game clock runs.
  if (match.turn?.action === "start_match") match = await control.act(lobby.id, "start_match");
  return { ...lobby, match };
}

export function teamOf(match: ControlMatch, playerId: number): Team {
  // A captain has a team from the check-in on; the others from their draft pick.
  if (match.captains.A === playerId) return "A";
  if (match.captains.B === playerId) return "B";
  const player = match.players.find((each) => each.id === playerId);
  if (!player || (player.team !== "A" && player.team !== "B")) throw new Error(`Player ${playerId} has no team.`);
  return player.team;
}

export function otherTeam(team: Team): Team {
  return team === "A" ? "B" : "A";
}

/** The ids of this team's players, captain first. */
export function teamIds(match: ControlMatch, team: Team): number[] {
  const captain = match.captains[team];
  const ids = match.players.filter((each) => each.team === team && each.active).map((each) => each.id);
  return captain === undefined ? ids : [captain, ...ids.filter((id) => id !== captain)];
}

export function nameOf(match: ControlMatch, playerId: number): string {
  const player = match.players.find((each) => each.id === playerId);
  if (!player) throw new Error(`No player ${playerId} in match ${match.id}.`);
  return player.name;
}

/** The room's landmarks. */
export function room(page: Page) {
  return {
    stage: page.getByRole("main"),
    heading: page.getByRole("main").getByRole("heading", { level: 1 }),
    phases: page.getByRole("list", { name: "Match phases" }),
    currentPhase: (name: string): Locator => page.getByRole("listitem", { name: new RegExp(`^${name}, current step`) }),
    lobbyChat: page.getByRole("region", { name: "Lobby chat" }),
    teamChat: page.getByRole("region", { name: "Team chat" }),
  };
}

export async function openRoom(page: Page, id: number): Promise<void> {
  await page.goto(`/matches/${id}`);
  // The scorebug: on every phase, desktop and phone (the phase rail is desktop only).
  await expect(page.getByRole("region", { name: "Now" })).toBeVisible();
}

/** Send a chat line in a chat region and see it there. */
export async function say(chat: Locator, text: string): Promise<void> {
  await chat.getByRole("textbox").fill(text);
  await chat.getByRole("button", { name: "Send" }).click();
  await expect(chat.getByRole("list").getByText(text)).toBeVisible();
}

/** An element's accessible name, as a screen reader hears it (from its ARIA snapshot). */
export async function accessibleName(locator: Locator): Promise<string> {
  const snapshot = await locator.ariaSnapshot();
  const found = /^- \w+ "((?:[^"\\]|\\.)*)"/.exec(snapshot);
  if (!found?.[1]) throw new Error(`No accessible name in: ${snapshot}`);
  return found[1];
}

/** Choose a radio. React Aria hides the input itself (its label is what's pressed), so the
 * visibility check is skipped; the checked state is then asserted like any other. */
export async function choose(radio: Locator): Promise<void> {
  await radio.check({ force: true });
  await expect(radio).toBeChecked();
}
