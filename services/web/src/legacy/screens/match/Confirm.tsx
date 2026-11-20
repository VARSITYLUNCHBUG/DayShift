import { Button, Card, Label, Spinner, TextArea, TextField } from "@heroui/react";
import { useState } from "react";

import { ActionDialog } from "../../components/ActionDialog";
import { Countdown } from "../../components/Countdown";
import { MatchShell } from "../../components/MatchShell";
import { notify } from "../../components/toast";
import { teamName } from "../../lib/format";
import { useAction, usePlayerId } from "../../../live/hooks";
import type { MatchSnap, Side, Team } from "../../../live/types";
import { ReportDialog } from "./ReportDialog";
import { ScoreNames } from "./ScoreNames";
import { Teams } from "./TeamSummary";
import type { MatchScreenProps } from "./types";

/** As the Discord modal allows. */
export const NOTE_LIMIT = 500;

const CLAIM_TONE: Record<Side, string> = {
  hk: "border-team-hk/40 bg-team-hk-soft text-team-hk-soft-foreground",
  am: "border-team-am/40 bg-team-am-soft text-team-am-soft-foreground",
};

/** `awaiting_confirmation`: the other captain confirms or disputes (3.3, 3.4); everyone else
 * waits for them, with the timer after which silence confirms. */
export function AwaitingConfirmation({ match }: MatchScreenProps) {
  const myId = usePlayerId();
  const answered = match.result.responses.some((r) => r.player_id === myId);
  return (
    <MatchShell match={match}>
      <div className="flex flex-wrap items-start justify-center gap-5">
        {match.viewer.is_captain && !answered ? <ConfirmCard match={match} /> : <WaitingCard match={match} />}
        {match.scoreboard ? <ScoreNames match={match} scoreboard={match.scoreboard} /> : null}
      </div>
      <Teams match={match} />
    </MatchShell>
  );
}

/** The captain the match waits on: the one who hasn't answered. */
function awaitedCaptain(match: MatchSnap): string | null {
  const answered = new Set(match.result.responses.map((r) => r.player_id));
  return match.players.find((p) => p.is_captain && !answered.has(p.id))?.name ?? null;
}

function claimText(match: MatchSnap, winner: Team | null): string {
  return winner ? `${teamName(match.team_names, winner)} won` : "No winner given";
}

/** "Rook reported / Rook's Team won", in the claimed winner's colours. */
function Claim({ match }: { match: MatchSnap }) {
  const winner = match.result.reported_winner;
  const side = winner ? match.sides[winner] : null;
  return (
    <div className={`flex flex-col gap-1 rounded-2xl border p-4.5 ${side ? CLAIM_TONE[side] : "border-border bg-background"}`}>
      <span className="text-sm opacity-85">{match.result.reported_by_name ?? "A captain"} reported</span>
      <span className="text-xl font-bold">{claimText(match, winner)}</span>
    </div>
  );
}

function ConfirmCard({ match }: { match: MatchSnap }) {
  const action = useAction();
  const [disputing, setDisputing] = useState(false);
  const [reporting, setReporting] = useState(false);

  const confirm = () => {
    action.run("results.confirm", { match_id: match.id }).catch(notify.error);
  };

  return (
    <Card aria-labelledby={`confirm-${match.id}`} className="w-full max-w-120 gap-4.5 border border-border p-7">
      <div className="flex items-center justify-between gap-3">
        <h1 id={`confirm-${match.id}`} className="text-2xl font-bold">
          Confirm result
        </h1>
        <span className="text-sm text-muted tabular-nums">
          Auto <Countdown deadline={match.deadline_at} />
        </span>
      </div>
      <Claim match={match} />
      <p className="text-sm text-muted">Silence confirms when the timer runs out.</p>
      <div className="grid grid-cols-2 gap-2.5">
        <Button variant="danger-soft" size="lg" fullWidth onPress={() => setDisputing(true)} className="h-13 rounded-2xl font-bold">
          Dispute
        </Button>
        <Button
          size="lg"
          fullWidth
          onPress={confirm}
          isPending={action.pending}
          className="h-13 rounded-2xl bg-success font-bold text-success-foreground hover:bg-success-hover"
        >
          {({ isPending }) => (
            <>
              {isPending ? <Spinner color="current" size="sm" /> : null}
              Confirm
            </>
          )}
        </Button>
      </div>
      <Button variant="secondary" fullWidth onPress={() => setReporting(true)} className="h-11 rounded-xl">
        Add a screenshot
      </Button>

      <DisputeDialog match={match} isOpen={disputing} onOpenChange={setDisputing} />
      <ReportDialog match={match} isOpen={reporting} onOpenChange={setReporting} />
    </Card>
  );
}

/** 3.4 Dispute note: optional, as on Discord. Staff see it; the other captain doesn't. */
export function DisputeDialog({
  match,
  isOpen,
  onOpenChange,
}: {
  match: MatchSnap;
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const action = useAction();
  const [note, setNote] = useState("");
  return (
    <ActionDialog
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      title="Dispute result"
      tone="danger"
      cancelLabel="Back"
      confirmLabel="Dispute"
      onConfirm={() => action.run("results.dispute", { match_id: match.id, note: note.trim() }).then(() => setNote(""))}
    >
      <p className="text-sm">
        {match.result.reported_by_name ?? "A captain"} reported{" "}
        <b className="font-semibold">{claimText(match, match.result.reported_winner)}</b>. Staff will decide, and ratings
        won&apos;t change until they do.
      </p>
      <TextField name="note" value={note} onChange={setNote} fullWidth>
        <Label>What happened?</Label>
        <TextArea rows={5} maxLength={NOTE_LIMIT} variant="secondary" className="resize-none" />
      </TextField>
      <span className="text-right text-xs text-muted tabular-nums">
        {note.length} / {NOTE_LIMIT}
      </span>
    </ActionDialog>
  );
}

function WaitingCard({ match }: { match: MatchSnap }) {
  const captain = awaitedCaptain(match);
  return (
    <Card aria-labelledby={`waiting-${match.id}`} className="w-full max-w-120 gap-4.5 border border-border p-7">
      <div className="flex items-center justify-between gap-3">
        <h1 id={`waiting-${match.id}`} className="text-2xl font-bold">
          {captain ? `Waiting for ${captain} to confirm` : "Waiting for the other captain"}
        </h1>
        <Countdown deadline={match.deadline_at} className="text-2xl font-bold" />
      </div>
      <Claim match={match} />
      <p className="text-sm text-muted">Silence confirms when the timer runs out.</p>
    </Card>
  );
}
