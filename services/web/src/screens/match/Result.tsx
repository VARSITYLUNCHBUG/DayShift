// After the game: confirm or dispute (R02, R03), the scoreboard's names (R04), under review
// (R05), cancelled (R06) and the final result, which links to the postgame (FE-PAGES' screens).
import { Label, ListBox, Select, TextArea, TextField } from "@heroui/react";
import type { Key } from "@heroui/react";
import { useState } from "react";

import { Button, ButtonLink } from "../../components/Button";
import { Countdown } from "../../components/Countdown";
import { Dialog } from "../../components/Dialog";
import { InlineAlert } from "../../components/InlineAlert";
import { Portrait } from "../../components/Portrait";
import { TEAM_CLASS } from "../../components/team";
import { errorText, notify } from "../../components/toast";
import { cn } from "../../lib/cn";
import { clockTime, signed } from "../../lib/format";
import type { MatchSnap, Scoreboard, ScoreboardRow, Team } from "../../live/protocol.gen";
import { useMatchAction } from "../../match/live";
import { leftRight, nameOf, teamKey, teamPlayers } from "../../match/model";
import { Note, StageHead } from "./Parts";
import { Room, useMe } from "./Room";
import type { MatchScreenProps } from "./types";

function reported(match: MatchSnap): Team | null {
  return match.result.reported_winner;
}

// --- Awaiting confirmation ---------------------------------------------------------------------

export function AwaitingConfirmation({ match }: MatchScreenProps) {
  const { myId } = useMe(match);
  const act = useMatchAction();
  const [disputing, setDisputing] = useState(false);
  const winner = reported(match);
  const by = match.result.reported_by_name ?? "A captain";
  const answered = match.result.responses.some((r) => r.player_id === myId);
  const canAnswer = match.viewer.is_captain && !answered;
  const tone = match.viewer.team ? teamKey(match, match.viewer.team) : null;
  const winnerTone = winner ? teamKey(match, winner) : null;
  const confirm = () => {
    act.run("results.confirm", { match_id: match.id }).then(() => notify.success("Result confirmed"), notify.error);
  };
  const buttons = canAnswer ? (
    <>
      <Button size="lg" team={tone} onPress={confirm} isPending={act.pending === "results.confirm"} pendingLabel="Confirming…">
        Confirm
      </Button>
      <Button size="lg" kind="danger" onPress={() => setDisputing(true)} isDisabled={act.pending !== null}>
        Dispute
      </Button>
    </>
  ) : null;
  const deadline = match.deadline_at;

  return (
    <Room
      match={match}
      heroes
      phaseLine={canAnswer ? "Result · confirm" : "Result"}
      now={{
        eyebrow: winner ? `${by} reported ${nameOf(match, winner)} won` : "Result reported",
        title: canAnswer ? "for you to confirm or dispute" : "Waiting for the other captain",
        tone: canAnswer ? tone : null,
        deadline,
        announce: canAnswer ? "to confirm or dispute" : undefined,
      }}
      footer={buttons}
      rail={<ScoreNamesPanel match={match} />}
    >
      <StageHead
        eyebrow={`${by} reported`}
        title={winner ? `${nameOf(match, winner)} won` : "A result is in"}
        lead={
          canAnswer
            ? "Confirm if it's right; dispute if it isn't and tell staff why."
            : `The other captain confirms or disputes it.${deadline ? ` No answer by ${clockTime(deadline)} and ${by}'s report stands.` : ""}`
        }
        tone={winnerTone ? TEAM_CLASS[winnerTone].text : undefined}
        action={buttons}
      />
      {canAnswer && deadline ? (
        <p className="text-caption text-muted">
          No answer by {clockTime(deadline)} and {by}&apos;s report stands.{" "}
          <Countdown deadline={deadline} label="Time to answer" /> left.
        </p>
      ) : null}
      <Responses match={match} />
      {disputing ? <DisputeDialog match={match} onClose={() => setDisputing(false)} /> : null}
    </Room>
  );
}

function Responses({ match }: { match: MatchSnap }) {
  if (match.result.responses.length === 0) return null;
  const verdict = { report: "reported", confirm: "confirmed", dispute: "disputed" } as const;
  return (
    <section aria-label="Answers" className="flex flex-col gap-2">
      <h2 className="text-card">Answers</h2>
      <ul className="flex flex-col gap-1.5">
        {match.result.responses.map((r) => (
          <li key={`${r.player_id}-${r.verdict}`} className="text-body">
            <b>{r.name}</b> {verdict[r.verdict]}
            {r.winner ? ` ${nameOf(match, r.winner)} won` : ""}
          </li>
        ))}
      </ul>
    </section>
  );
}

