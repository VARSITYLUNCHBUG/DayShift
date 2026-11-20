// What the room's screens work out from a match snapshot. Pure functions, no React: the server
// decides every rule, these only read what it sent.
import type { TeamKey } from "../components/team";
import { byName, teamName } from "../lib/format";
import type {
  ChampionChoice,
  ChampionRef,
  DraftActionKind,
  MatchPlayer,
  MatchSnap,
  Side,
  SubEntry,
  Team,
  Wish,
} from "../live/protocol.gen";

export const TEAMS = ["A", "B"] as const satisfies readonly Team[];

export function other(team: Team): Team {
  return team === "A" ? "B" : "A";
}

/** The colour a team wears: its side once the coinflip has set one. Before that, team A wears
 * The Hidden King's amber and B The Archmother's blue, so the lobby chat and the player draft can
 * tell the two apart (the board's choice). */
export function teamKey(match: Pick<MatchSnap, "sides">, team: Team): TeamKey {
  return match.sides[team] ?? (team === "A" ? "hk" : "am");
}

/** The colour for a player, or none while they're not on a team. */
export function playerKey(match: Pick<MatchSnap, "sides">, team: Team | null | undefined): TeamKey | null {
  return team ? teamKey(match, team) : null;
}

export function nameOf(match: MatchSnap, team: Team): string {
  return teamName(match.team_names, team);
}

/** The team playing a side. */
export function teamOfSide(match: Pick<MatchSnap, "sides">, side: Side): Team | null {
  return match.sides.A === side ? "A" : match.sides.B === side ? "B" : null;
}

/** The two teams in the order the board draws them: The Hidden King on the left once sides are
 * set, team A before. */
export function leftRight(match: Pick<MatchSnap, "sides">): [Team, Team] {
  const left = teamOfSide(match, "hk") ?? "A";
  return [left, other(left)];
}

export function player(match: MatchSnap, id: string | null | undefined): MatchPlayer | undefined {
  if (!id) return undefined;
  return match.players.find((p) => p.id === id);
}

/** A team's players, captain first, then by name. */
export function teamPlayers(match: MatchSnap, team: Team): MatchPlayer[] {
  return match.players.filter((p) => p.team === team).sort((a, b) => Number(b.is_captain) - Number(a.is_captain) || byName(a, b));
}

/** Players the captains can still pick in the player draft. */
export function playerPool(match: MatchSnap): MatchPlayer[] {
  return match.players.filter((p) => !p.is_captain && p.team === null).sort(byName);
}

export function captainOf(match: MatchSnap, team: Team): MatchPlayer | undefined {
  return match.players.find((p) => p.is_captain && p.team === team);
}

/** "49% to win", only when the snapshot has a chance to show. */
export function winChance(match: MatchSnap, team: Team): string | null {
  if (match.win_chance_a === null) return null;
  const a = Math.round(match.win_chance_a * 100);
  return `${team === "A" ? a : 100 - a}% to win`;
}

/** "Captain Rook · 49% to win". */
export function captainLine(match: MatchSnap, team: Team): string {
  const captain = match.captains[team];
  return [captain ? `Captain ${captain}` : null, winChance(match, team)].filter(Boolean).join(" · ");
}

const VERB: Record<DraftActionKind, { noun: string; ing: string }> = {
  player_pick: { noun: "pick", ing: "picking" },
  pick: { noun: "pick", ing: "picking" },
  ban: { noun: "ban", ing: "banning" },
};

