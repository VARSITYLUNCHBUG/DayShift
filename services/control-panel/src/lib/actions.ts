/**
 * Which `matches/{id}/act` actions make sense for a match right now, who can make them, and a
 * starting point for their `args` (devtools/README.md). The server has the last word: this only
 * keeps the act-as picker to what the phase allows.
 */
import type { Action, Match, MatchPlayer, PlayerRef } from "../api";
import { SWAPPABLE, TERMINAL } from "./match";

export interface ActionChoice {
  action: Action;
  label: string;
  /** Who can make it, the likeliest first. Empty: nobody in the match (staff, deadlock-api). */
  actors: PlayerRef[];
  /** The match is waiting for exactly this. */
  onTurn: boolean;
}

const LABELS: Record<Action, string> = {
  ready: "Ready up",
  vote: "Vote for captains",
  checkin: "Check in as captain",
  pick: "Pick",
  ban: "Ban",
  coinflip: "Choose a side (coinflip)",
  teams_ready: "Confirm the teams",
  swap: "Offer a player swap",
  accept_swap: "Accept the swap",
  decline_swap: "Decline the swap",
  api_lobby: "deadlock-api answers the lobby",
  lobby_code: "Enter the lobby code",
  start_match: "Start the match",
  report: "Report the result",
  confirm: "Confirm the result",
  dispute: "Dispute the result",
  resolve: "Resolve the dispute (staff)",
  void: "Void the match (staff)",
  request_sub: "Ask to sub out",
  approve_sub: "Approve the sub-out",
  cancel_sub: "Cancel the sub request",
  invite_sub: "Invite a substitute",
  offer_queue: "Offer the seat to the queue",
  accept_sub: "Accept the sub offer",
  decline_sub: "Decline the sub offer",
};

export function actionLabel(action: Action): string {
  return LABELS[action];
}

/** The read model's turn names a draft pick `player_pick`; the act endpoint calls it `pick`. */
function turnAction(match: Match): string | null {
  const action = match.turn?.action ?? null;
  return action === "player_pick" ? "pick" : action;
}

const active = (match: Match) => match.players.filter((p) => p.active);
const captains = (match: Match) => active(match).filter((p) => p.isCaptain);
const ids = (players: MatchPlayer[]) => players.map((p) => p.id);
const byRating = (players: MatchPlayer[]) => players.slice().sort((a, b) => (b.rating ?? 0) - (a.rating ?? 0));

/** Every action the match's phase allows, the one it waits for first. */
export function validActions(match: Match): ActionChoice[] {
  if (TERMINAL.has(match.status)) return [];
  const turn = match.turn?.playerIds ?? [];
  const wanted = turnAction(match);
  const out: ActionChoice[] = [];
  const add = (action: Action, actors: PlayerRef[]) => {
    out.push({ action, label: LABELS[action], actors, onTurn: action === wanted });
  };
  const live = active(match);
  const caps = ids(captains(match));

  // On hold (an open sub), the league refuses the phase's own actions until the sub is settled.
  switch (match.onHold ? null : match.status) {
    case "ready_check":
      add("ready", turn.length ? turn : ids(live.filter((p) => !p.ready)));
      break;
    case "captain_phase":
      add("vote", turn.length ? turn : ids(live));
      break;
    case "captain_checkin":
      add("checkin", turn.length ? turn : ids(captains(match).filter((p) => !p.checkedIn)));
      break;
    case "player_draft":
      add("pick", turn);
      break;
    case "coinflip":
      add("coinflip", turn);
      break;
    case "team_confirm":
      add("teams_ready", turn.length ? turn : caps);
      break;
    case "champion_draft":
      add(wanted === "ban" ? "ban" : "pick", turn);
      break;
    case "lobby_code":
      if (wanted === "api_lobby") add("api_lobby", []);
      add("lobby_code", turn.length ? turn : ["host"]);
      break;
    case "in_progress":
      if (wanted === "start_match") add("start_match", caps);
      add("report", caps);
      break;
    case "awaiting_confirmation":
      add("confirm", turn.length ? turn : ["other_captain"]);
      add("dispute", turn.length ? turn : ["other_captain"]);
      break;
    case "disputed":
      add("resolve", []);
      break;
  }

  if ((match.swapOpen ?? SWAPPABLE.has(match.status)) && !match.onHold) {
    const pending = match.swaps.find((s) => s.status === "pending");
    if (pending) {
      const answering = caps.filter((id) => id !== pending.requestedBy);
      add("accept_swap", answering);
      add("decline_swap", answering);
    } else {
      add("swap", caps);
    }
  }

  // A sub-out waits for the other captain ("approval"), then for someone to fill it ("open").
  const openSub = match.subRequests.find((s) => s.status === "approval" || s.status === "open");
  if (openSub) {
    if (openSub.status === "approval") add("approve_sub", caps);
    else {
      add("invite_sub", ["requester"]);
      add("offer_queue", ["requester"]);
    }
    add("cancel_sub", ["requester"]);
    if (openSub.pendingOffers) {
      add("accept_sub", ["offered"]);
      add("decline_sub", ["offered"]);
    }
  } else {
    add("request_sub", ids(live.filter((p) => !p.isCaptain)).concat(caps));
  }
  add("void", []);

  // What the match waits for first, then the rest in flow order.
  return out.sort((a, b) => Number(b.onTurn) - Number(a.onTurn));
}

/** A starting point for an action's `args`, for the player making it. */
export function argsFor(action: Action, match: Match, actor: PlayerRef | null): Record<string, unknown> {
  const live = active(match);
  const me = live.find((p) => p.id === actor);
  switch (action) {
    case "vote":
      return { candidates: ids(byRating(live)).slice(0, 2) };
    case "pick":
      if (match.status === "player_draft") {
        return { player_id: byRating(live.filter((p) => p.team === null))[0]?.id ?? null };
      }
      return { champion: "haze" };
    case "ban":
      return { champion: "seven" };
    case "coinflip":
      return { choice: "hidden_king" };
    case "swap": {
      const team = me?.team ?? "A";
      const other = team === "A" ? "B" : "A";
      const first = (t: "A" | "B") => live.find((p) => p.team === t && !p.isCaptain)?.id ?? null;
      return { give: first(team), take: first(other) };
    }
    case "accept_swap":
    case "decline_swap":
      return { swap_id: match.swaps.find((s) => s.status === "pending")?.id ?? null };
    case "api_lobby":
      return { create: true };
    case "lobby_code":
      return { code: `DEV${match.id}` };
    case "report":
      return { winner: "A" };
    case "dispute":
      return { note: "Score was the other way round" };
    case "resolve":
      return { outcome: "A" };
    case "void":
      return { reason: "dev" };
    case "approve_sub":
      return { approve: true };
    case "invite_sub":
      return { invitee: "queued:1" };
    default:
      return {};
  }
}
