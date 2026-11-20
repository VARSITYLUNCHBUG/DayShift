// /matches/:id: the match, live, on the screen for its status. Every status has a screen; adding
// one to the schema (and regenerating protocol.gen.ts) fails to compile until it has one here.
import { Navigate, useParams } from "react-router";

import { useSessionPlayer } from "../../api/session";
import { ButtonLink } from "../../components/Button";
import { EmptyState, Skeleton } from "../../components/States";
import { usePlayerId } from "../../live/hooks";
import type { MatchStatus } from "../../live/protocol.gen";
import { useMatchTopic } from "../../match/live";
import { Coinflip, ScrimClaim, ScrimReady } from "./Coinflip";
import { HeroDraft } from "./HeroDraft";
import { InGame } from "./InGame";
import { LobbyCodeScreen } from "./Lobby";
import { PlayerDraft } from "./PlayerDraft";
import { CaptainCheckIn, CaptainVote, ReadyCheck } from "./PreDraft";
import { AwaitingConfirmation, Cancelled, Completed, Disputed } from "./Result";
import { ScrimDrafted } from "./Scrim";
import type { MatchScreen, MatchScreenProps } from "./types";
import { useMatchToasts } from "./useMatchToasts";

export const MATCH_SCREENS: Record<MatchStatus, MatchScreen> = {
  ready_check: ReadyCheck,
  captain_phase: CaptainVote,
  captain_checkin: CaptainCheckIn,
  player_draft: PlayerDraft,
  // Ranked and scrim coinflips both: the snapshot's options say what can be chosen.
  coinflip: Coinflip,
  champion_draft: HeroDraft,
  lobby_code: LobbyCodeScreen,
  // The bot's lobby before Start match, then the game.
  in_progress: InGame,
  awaiting_confirmation: AwaitingConfirmation,
  disputed: Disputed,
  completed: Completed,
  voided: Cancelled,
  captain_claim: ScrimClaim,
  ready_to_draft: ScrimReady,
  drafted: ScrimDrafted,
};

const MATCH_ID = /^[1-9][0-9]{0,18}$/;

export function MatchView({ match }: MatchScreenProps) {
  const Screen = MATCH_SCREENS[match.status];
  return <Screen match={match} />;
}

export function MatchRoute() {
  const { id = "" } = useParams();
  const valid = MATCH_ID.test(id);
  const { match, state } = useMatchTopic(valid ? id : null);
  const session = useSessionPlayer();
  const myId = usePlayerId() ?? session?.id ?? null;
  useMatchToasts(match, myId);
  // Not live (finished, or never was): its record, which says so if there's no such match.
  if (valid && state === "gone") return <Navigate to={`/matches/${id}/summary`} replace />;
  if (!valid) return <NoSuchMatch id={id} />;
  if (!match) {
    return (
      <main className="mx-auto w-full max-w-room p-8">
        <Skeleton label="Loading the match" />
      </main>
    );
  }
  return <MatchView match={match} />;
}

function NoSuchMatch({ id }: { id: string }) {
  return (
    <main id="main" className="mx-auto flex min-h-dvh w-full max-w-app items-center px-4">
      <EmptyState
        title={MATCH_ID.test(id) ? `No match No. ${id}` : "That isn't a match"}
        action={<ButtonLink to="/matches">See the matches</ButtonLink>}
        className="w-full"
      >
        It may have been on another server, or the link is wrong.
      </EmptyState>
    </main>
  );
}

export default MatchRoute;
