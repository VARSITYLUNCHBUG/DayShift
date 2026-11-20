// What the postgame pages say about a match, worked out from its record (MatchDetail) and its
// postgame document (league/services/postgame.py). Pure, so the words are tested.
import type { Award, Beat, MatchDetail, MatchEvent, Objective, PendingReason, PlayerLine, Postgame, Side, Team } from "../../api/types";
import { number } from "../../lib/format";
import { compact, gameClock, SIDE_NAME, teamLabel } from "../shared/format";
import { interpolate } from "../../components/charts/scale";

export interface Names {
  /** "Rook's Team", by side. */
  side: Record<Side, string>;
  /** A side's league team letter. */
  team: Record<Side, Team>;
}

/** Each side's team name, from the record's teams and the postgame's letters. */
export function namesOf(detail: MatchDetail, doc: Postgame | null): Names {
  const bySide = (side: Side): Team => {
    const fromDoc = doc?.teams[side].letter;
    if (fromDoc === "A" || fromDoc === "B") return fromDoc;
    const fromDetail = detail.teams.find((team) => team.side === side)?.team;
    return fromDetail ?? (side === "hk" ? "A" : "B");
  };
  const team = { hk: bySide("hk"), am: bySide("am") };
  const name = (side: Side) => {
    const record = detail.teams.find((t) => t.team === team[side]);
    const captain = record?.players.find((p) => p.is_captain)?.name ?? null;
    return record?.name ?? teamLabel(captain, team[side]);
  };
  return { side: { hk: name("hk"), am: name("am") }, team };
}

/** The winning side: the postgame's, else the record's winner and its side. */
export function winningSide(detail: MatchDetail, doc: Postgame | null): Side | null {
  if (doc?.winner) return doc.winner;
  if (!detail.winner) return null;
  return detail.teams.find((team) => team.team === detail.winner)?.side ?? null;
}

export function playerBySlot(doc: Postgame): Map<number, PlayerLine> {
  return new Map(doc.players.map((line) => [line.slot, line]));
}

/** "Rook" or "Rook (Abrams)": a player as the postgame names them. */
export function who(line: PlayerLine | undefined, withHero = false): string {
  if (!line) return "Someone";
  return withHero ? `${line.name} (${line.hero})` : line.name;
}

export const OBJECTIVE_NAME: Record<Objective["kind"], string> = {
  guardian: "Guardian",
  walker: "Walker",
  base_guardian: "Base Guardian",
  shrine: "Shrine",
  patron_shield: "Patron's shield",
  patron: "Patron",
  objective: "Objective",
};

/** The letter an objective shows on the timeline (R08's key). */
export const OBJECTIVE_LETTER: Record<Objective["kind"], string> = {
  guardian: "G",
  walker: "W",
  base_guardian: "B",
  shrine: "S",
  patron_shield: "P",
  patron: "P",
  objective: "O",
};

const LANES: Record<number, string> = { 1: "Yellow lane", 2: "Green lane", 3: "Blue lane", 4: "Purple lane" };

export function laneName(lane: number | null): string | null {
  return lane === null ? null : (LANES[lane] ?? `Lane ${lane}`);
}

/** "+3.1k Rook's Team", "Even": a lead (Hidden King minus Archmother) in words. */
export function leadText(lead: number, names: Names, unit: "souls" | "kills"): string {
  if (lead === 0) return "Even";
  const side: Side = lead > 0 ? "hk" : "am";
  const size = unit === "souls" ? compact(Math.abs(lead)) : number(Math.abs(lead));
  return `${names.side[side]} +${size}`;
}

export interface Moment {
  t: number;
  /** The kind of moment, for the timeline's filters. */
  kind: "kill" | "fight" | "objective" | "mid_boss";
  side: Side | null;
  title: string;
  text: string;
}

/** Every event as a moment with words: "First blood", "Guardian falls", "4–1 fight". */
export function moments(doc: Postgame, names: Names): Moment[] {
  const slots = playerBySlot(doc);
  return doc.events.map((event): Moment => describe(event, doc, names, slots));
}

