// Which screen shows a match in each status. A Record over MatchStatus, so a status added to the
// schema (and regenerated into protocol.gen.ts) fails to compile until it has a screen here.
import type { MatchStatus } from "../../../live/types";
import { Cancelled } from "./Cancelled";
import { CaptainVote } from "./CaptainVote";
import { Coinflip, ScrimCoinflip } from "./Coinflip";
import { AwaitingConfirmation } from "./Confirm";
import { HeroDraft } from "./HeroDraft";
import { InGame } from "./InGame";
import { LobbyCode } from "./LobbyCode";
import { PlayerDraft } from "./PlayerDraft";
import { ReadyCheck } from "./ReadyCheck";
import { Completed } from "./Result";
import { Disputed } from "./Review";
import { ScrimClaim, ScrimDrafted } from "./Scrim";
import type { MatchScreen } from "./types";

export const MATCH_SCREENS: Record<MatchStatus, MatchScreen> = {
  ready_check: ReadyCheck,
  captain_phase: CaptainVote,
  player_draft: PlayerDraft,
  // Ranked and scrim coinflips both; Coinflip picks the layout by kind.
  coinflip: Coinflip,
  champion_draft: HeroDraft,
  lobby_code: LobbyCode,
  // The bot-hosted lobby before Start match, then the game.
  in_progress: InGame,
  awaiting_confirmation: AwaitingConfirmation,
  disputed: Disputed,
  completed: Completed,
  // Every match that ended without a result, scrims' included.
  voided: Cancelled,
  // Scrims.
  captain_claim: ScrimClaim,
  ready_to_draft: ScrimCoinflip,
  drafted: ScrimDrafted,
};
