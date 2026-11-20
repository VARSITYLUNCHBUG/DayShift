// What the draft screens work out from a match snapshot: whose turn, which step, the pick order.
import type { TurnStep } from "../components/TurnStrip";
import { byName, teamName } from "../lib/format";
import type { CoinflipChoice, DraftActionKind, MatchPlayer, MatchSnap, Side, Team } from "../../live/types";

/** The step the service expects with a pick, ban or random (`Match.step_index`), while a draft
 * runs. A stale one is refused, so a double click can't act twice. */
export function stepIndex(match: MatchSnap): number | null {
  return match.status === "player_draft" || match.status === "champion_draft" ? match.step_index : null;
}

export function playerName(match: MatchSnap, id: string | null | undefined): string | null {
  if (!id) return null;
  return match.players.find((p) => p.id === id)?.name ?? null;
}

/** The team a side plays as. */
export function teamOfSide(match: MatchSnap, side: Side): Team | null {
  return match.sides.A === side ? "A" : match.sides.B === side ? "B" : null;
}

/** A team's players, captain first, then by name. */
export function teamPlayers(match: MatchSnap, team: Team): MatchPlayer[] {
  return match.players
    .filter((p) => p.team === team)
    .sort((a, b) => Number(b.is_captain) - Number(a.is_captain) || byName(a, b));
}

/** Players the captains can still pick. */
export function playerPool(match: MatchSnap): MatchPlayer[] {
  return match.players.filter((p) => !p.is_captain && p.team === null);
}

const VERB: Record<DraftActionKind, { noun: string; ing: string }> = {
  player_pick: { noun: "pick", ing: "picking" },
  pick: { noun: "pick", ing: "picking" },
  ban: { noun: "ban", ing: "banning" },
};

function capital(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** "Your pick", "P2 is banning". */
export function turnTitle(match: MatchSnap): string {
  const turn = match.turn;
  if (!turn) return "";
  const verb = VERB[turn.action];
  if (match.viewer.is_acting) return `Your ${verb.noun}`;
  return `${turn.captain_name || teamName(match.team_names, turn.team)} is ${verb.ing}`;
}

/** The player draft counts picks across both captains: "Pick 8 of 10 · Next: Vesper". */
export function playerDraftLine(match: MatchSnap): string {
  const done = match.draft.filter((d) => d.action === "player_pick").length;
  const total = done + playerPool(match).length;
  const next = match.turn?.next_captain_name;
  return `Pick ${Math.min(done + 1, total)} of ${total}${next ? ` · Next: ${next}` : ""}`;
}

/** The hero draft counts bans and picks apart: "Ban 4 of 6 · Next: P2". */
export function heroDraftLine(match: MatchSnap): string {
  const turn = match.turn;
  if (!turn) return "";
  const next = turn.next_captain_name;
  return `${capital(VERB[turn.action].noun)} ${turn.position} of ${turn.total}${next ? ` · Next: ${next}` : ""}`;
}

/** The player draft's order, one step per pick, labelled with the captain who makes it: the
 * picks made, then every one still to come. */
export function playerPickSteps(match: MatchSnap): TurnStep[] {
  const done = match.draft.filter((d) => d.action === "player_pick");
  const captain = (team: Team) => match.captains[team] ?? teamName(match.team_names, team);
  const drafting = match.status === "player_draft" && match.turn !== null;
  return match.player_draft_order.map(({ step_index: i, team }) => {
    const entry = done[i];
    const number = i + 1;
    if (entry) {
      const by = entry.team ?? team;
      return {
        key: String(i),
        label: captain(by),
        title: `${teamName(match.team_names, by)} took ${entry.label}, pick ${number}`,
        state: "done",
      };
    }
    return {
      key: String(i),
      label: captain(team),
      title: `${teamName(match.team_names, team)} pick, pick ${number}`,
      state: drafting && i === match.step_index ? "current" : "upcoming",
    };
  });
}

interface ChoiceText {
  /** The small line on the card. */
  eyebrow: string;
  title: string;
  tone: Side | "accent";
}

/** How each coinflip choice reads on its card. */
export const COINFLIP_CHOICE: Record<CoinflipChoice, ChoiceText> = {
  hk_pick1: { eyebrow: "The Hidden King", title: "Pick 1", tone: "hk" },
  hk_pick2: { eyebrow: "The Hidden King", title: "Pick 2", tone: "hk" },
  am_pick1: { eyebrow: "The Archmother", title: "Pick 1", tone: "am" },
  am_pick2: { eyebrow: "The Archmother", title: "Pick 2", tone: "am" },
  first_pick: { eyebrow: "Pick order", title: "First pick", tone: "accent" },
  last_pick: { eyebrow: "Pick order", title: "Last pick", tone: "accent" },
  hidden_king: { eyebrow: "Side", title: "The Hidden King", tone: "hk" },
  archmother: { eyebrow: "Side", title: "The Archmother", tone: "am" },
};

/** "First pick", "The Archmother, Pick 2". */
export function choiceName(choice: CoinflipChoice): string {
  const text = COINFLIP_CHOICE[choice];
  return text.eyebrow === "Pick order" || text.eyebrow === "Side" ? text.title : `${text.eyebrow}, ${text.title}`;
}

/** How many ban and pick steps each side has, from the hero draft's plan. */
export function sideSlots(match: MatchSnap, side: Side | null): { bans: number; picks: number } {
  if (!side) return { bans: 0, picks: 0 };
  const steps = match.champion_steps.filter((s) => s.side === side);
  return { bans: steps.filter((s) => s.action === "ban").length, picks: steps.filter((s) => s.action === "pick").length };
}

/** "Pick 1" for the side that bans and picks first. */
export function pickOrder(match: MatchSnap, team: Team): string | null {
  const first = match.champion_steps[0]?.side;
  const side = match.sides[team];
  if (!first || !side) return null;
  return side === first ? "Pick 1" : "Pick 2";
}
