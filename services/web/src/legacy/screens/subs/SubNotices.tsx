import { Pause } from "@gravity-ui/icons";
import { Button, Card, Spinner } from "@heroui/react";

import { Countdown } from "../../components/Countdown";
import { notify } from "../../components/toast";
import { teamName } from "../../lib/format";
import { useAction, usePlayerId } from "../../../live/hooks";
import type { MatchSnap, SubEntry } from "../../../live/types";
import { approver, canNameSub, isApprover, sideText } from "./subs";

interface Props {
  match: MatchSnap;
  /** Open the naming dialog for this request. */
  onName: (requestId: string) => void;
}

/** Above every phase while sub requests are in play: 4.3 for the captain who has to approve one,
 * and 4.6 (the match is paused) for everyone else. A ready check that closed short shows its
 * own refill screen instead (2.3). */
export function SubNotices({ match, onName }: Props) {
  const myId = usePlayerId();
  const lines = match.subs.filter((line) => line.reason === "sub_out");
  if (lines.length === 0) return null;
  return (
    <div className="flex flex-col gap-3">
      {lines.map((line) =>
        isApprover(match, line, myId) ? (
          <ApproveCard key={line.id} match={match} line={line} />
        ) : (
          <PausedBanner key={line.id} match={match} line={line} myId={myId} onName={onName} />
        ),
      )}
    </div>
  );
}

/** "Waiting for Orrin", "Waiting for Vesper to approve", … */
function waitingText(match: MatchSnap, line: SubEntry, nameable: boolean): string {
  if (line.status === "approval") {
    const captain = approver(match, line);
    return captain ? `Waiting for ${captain.name} to approve` : "Waiting for the other captain to approve";
  }
  if (line.offer) return `Waiting for ${line.offer.name}`;
  if (line.name_until) {
    if (nameable) return "Name a sub, or the queue is asked";
    return `${line.requested_by_name ?? "Their captain"} is naming a sub`;
  }
  return nameable ? "Nobody in the queue can take it yet. You can still name someone." : "Waiting for someone to join the queue";
}

function PausedBanner({
  match,
  line,
  myId,
  onName,
}: {
  match: MatchSnap;
  line: SubEntry;
  myId: string | null;
  onName: (requestId: string) => void;
}) {
  const action = useAction();
  const nameable = canNameSub(match, line, myId);
  const mine = myId !== null && line.requested_by_id === myId;
  // The approval deadline while waiting on a captain, then when the match is cancelled.
  const deadline = line.status === "open" && line.name_until && !line.offer ? line.name_until : line.deadline_at;
  const cancel = () => {
    action.run("subs.cancel", { request_id: line.id }).catch(notify.error);
  };
  return (
    <section
      aria-label="Paused"
      className="flex flex-wrap items-center gap-x-5 gap-y-3 rounded-2xl border border-warning/40 bg-warning-soft px-5 py-4 text-warning-soft-foreground sm:px-6"
    >
      <Pause width={22} height={22} aria-hidden="true" className="shrink-0 text-warning" />
      <span className="flex min-w-0 flex-1 basis-64 flex-col gap-0.5">
        <span className="text-lg font-bold">{line.leaving_name} is subbing out</span>
        <span className="text-sm opacity-85">{waitingText(match, line, nameable)}</span>
      </span>
      <Countdown deadline={deadline} className="text-2xl font-bold" />
      <div className="flex flex-wrap gap-2">
        {nameable ? (
          <Button onPress={() => onName(line.id)} className="h-11 rounded-xl px-4.5 font-semibold">
            Name a sub
          </Button>
        ) : null}
        {mine ? (
          <Button
            variant="outline"
            onPress={cancel}
            isPending={action.pending}
            className="h-11 rounded-xl border-warning/40 px-4.5 font-semibold text-warning-soft-foreground"
          >
            {({ isPending }) => (
              <>
                {isPending ? <Spinner color="current" size="sm" /> : null}
                Cancel request
              </>
            )}
          </Button>
        ) : null}
      </div>
    </section>
  );
}

/** 4.3 Approve sub out: the other captain says yes or no to a captain subbing out a teammate. */
export function ApproveCard({ match, line }: { match: MatchSnap; line: SubEntry }) {
  const action = useAction();
  const answer = (approve: boolean) => {
    action.run("subs.answer_request", { request_id: line.id, approve }).catch(notify.error);
  };
  const side = line.team ? match.sides[line.team] : null;
  return (
    <Card aria-labelledby={`approve-${line.id}`} className="mx-auto w-full max-w-120 gap-4.5 border border-border p-7">
      <div className="flex items-center justify-between gap-3">
        <span className="text-sm text-muted">Match {match.id} · Sub out</span>
        <Countdown deadline={line.deadline_at} className="text-2xl font-bold" />
      </div>
      <h2 id={`approve-${line.id}`} className="text-2xl leading-snug font-bold">
        {line.requested_by_name ?? "Their captain"} wants to sub out{" "}
        <span className={sideText(side)}>{line.leaving_name}</span>
      </h2>
      {line.team ? <span className="text-sm text-muted">{teamName(match.team_names, line.team)}</span> : null}
      <div className="grid grid-cols-2 gap-2.5">
        <Button
          variant="outline"
          size="lg"
          fullWidth
          isDisabled={action.pending}
          onPress={() => answer(false)}
          className="h-13 rounded-2xl font-bold"
        >
          Refuse
        </Button>
        <Button size="lg" fullWidth isDisabled={action.pending} onPress={() => answer(true)} className="h-13 rounded-2xl font-bold">
          Approve
        </Button>
      </div>
    </Card>
  );
}