function DisputeDialog({ match, onClose }: { match: MatchSnap; onClose: () => void }) {
  const act = useMatchAction();
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const send = () => {
    setError(null);
    act.run("results.dispute", { match_id: match.id, note: note.trim() }).then(
      () => {
        notify.info("Disputed", "Staff will review the result.");
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
      eyebrow={`No. ${match.id} · dispute`}
      title="Dispute the result?"
      actions={
        <>
          <Button kind="danger-solid" onPress={send} isPending={act.pending === "results.dispute"} pendingLabel="Sending…">
            Dispute
          </Button>
          <Button kind="quiet" onPress={onClose} autoFocus>
            Go back
          </Button>
        </>
      }
    >
      <p>Staff look at the screenshot and the match ID, then decide. Ratings wait until they do.</p>
      <TextField value={note} onChange={setNote} className="flex flex-col gap-1.5">
        <Label className="text-label font-extrabold text-foreground">What&apos;s wrong? (optional)</Label>
        <TextArea rows={3} maxLength={500} placeholder="We won 41 to 27: the report has the wrong team." />
      </TextField>
      {error ? <InlineAlert title={error} /> : null}
    </Dialog>
  );
}

// --- Scoreboard names (R04) --------------------------------------------------------------------

function ScoreNamesPanel({ match }: { match: MatchSnap }) {
  if (!match.scoreboard || !match.viewer.is_captain) return null;
  return <ScoreNames match={match} scoreboard={match.scoreboard} />;
}

/** The scoreboard's in-game names nobody has matched to a player yet: a captain matches each one,
 * so the reader's numbers reach the right players. */
export function ScoreNames({ match, scoreboard }: { match: MatchSnap; scoreboard: Scoreboard }) {
  const act = useMatchAction();
  const [error, setError] = useState<string | null>(null);
  const map = (row: ScoreboardRow, key: Key | null) => {
    if (key === null) return;
    setError(null);
    act
      .run("ocr.map_row", { read_id: scoreboard.read_id, row: row.row, player_id: String(key) })
      .catch((reason: unknown) => setError(errorText(reason)));
  };
  return (
    <section aria-labelledby="score-names" className="flex flex-col gap-3 rounded-panel border border-line bg-surface p-5">
      <div className="flex items-baseline justify-between gap-2">
        <h2 id="score-names" className="text-card">
          Match the scoreboard names
        </h2>
        <span className="text-caption font-bold">{scoreboard.rows.length} left</span>
      </div>
      <p className="text-caption text-muted">
        These names on the scoreboard don&apos;t match a player yet. Choose who each one is.
      </p>
      <ul className="flex flex-col gap-2.5">
        {scoreboard.rows.map((row) => {
          const key = teamKey(match, row.team);
          const options = scoreboard.players.filter((p) => p.team === row.team);
          const hero = row.hero?.name ?? row.hero_name;
          return (
            <li key={row.row} className="flex flex-wrap items-center gap-3">
              <Portrait hero={hero || row.name} src={row.hero?.icon_url} team={key} />
              <span className="flex min-w-32 flex-1 flex-col">
                <b className="text-body break-all">{row.name || "?"}</b>
                <span className="text-caption text-muted">{[hero, nameOf(match, row.team)].filter(Boolean).join(" · ")}</span>
              </span>
              <Select
                placeholder="Who is it?"
                onChange={(k) => map(row, k)}
                className="min-w-44"
                isDisabled={act.pending !== null}
              >
                <Label className="sr-only">Player for {row.name || "this name"}</Label>
                <Select.Trigger className="h-11">
                  <Select.Value />
                  <Select.Indicator />
                </Select.Trigger>
                <Select.Popover>
                  <ListBox>
                    {options.map((p) => (
                      <ListBox.Item key={p.id} id={p.id} textValue={p.name}>
                        {p.name}
                        <ListBox.ItemIndicator />
                      </ListBox.Item>
                    ))}
                  </ListBox>
                </Select.Popover>
              </Select>
            </li>
          );
        })}
      </ul>
      {error ? <InlineAlert title={error} /> : null}
    </section>
  );
}

// --- Disputed (R05) ----------------------------------------------------------------------------

export function Disputed({ match }: MatchScreenProps) {
  return (
    <Room
      match={match}
      heroes
      now={{ eyebrow: "Under review", title: "Staff will decide", line: "Ratings wait until they do" }}
      rail={<ScoreNamesPanel match={match} />}
    >
      <StageHead
        eyebrow="Result under review"
        title="The captains disagree"
        lead="Staff look at the report, the screenshot and the Deadlock match ID, then decide. Nothing for you to do; you'll see the result here."
      />
      <Responses match={match} />
    </Room>
  );
}

// --- Completed ---------------------------------------------------------------------------------

export function Completed({ match }: MatchScreenProps) {
  const { myId } = useMe(match);
  const winner = match.result.winner;
  const tone = winner ? teamKey(match, winner) : null;
  const mine = myId ? match.result.deltas[myId] : undefined;
  const myTeam = match.viewer.is_player ? match.viewer.team : null;
  return (
    <Room
      match={match}
      heroes
      now={{ eyebrow: `No. ${match.id} is over`, title: winner ? `${nameOf(match, winner)} won` : "Final", tone }}
    >
      <StageHead
        eyebrow="Final"
        title={winner ? `${nameOf(match, winner)} won` : "Match over"}
        lead={
          myTeam && winner
            ? `${myTeam === winner ? "You won." : "You lost."}${mine !== undefined ? ` ${match.rating_label} ${signed(mine)}.` : ""}`
            : undefined
        }
        tone={tone ? TEAM_CLASS[tone].text : undefined}
      />
      <div className="flex flex-wrap gap-2.5">
        <ButtonLink to={`/matches/${match.id}/timeline`} icon="timeline">
          Postgame: timeline
        </ButtonLink>
        <ButtonLink to={`/matches/${match.id}/replay`} kind="ghost" icon="replay">
          Replay
        </ButtonLink>
        <ButtonLink to={`/matches/${match.id}/advanced`} kind="ghost" icon="stats">
          Advanced
        </ButtonLink>
      </div>
      <div className="flex flex-wrap gap-4">
        {leftRight(match).map((team) => (
          <FinalTeam key={team} match={match} team={team} myId={myId} />
        ))}
      </div>
      <ButtonLink to="/" kind="quiet" className="self-start">
        Back to Play
      </ButtonLink>
    </Room>
  );
}

function FinalTeam({ match, team, myId }: { match: MatchSnap; team: Team; myId: string | null }) {
  const key = teamKey(match, team);
  const won = match.result.winner === team;
  return (
    <section
      aria-label={nameOf(match, team)}
      className={cn("flex min-w-0 flex-1 basis-75 flex-col gap-2 rounded-panel border-2 p-4", TEAM_CLASS[key].softBorder)}
    >
      <div className="flex items-baseline justify-between gap-2">
        <h2 className={cn("text-section", TEAM_CLASS[key].text)}>{nameOf(match, team)}</h2>
        <span className="text-caption font-extrabold">{won ? "Won" : "Lost"}</span>
      </div>
      <ul className="flex flex-col">
        {teamPlayers(match, team).map((p) => {
          const delta = match.result.deltas[p.id];
          return (
            <li
              key={p.id}
              className={cn(
                "flex min-h-11 items-center justify-between gap-2 rounded-row px-2",
                p.id === myId && TEAM_CLASS[key].soft,
              )}
            >
              <span className="truncate font-bold">
                {p.name}
                {p.id === myId ? <span className="ml-1.5 text-micro font-semibold text-muted">you</span> : null}
              </span>
              {delta !== undefined ? <span className="text-label font-extrabold tabular-nums">{signed(delta)}</span> : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

// --- Cancelled (R06) ---------------------------------------------------------------------------

export function Cancelled({ match }: MatchScreenProps) {
  const reason = match.result.void_reason;
  return (
    <Room match={match} now={{ eyebrow: `No. ${match.id}`, title: "Cancelled", line: "No rating change" }}>
      <StageHead
        eyebrow="Match cancelled"
        title="This match didn't happen"
        lead={reason ?? "It was cancelled, so nobody's rating changes."}
      />
      <Note title="What now">
        {match.viewer.is_player ? "Head back to Play to queue for the next one." : "Nothing more happens here."}
      </Note>
      <ButtonLink to="/" className="self-start">
        Back to Play
      </ButtonLink>
    </Room>
  );
}