export function capital(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** "Your pick", "Vesper is banning". */
export function turnTitle(match: MatchSnap): string {
  const turn = match.turn;
  if (!turn) return "";
  const verb = VERB[turn.action];
  if (match.viewer.is_acting) return `Your ${verb.noun}`;
  return `${turn.captain_name || nameOf(match, turn.team)} is ${verb.ing}`;
}

/** The player draft counts picks across both captains: "Pick 2 of 10 · then Vesper". */
export function playerDraftLine(match: MatchSnap): string {
  const done = match.draft.filter((d) => d.action === "player_pick").length;
  const total = match.player_draft_order.length || done + playerPool(match).length;
  const next = match.turn?.next_captain_name;
  return `Pick ${Math.min(done + 1, total)} of ${total}${next ? ` · then ${next}` : ""} · runs out: a random player`;
}

/** The hero draft: "Ban 4 of 6 · then Vesper picks · runs out: a random hero". */
export function heroDraftLine(match: MatchSnap): string {
  const turn = match.turn;
  if (!turn) return "";
  const next =
    turn.next_captain_name && turn.next_action ? ` · then ${turn.next_captain_name} ${VERB[turn.next_action].noun}s` : "";
  return `${capital(VERB[turn.action].noun)} ${turn.position} of ${turn.total}${next} · runs out: a random hero`;
}

/** The step a pick, ban or random goes with: a stale one is refused, so a double press can't act
 * twice. */
export function stepIndex(match: MatchSnap): number {
  return match.step_index;
}

// --- The hero draft ----------------------------------------------------------------------------

export interface HeroPick {
  champion: ChampionRef;
  team: Team | null;
  random: boolean;
  /** The player who plays it, when the server says. */
  playerId: string | null;
}

/** The heroes banned and picked so far, in draft order. */
export function heroActions(match: MatchSnap): { bans: HeroPick[]; picks: HeroPick[] } {
  const bans: HeroPick[] = [];
  const picks: HeroPick[] = [];
  for (const entry of match.draft) {
    if (!entry.champion || entry.action === "player_pick") continue;
    const line = { champion: entry.champion, team: entry.team, random: entry.random, playerId: entry.player_id };
    (entry.action === "ban" ? bans : picks).push(line);
  }
  return { bans, picks };
}

export type HeroStatus = { kind: "free" } | { kind: "banned" } | { kind: "taken"; team: Team | null };

/** Whether each hero is free, banned or taken, by id. */
export function heroStatus(match: MatchSnap): Map<string, HeroStatus> {
  const { bans, picks } = heroActions(match);
  const status = new Map<string, HeroStatus>();
  for (const ban of bans) status.set(ban.champion.id, { kind: "banned" });
  for (const pick of picks) status.set(pick.champion.id, { kind: "taken", team: pick.team });
  for (const hero of match.champions) {
    if (!status.has(hero.id) && hero.taken) status.set(hero.id, { kind: "taken", team: null });
  }
  return status;
}

/** One cell per step of the hero draft's plan, with the hero once it's done. */
export function heroSteps(match: MatchSnap): { kind: "ban" | "pick"; team: TeamKey; hero: string | null; isRandom: boolean }[] {
  const done = match.draft.filter((d) => d.action !== "player_pick");
  return match.champion_steps.map((step, index) => {
    const entry = done[index];
    return {
      kind: step.action,
      team: step.side,
      hero: entry?.champion?.name ?? null,
      isRandom: entry?.random ?? false,
    };
  });
}

/** The step on the clock, or past the end once every step is done. */
export function heroStepNow(match: MatchSnap): number {
  return match.champion_step ?? match.draft.filter((d) => d.action !== "player_pick").length;
}

export function heroById(match: MatchSnap): Map<string, ChampionChoice> {
  return new Map(match.champions.map((hero) => [hero.id, hero]));
}

// --- Wishes ------------------------------------------------------------------------------------

/** One player's wishes, most wanted first, as champion ids. */
export function wishesOf(wishes: readonly Wish[], playerId: string | null): string[] {
  if (!playerId) return [];
  return wishes
    .filter((w) => w.player_id === playerId)
    .sort((a, b) => a.rank - b.rank)
    .map((w) => w.champion_id);
}

/** Who on your team wants each hero, by champion id: the players' ids in rank order. */
export function wishersByHero(wishes: readonly Wish[]): Map<string, string[]> {
  const by = new Map<string, string[]>();
  for (const wish of [...wishes].sort((a, b) => a.rank - b.rank)) {
    const list = by.get(wish.champion_id) ?? [];
    list.push(wish.player_id);
    by.set(wish.champion_id, list);
  }
  return by;
}

export const MAX_WISHES = 3;

/** Your wishes with this hero added (at the end) or taken off. Null when it would be a fourth. */
export function toggleWish(current: readonly string[], heroId: string): string[] | null {
  if (current.includes(heroId)) return current.filter((id) => id !== heroId);
  if (current.length >= MAX_WISHES) return null;
  return [...current, heroId];
}

// --- Subs --------------------------------------------------------------------------------------

/** Whoever asked, the player leaving if they asked for themself, or the leaver's captain, while
 * the spot is open and nobody is being asked (`subs._can_invite`). The server checks again. */
export function canNameSub(match: MatchSnap, line: SubEntry, myId: string | null): boolean {
  if (!myId || !match.viewer.is_player || line.status !== "open" || line.reason !== "sub_out") return false;
  if (line.offer) return false;
  if (line.requested_by_id === myId) return true;
  if (line.is_self && line.leaving_id === myId) return true;
  return match.viewer.is_captain && line.team !== null && match.viewer.team === line.team;
}

/** The captain who answers a captain's request: the one who didn't ask. */
export function approver(match: MatchSnap, line: SubEntry): MatchPlayer | undefined {
  return match.players.find((p) => p.is_captain && p.id !== line.requested_by_id);
}

export function isApprover(match: MatchSnap, line: SubEntry, myId: string | null): boolean {
  return line.status === "approval" && match.viewer.is_captain && myId !== null && approver(match, line)?.id === myId;
}

/** The match is paused for a sub: someone is subbing out mid-match (a ready check's refill has its
 * own screen). */
export function pausedFor(match: MatchSnap): SubEntry[] {
  return match.subs.filter((line) => line.reason === "sub_out");
}

/** Statuses after which the match's page is a record, not a room. */
export const FINISHED = new Set<MatchSnap["status"]>(["completed", "voided", "drafted"]);