function describe(event: MatchEvent, doc: Postgame, names: Names, slots: Map<number, PlayerLine>): Moment {
  const side = event.team;
  const team = side ? names.side[side] : "Nobody";
  switch (event.type) {
    case "first_blood": {
      const fb = doc.first_blood;
      const killer = fb?.killer !== null && fb?.killer !== undefined ? slots.get(fb.killer) : undefined;
      const victim = fb ? slots.get(fb.victim) : undefined;
      return { t: event.t, kind: "kill", side, title: "First blood", text: `${who(killer, true)} on ${who(victim, true)}.` };
    }
    case "fight": {
      const fight = doc.fights[event.ref];
      const score = fight ? fightScore(fight, fight.winner ?? side) : "";
      const length = fight ? gameClock(fight.end - fight.start) : "";
      return {
        t: event.t,
        kind: "fight",
        side,
        title: fight?.winner ? `${score} fight to ${names.side[fight.winner]}` : `${score} fight`,
        text: fight ? `${fight.hk + fight.am} deaths in ${length}: ${names.side.hk} got ${fight.hk}, ${names.side.am} got ${fight.am}.` : "",
      };
    }
    case "objective": {
      const objective = doc.objectives[event.ref];
      const what = objective ? OBJECTIVE_NAME[objective.kind] : "Objective";
      const lane = objective ? laneName(objective.lane) : null;
      return {
        t: event.t,
        kind: "objective",
        side,
        title: `${team} take a ${what}`,
        text: objective ? `${names.side[objective.team]}'s ${what.toLowerCase()}${lane ? ` in ${lane}` : ""} falls.` : "",
      };
    }
    case "mid_boss":
      return { t: event.t, kind: "mid_boss", side, title: `Mid Boss to ${team}`, text: `${team} take the Mid Boss and the Rejuvenator.` };
  }
}

/** A fight's kills as "6–1", the winner's first. */
export function fightScore(fight: { hk: number; am: number }, winner: Side | null): string {
  // `hk` and `am` are each side's kills in it.
  if (winner === "am") return `${fight.am}–${fight.hk}`;
  return `${fight.hk}–${fight.am}`;
}

export interface Story {
  t: number;
  title: string;
  text: string;
}

/** The summary's story beats (R07): the first Walker, the Mid Boss, the big fight, the end. */
export function storyBeats(doc: Postgame, names: Names): Story[] {
  return doc.beats.map((beat) => storyOf(beat, doc, names));
}

function swing(beat: Beat, names: Names): string {
  if (beat.soul_lead === 0) return "Souls level.";
  const side: Side = beat.soul_lead > 0 ? "hk" : "am";
  return `${names.side[side]} ${compact(Math.abs(beat.soul_lead))} up.`;
}

function storyOf(beat: Beat, doc: Postgame, names: Names): Story {
  const team = beat.team ? names.side[beat.team] : "Nobody";
  switch (beat.type) {
    case "first_walker": {
      const objective = doc.objectives[beat.ref];
      const lane = objective ? laneName(objective.lane) : null;
      return { t: beat.t, title: "First Walker falls", text: `${team} crack ${lane ?? "a lane"}. ${swing(beat, names)}` };
    }
    case "mid_boss":
      return { t: beat.t, title: `Mid Boss to ${team}`, text: `The Rejuvenator goes to ${team}. ${swing(beat, names)}` };
    case "biggest_fight": {
      const fight = doc.fights[beat.ref];
      const score = fight ? fightScore(fight, fight.winner) : "";
      return { t: beat.t, title: "The big one", text: `${score} to ${team}, the biggest fight of the match. ${swing(beat, names)}` };
    }
    case "patron":
      return { t: beat.t, title: "Patron down", text: `${team} finish it at ${gameClock(beat.t)}.` };
  }
}

