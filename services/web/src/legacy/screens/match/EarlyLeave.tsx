import { Alert, Button, Card, Chip, Modal, Spinner, ToggleButton } from "@heroui/react";
import { useState } from "react";

import { Countdown } from "../../components/Countdown";
import { errorText, notify } from "../../components/toast";
import { byName, teamName } from "../../lib/format";
import { useAction, usePlayerId } from "../../../live/hooks";
import type { MatchSnap, Team } from "../../../live/types";
import { otherCaptainName, sideText } from "../subs/subs";

interface DialogProps {
  match: MatchSnap;
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
}

/** 4.7 Report an early leave (captain): who left in the game's first minutes. The other captain
 * confirms, and the match is voided with no rating change. */
export function EarlyLeaveDialog({ match, isOpen, onOpenChange }: DialogProps) {
  return (
    <Modal.Backdrop isOpen={isOpen} onOpenChange={onOpenChange}>
      <Modal.Container size="md" scroll="inside">
        <Modal.Dialog>
          {({ close }) => (
            <>
              <Modal.CloseTrigger aria-label="Close" />
              <Modal.Header>
                <Modal.Heading className="text-2xl font-bold">
                  Who left in the first {match.early_leave.minutes} min?
                </Modal.Heading>
              </Modal.Header>
              <Modal.Body>
                <ReportForm match={match} onDone={close} />
              </Modal.Body>
            </>
          )}
        </Modal.Dialog>
      </Modal.Container>
    </Modal.Backdrop>
  );
}

function ReportForm({ match, onDone }: { match: MatchSnap; onDone: () => void }) {
  const action = useAction();
  const [leaver, setLeaver] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const chosen = match.players.find((p) => p.id === leaver) ?? null;
  const other = otherCaptainName(match, match.viewer.team);

  const report = () => {
    if (!chosen) return;
    setError(null);
    action.run("early_leave.report", { match_id: match.id, player_id: chosen.id }).then(
      () => {
        notify.success("Early leave reported", other ? `Waiting for ${other} to agree` : undefined);
        onDone();
      },
      (reason: unknown) => setError(errorText(reason)),
    );
  };

  return (
    <div className="flex flex-col gap-4.5">
      <div className="grid grid-cols-2 gap-4">
        {(["A", "B"] as const).map((team) => (
          <TeamColumn key={team} match={match} team={team} chosen={leaver} onChoose={setLeaver} />
        ))}
      </div>
      <span className="text-sm text-muted">{other ? `${other} confirms` : "The other captain confirms"} · voids the match</span>
      {error ? (
        <Alert status="danger">
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Title>{error}</Alert.Title>
          </Alert.Content>
        </Alert>
      ) : null}
      <Button
        variant="danger"
        size="lg"
        fullWidth
        isDisabled={!chosen}
        isPending={action.pending}
        onPress={report}
        className="h-13 rounded-2xl text-base font-bold"
      >
        {({ isPending }) => (
          <>
            {isPending ? <Spinner color="current" size="sm" /> : null}
            {chosen ? `Report ${chosen.name}` : "Report"}
          </>
        )}
      </Button>
    </div>
  );
}

function TeamColumn({
  match,
  team,
  chosen,
  onChoose,
}: {
  match: MatchSnap;
  team: Team;
  chosen: string | null;
  onChoose: (id: string) => void;
}) {
  const players = match.players.filter((p) => p.team === team).sort(byName);
  const id = `leave-team-${team}`;
  return (
    <div role="group" aria-labelledby={id} className="flex min-w-0 flex-col gap-1.5">
      <span id={id} className={`text-sm font-semibold ${sideText(match.sides[team])}`}>
        {teamName(match.team_names, team)}
      </span>
      {players.map((player) => {
        const on = chosen === player.id;
        return (
          <ToggleButton
            key={player.id}
            isSelected={on}
            onChange={() => onChoose(player.id)}
            className={`h-11 w-full rounded-xl border px-2 text-sm ${
              on ? "border-2 border-danger bg-danger-soft font-semibold text-danger-soft-foreground" : "border-border bg-background font-medium"
            }`}
          >
            <span className="truncate">{player.name}</span>
          </ToggleButton>
        );
      })}
    </div>
  );
}

/** A reported early leave, while it waits: 4.8 for the captain who answers, a notice for
 * everyone else. */
export function EarlyLeaveNotice({ match }: { match: MatchSnap }) {
  const myId = usePlayerId();
  const claim = match.early_leave.pending;
  if (!claim) return null;
  const leaver = match.players.find((p) => p.id === claim.leaver_id);
  const side = leaver?.team ? match.sides[leaver.team] : null;
  if (match.viewer.is_captain && myId !== null && claim.by_id !== myId) {
    return <AnswerCard match={match} />;
  }
  const answering = match.players.find((p) => p.is_captain && p.id !== claim.by_id)?.name ?? "the other captain";
  return (
    <section
      aria-label="Early leave"
      className="flex flex-wrap items-center gap-x-5 gap-y-2 rounded-2xl border border-danger/40 bg-danger-soft px-5 py-4 text-danger-soft-foreground sm:px-6"
    >
      <span className="flex min-w-0 flex-1 basis-64 flex-col gap-0.5">
        <span className="text-lg font-bold">
          {claim.by_name} says <span className={sideText(side)}>{claim.leaver_name}</span> left
        </span>
        <span className="text-sm opacity-85">Waiting for {answering}</span>
      </span>
      <Countdown deadline={claim.deadline_at} className="text-2xl font-bold" />
    </section>
  );
}

function AnswerCard({ match }: { match: MatchSnap }) {
  const action = useAction();
  const claim = match.early_leave.pending;
  if (!claim) return null;
  const leaver = match.players.find((p) => p.id === claim.leaver_id);
  const side = leaver?.team ? match.sides[leaver.team] : null;
  const answer = (agree: boolean) => {
    action.run("early_leave.answer", { match_id: match.id, agree }).catch(notify.error);
  };
  return (
    <Card aria-labelledby={`early-${match.id}`} className="mx-auto w-full max-w-120 gap-4.5 border border-border p-7">
      <div className="flex items-center justify-between gap-3">
        <Chip color="danger" variant="soft" size="sm" className="font-bold">
          Early leave
        </Chip>
        <Countdown deadline={claim.deadline_at} className="text-2xl font-bold" />
      </div>
      <h2 id={`early-${match.id}`} className="text-2xl leading-snug font-bold">
        {claim.by_name} says <span className={sideText(side)}>{claim.leaver_name}</span> left
      </h2>
      <span className="text-sm text-muted">Agree to void with no rating change.</span>
      <div className="grid grid-cols-2 gap-2.5">
        <Button
          variant="outline"
          size="lg"
          fullWidth
          isDisabled={action.pending}
          onPress={() => answer(false)}
          className="h-13 rounded-2xl font-bold"
        >
          Disagree
        </Button>
        <Button size="lg" fullWidth isDisabled={action.pending} onPress={() => answer(true)} className="h-13 rounded-2xl font-bold">
          Agree
        </Button>
      </div>
    </Card>
  );
}
