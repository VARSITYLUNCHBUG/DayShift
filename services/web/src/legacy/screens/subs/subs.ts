// Who can do what with a sub request, as the server decides it (league/services/subs.py). The
// server checks again on every action; these only decide which buttons to show.
import type { MatchPlayer, MatchSnap, Side, SubEntry, Team } from "../../../live/types";

/** Whoever asked, the player leaving if they asked for themself, or the leaver's captain
 * (`subs._can_invite`), while the spot is open and nobody is being asked. */
export function canNameSub(match: MatchSnap, line: SubEntry, myId: string | null): boolean {
  if (!myId || !match.viewer.is_player || line.status !== "open" || line.reason !== "sub_out") return false;
  if (line.offer) return false;
  if (line.requested_by_id === myId) return true;
  if (line.is_self && line.leaving_id === myId) return true;
  return match.viewer.is_captain && line.team !== null && match.viewer.team === line.team;
}

/** The captain who answers a captain's request: the one who didn't ask. */
export function approver(match: MatchSnap, line: SubEntry): MatchPlayer | null {
  return match.players.find((p) => p.is_captain && p.id !== line.requested_by_id) ?? null;
}

export function isApprover(match: MatchSnap, line: SubEntry, myId: string | null): boolean {
  return line.status === "approval" && match.viewer.is_captain && myId !== null && approver(match, line)?.id === myId;
}

/** The other team's captain, by name. */
export function otherCaptainName(match: MatchSnap, team: Team | null): string | null {
  if (!team) return null;
  return match.captains[team === "A" ? "B" : "A"];
}

/** Text colour for a player's name, by the side their team plays (warning before the coinflip). */
export function sideText(side: Side | null | undefined): string {
  if (side === "hk") return "text-team-hk";
  if (side === "am") return "text-team-am";
  return "text-warning";
}

// Offers accepted from this page. The "You're in" toast leaves out its "Open" button for these:
// accepting here already goes to the match.
const acceptedHere = new Set<string>();

export function markAcceptedHere(offerId: string): void {
  acceptedHere.add(offerId);
}

export function wasAcceptedHere(offerId: string): boolean {
  return acceptedHere.has(offerId);
}

/** For tests. */
export function resetAcceptedHere(): void {
  acceptedHere.clear();
}