/** One line under the result: how the winner got there. */
export function storyLine(doc: Postgame, names: Names): string {
  const winner = doc.winner;
  if (!winner) return `${gameClock(doc.duration_s)} of Deadlock.`;
  const leads = doc.timeline.souls.map((lead) => (winner === "hk" ? lead : -lead));
  const worst = Math.min(0, ...leads);
  const fight = doc.beats.find((beat) => beat.type === "biggest_fight");
  const big = fight ? doc.fights[fight.ref] : undefined;
  const parts: string[] = [];
  if (worst < -1000) parts.push(`${names.side[winner]} were down ${compact(-worst)} souls at one point`);
  else parts.push(`${names.side[winner]} were never behind by much`);
  if (big && fight) parts.push(`then a ${fightScore(big, big.winner)} fight at ${gameClock(fight.t)}`);
  const end = doc.beats.find((beat) => beat.type === "patron");
  parts.push(end ? `Patron down at ${gameClock(end.t)}` : `over at ${gameClock(doc.duration_s)}`);
  return `${parts.join(", ")}.`;
}

/** The soul or kill lead at a moment. */
export function leadAt(doc: Postgame, t: number, unit: "souls" | "kills"): number {
  return Math.round(interpolate(doc.timeline.t, unit === "souls" ? doc.timeline.souls : doc.timeline.kills, t));
}

/** Kills each side has by a moment: the other side's deaths. */
export function killsBy(doc: Postgame, t: number): Record<Side, number> {
  const slots = playerBySlot(doc);
  const out: Record<Side, number> = { hk: 0, am: 0 };
  for (const death of doc.deaths) {
    if (death.t > t) break;
    const victim = slots.get(death.victim);
    if (victim) out[victim.team === "hk" ? "am" : "hk"] += 1;
  }
  return out;
}

export const AWARD_NAME: Record<Award["kind"], string> = {
  mvp: "MVP",
  wrecking_ball: "Wrecking ball",
  first_blood: "First blood",
  the_wall: "The wall",
  field_medic: "Field medic",
  dead_eye: "Dead eye",
};

const stat = (award: Award, key: string) => award.stats[key] ?? 0;

/** What an award was for, from its stats: "18 kills, 48.5k souls, 70.4k hero damage". */
export function awardLine(award: Award, doc: Postgame): string {
  switch (award.kind) {
    case "mvp":
      return `${number(stat(award, "kills"))} kills, ${compact(stat(award, "souls"))} souls, ${compact(stat(award, "damage"))} hero damage`;
    case "wrecking_ball":
      return `${compact(stat(award, "objective_damage"))} objective damage, most in the match`;
    case "first_blood": {
      const victim = playerBySlot(doc).get(stat(award, "victim"));
      return `${victim ? who(victim, true) : "First kill"} at ${gameClock(stat(award, "t"))}`;
    }
    case "the_wall":
      return `${compact(stat(award, "taken"))} damage taken, ${compact(stat(award, "mitigated"))} shrugged off`;
    case "field_medic":
      return `${compact(stat(award, "healing"))} healing`;
    case "dead_eye":
      return `${Math.round(stat(award, "accuracy") * 100)}% accuracy, ${Math.round(stat(award, "crit_rate") * 100)}% headshots`;
  }
}

/** Why there's no postgame yet (R11), and who can fix it. */
export const PENDING: Record<PendingReason, { title: string; text: string }> = {
  later: {
    title: "The match data isn't in yet",
    text: "deadlock-api usually has a match a few minutes after it ends. This page fills in by itself: the timeline, the replay and every number.",
  },
  "no-match-id": {
    title: "No Deadlock match ID for this one",
    text: "The result was reported without a Deadlock match ID, so we only have the result and the draft. Staff can add the ID in Discord; then the timeline, the replay and every number fill in.",
  },
  unavailable: {
    title: "The match data isn't available",
    text: "deadlock-api couldn't give us this match, so the summary has the result and the draft only. Ratings don't wait for it: they come from the confirmed result.",
  },
};

export function sideName(side: Side): string {
  return SIDE_NAME[side];
}
