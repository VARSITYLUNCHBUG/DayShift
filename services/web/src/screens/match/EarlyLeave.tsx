// Early leave (I07, I08, I12): a captain reports who left the game early; the other captain
// agrees (the match is void, the leaver gets a penalty) or not (staff decide). Players only ever
// see "left early", never the window's minutes (D17).
import { useState } from "react";

import { Button } from "../../components/Button";
import { Dialog } from "../../components/Dialog";
import { InlineAlert } from "../../components/InlineAlert";
import { NoticeSheet } from "../../components/NoticeSheet";
import { RadioCards } from "../../components/RadioCards";
import { errorText, notify } from "../../components/toast";
import type { EarlyLeaveClaim, MatchSnap } from "../../live/protocol.gen";
import { useMatchAction } from "../../match/live";
import { leftRight, nameOf, other, teamKey, teamPlayers } from "../../match/model";

export function EarlyLeaveDialog({ match, myId, onClose }: { match: MatchSnap; myId: string | null; onClose: () => void }) {
  const act = useMatchAction();
  const [who, setWho] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const team = match.viewer.team;
  const otherCaptain = team ? match.captains[other(team)] : null;
  const chosen = match.players.find((p) => p.id === who);
  const send = () => {
    if (!who) return;
    setError(null);
    act.run("early_leave.report", { match_id: match.id, player_id: who }).then(
      () => {
        notify.info("Early leave reported", `${otherCaptain ?? "The other captain"} agrees or disagrees next.`);
        onClose();
      },
      (reason: unknown) => setError(errorText(reason)),
    );
  };
  return (
    <Dialog
      isOpen
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      tone={null}
      eyebrow={`No. ${match.id} · report an early leave`}
      title="Who left early?"
      actions={
        <>
          <Button
            kind="danger-solid"
            onPress={send}
            isDisabled={!who}
            isPending={act.pending === "early_leave.report"}
            pendingLabel="Sending…"
          >
            {chosen ? `Report ${chosen.name}` : "Report"}
          </Button>
          <Button kind="quiet" onPress={onClose} autoFocus>
            Cancel
          </Button>
        </>
      }
    >
      <p>
        If {otherCaptain ?? "the other captain"} agrees, the match is void: no rating change, and the leaver gets a penalty. If
        not, staff decide.
      </p>
      {leftRight(match).map((t) => (
        <RadioCards
          key={t}
          label={nameOf(match, t)}
          value={who}
          onChange={setWho}
          columns="grid-cols-1 sm:grid-cols-2"
          options={teamPlayers(match, t)
            .filter((p) => p.id !== myId)
            .map((p) => ({ id: p.id, title: p.name, tone: teamKey(match, t) }))}
        />
      ))}
      {error ? <InlineAlert title={error} /> : null}
    </Dialog>
  );
}

/** The other captain's answer. */
export function EarlyLeaveAnswerSheet({ match, claim }: { match: MatchSnap; claim: EarlyLeaveClaim }) {
  const act = useMatchAction();
  const answer = (agree: boolean) => {
    act.run("early_leave.answer", { match_id: match.id, agree }).catch(notify.error);
  };
  return (
    <NoticeSheet
      isOpen
      eyebrow="Early leave reported"
      title={`${claim.by_name} says ${claim.leaver_name} left early`}
      deadline={claim.deadline_at}
      tone={match.viewer.team ? teamKey(match, match.viewer.team) : null}
      actions={
        <>
          <Button
            kind="danger-solid"
            onPress={() => answer(true)}
            isPending={act.pending === "early_leave.answer"}
            pendingLabel="Sending…"
          >
            Agree: void the match
          </Button>
          <Button kind="ghost" onPress={() => answer(false)} isDisabled={act.pending !== null}>
            Disagree
          </Button>
        </>
      }
    >
      Agree and the match is void, with no rating change; {claim.leaver_name} gets a penalty. Disagree, or no answer, and staff
      decide.
    </NoticeSheet>
  );
}

/** What everyone else sees while a claim waits for its answer. */
export function EarlyLeaveStatus({ match, myId }: { match: MatchSnap; myId: string | null }) {
  const claim = match.early_leave.pending;
  if (!claim) return null;
  const mine = claim.by_id === myId;
  const answerer = claim.by_id ? match.players.find((p) => p.is_captain && p.id !== claim.by_id)?.name : null;
  return (
    <InlineAlert
      kind="warn"
      title={
        mine
          ? `You reported ${claim.leaver_name} for leaving early`
          : `${claim.by_name} reported ${claim.leaver_name} for leaving early`
      }
    >
      {`Waiting for ${answerer ?? "the other captain"} to agree or disagree. If they agree, the match is void.`}
    </InlineAlert>
  );
}
