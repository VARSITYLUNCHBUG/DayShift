// In game (B15): the clock since the start, the code for the 12, and the three things that can
// happen: report the result (captains), someone has to go (Need a sub), someone left early
// (captains, while it's open). The bot's own lobby, before Start match, is BotLobby.
import { useState } from "react";

import { Button } from "../../components/Button";
import { clockTime } from "../../lib/format";
import { useElapsed } from "../../live/hooks";
import { other } from "../../match/model";
import { EarlyLeaveDialog, EarlyLeaveStatus } from "./EarlyLeave";
import { BotLobby } from "./Lobby";
import { Note, StageHead } from "./Parts";
import { ReportForm } from "./Report";
import { Room, useMe } from "./Room";
import type { MatchScreenProps } from "./types";

export function InGame({ match }: MatchScreenProps) {
  if (match.lobby.api_lobby && !match.lobby.api_started) return <BotLobby match={match} />;
  return <Game match={match} />;
}

function Game({ match }: MatchScreenProps) {
  const { myId } = useMe(match);
  const [reporting, setReporting] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const elapsed = useElapsed(match.started_at);
  const isCaptain = match.viewer.is_captain;
  const team = match.viewer.team;
  const otherCaptain = team ? match.captains[other(team)] : null;
  const canReportLeave = isCaptain && match.early_leave.open && !match.early_leave.pending;
  const line = [
    match.started_at ? `Started ${clockTime(match.started_at)}` : null,
    match.lobby_code ? `Lobby ${match.lobby_code}` : null,
  ]
    .filter(Boolean)
    .join(" · ");
  const reportButton = isCaptain ? (
    <Button size="lg" onPress={() => setReporting(true)}>
      Report result
    </Button>
  ) : null;

  return (
    <Room
      match={match}
      heroes
      phaseLine={reporting ? "Result · report" : "Game"}
      now={{
        eyebrow: reporting ? "Game over" : "In game",
        clock: elapsed ? (
          <span role="timer" aria-label={`Game time ${elapsed}`}>
            {elapsed}
          </span>
        ) : undefined,
        title: reporting ? "Report the result" : "Good luck",
        line: line || undefined,
      }}
      footer={!reporting ? reportButton : undefined}
    >
      {reporting ? (
        <ReportForm match={match} myId={myId} onDone={() => setReporting(false)} />
      ) : (
        <>
          <StageHead
            eyebrow="In game"
            title="Good luck"
            lead="The match is on. Nothing to do here until it ends: the result goes in from this page."
          />
          <EarlyLeaveStatus match={match} myId={myId} />
          <section className="flex flex-col gap-4 rounded-panel border border-line-strong bg-surface p-6">
            <h2 className="text-section">When it&apos;s over</h2>
            <p className="text-body text-muted">
              {isCaptain
                ? `You report the winner and the Deadlock match ID; the scoreboard screenshot helps. ${otherCaptain ?? "The other captain"} confirms it, then the postgame opens for everyone.`
                : "A captain reports the winner, the other confirms it, then the postgame opens for everyone."}
            </p>
            {reportButton ? <div className="max-md:hidden">{reportButton}</div> : null}
          </section>
          <div className="grid gap-4 md:grid-cols-2">
            {match.viewer.can_request_sub ? (
              <Note title="Someone has to go">
                Ask for a sub with Need a sub at the top.{" "}
                {isCaptain ? `${otherCaptain ?? "The other captain"} approves a teammate's sub, then` : "Then"} you name a sub or
                offer the spot to the queue. The match pauses until they&apos;re in.
              </Note>
            ) : null}
            {canReportLeave ? (
              <section className="flex flex-col gap-3 rounded-panel border border-line bg-surface px-5 py-4.5">
                <h2 className="font-sans text-body font-extrabold tracking-normal">Someone left early</h2>
                <p className="text-caption text-muted">
                  Report it and {otherCaptain ?? "the other captain"} agrees or disagrees. If they agree, the match is void: no
                  rating change, and the leaver gets a penalty.
                </p>
                <Button kind="danger" size="sm" onPress={() => setLeaving(true)} className="self-start">
                  Report an early leave
                </Button>
              </section>
            ) : null}
          </div>
        </>
      )}
      {leaving ? <EarlyLeaveDialog match={match} myId={myId} onClose={() => setLeaving(false)} /> : null}
    </Room>
  );
}
