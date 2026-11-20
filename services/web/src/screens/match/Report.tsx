// Report the result (R01): who won, the Deadlock match ID (required, as on Discord), the
// end-of-match scoreboard screenshot (optional: drop, paste or choose), MVP and key players.
// It goes over HTTP; the new state arrives over the socket.
import { FieldError, Input, Label, TextField } from "@heroui/react";
import { useEffect, useId, useState } from "react";
import type { SyntheticEvent, ReactNode } from "react";
import { DropZone } from "react-aria-components/DropZone";
import { FileTrigger } from "react-aria-components/FileTrigger";
import { ToggleButton } from "react-aria-components/ToggleButton";

import { Button } from "../../components/Button";
import { Icon } from "../../components/Icon";
import { InlineAlert } from "../../components/InlineAlert";
import { Sticker } from "../../components/Sticker";
import { SIDE_NAME, TEAM_CLASS } from "../../components/team";
import { errorText, notify } from "../../components/toast";
import { cn } from "../../lib/cn";
import type { MatchSnap, MatchStatus, Team } from "../../live/protocol.gen";
import { leftRight, nameOf, other, teamKey, teamPlayers } from "../../match/model";
import { matchIdProblem, SCREENSHOT_TYPES, screenshotProblem, useReport } from "../../match/report";
import { StageHead } from "./Parts";

/** The bot's thanks for each outcome (bot/handlers/results.py `process_report`). */
export const REPORT_THANKS: Partial<Record<MatchStatus, string>> = {
  awaiting_confirmation: "Thanks: the other captain can now confirm or dispute.",
  completed: "Thanks: both captains agree, and the result is posted.",
  disputed: "You and the other captain disagree, so staff will decide.",
};

function size(bytes: number): string {
  return bytes >= 1024 * 1024 ? `${(bytes / (1024 * 1024)).toFixed(1)} MB` : `${Math.ceil(bytes / 1024)} KB`;
}

export function ReportForm({ match, myId, onDone }: { match: MatchSnap; myId: string | null; onDone: () => void }) {
  const report = useReport(match.id);
  const ids = useId();
  const [winner, setWinner] = useState<Team | null>(null);
  const [matchId, setMatchId] = useState("");
  const [shot, setShot] = useState<File | null>(null);
  const [shotProblem, setShotProblem] = useState<string | null>(null);
  const [mvp, setMvp] = useState<string | null>(null);
  const [keys, setKeys] = useState<string[]>([]);
  const [tried, setTried] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const team = match.viewer.team;
  const otherCaptain = team ? match.captains[other(team)] : null;
  const idProblem = matchIdProblem(matchId);

  const pick = (file: File) => {
    setShot(file);
    setShotProblem(screenshotProblem(file));
    setError(null);
  };

  // Paste a screenshot anywhere on the page while the form is open.
  useEffect(() => {
    const paste = (event: ClipboardEvent) => {
      const file = [...(event.clipboardData?.files ?? [])].find((f) => SCREENSHOT_TYPES.includes(f.type));
      if (file) {
        event.preventDefault();
        setShot(file);
        setShotProblem(screenshotProblem(file));
      }
    };
    document.addEventListener("paste", paste);
    return () => document.removeEventListener("paste", paste);
  }, []);

  const toggleKey = (id: string, on: boolean) => {
    setKeys((current) => (on ? [...current.filter((k) => k !== id).slice(-1), id] : current.filter((k) => k !== id)));
  };

  const submit = (event: SyntheticEvent) => {
    event.preventDefault();
    setTried(true);
    if (!winner || idProblem || shotProblem) return;
    setError(null);
    report.mutate(
      { winner, deadlockMatchId: matchId, screenshot: shot, mvp, keys },
      {
        onSuccess: (done) => {
          notify.success(REPORT_THANKS[done.status] ?? "Thanks: result received.");
          onDone();
        },
        onError: (reason) => setError(errorText(reason)),
      },
    );
  };

  const roster = leftRight(match).flatMap((t) => teamPlayers(match, t));
  const tone = winner ? teamKey(match, winner) : null;

  return (
    <form onSubmit={submit} noValidate className="flex max-w-215 flex-col gap-7">
      <StageHead
        eyebrow={`Report the result${team && match.viewer.is_captain ? ` · you captain ${nameOf(match, team)}` : ""}`}
        title={`Who won No. ${match.id}?`}
        lead={`Pick the winner and enter the Deadlock match ID. ${otherCaptain ?? "The other captain"} confirms it, then the postgame opens for everyone.`}
      />

      <div role="group" aria-labelledby={`${ids}-winner`} className="flex flex-col gap-2.5">
        <span id={`${ids}-winner`} className="text-label font-extrabold">
          Winner
        </span>
        <div className="grid gap-3 sm:grid-cols-2">
          {leftRight(match).map((t, index) => {
            const key = teamKey(match, t);
            const side = match.sides[t];
            const selected = winner === t;
            return (
              <ToggleButton
                key={t}
                isSelected={selected}
                onChange={() => setWinner(t)}
                // The form replaces the page's stage: focus lands on its first question.
                autoFocus={index === 0}
                aria-label={`${nameOf(match, t)} won`}
                className={cn(
                  "relative flex min-h-32 cursor-pointer flex-col items-start gap-2 rounded-panel border-3 p-6 text-left outline-none transition-state",
                  selected
                    ? cn(TEAM_CLASS[key].border, TEAM_CLASS[key].soft, "shadow-lift")
                    : cn(TEAM_CLASS[key].softBorder, "bg-surface"),
                )}
              >
                {selected ? (
                  <span className="absolute top-3 right-3">
                    <Sticker tone={key} size="sm" tilt="right">
                      Chosen
                    </Sticker>
                  </span>
                ) : null}
                {side ? <span className={cn("text-label font-bold", TEAM_CLASS[key].text)}>{SIDE_NAME[side]}</span> : null}
                <span className={cn("font-display text-coin", TEAM_CLASS[key].text)}>{nameOf(match, t)} won</span>
                <span className="text-caption text-muted">
                  Captain {match.captains[t] ?? "?"}
                  {t === team ? " · you" : ""}
                </span>
              </ToggleButton>
            );
          })}
        </div>
        {tried && !winner ? <span className="text-caption font-semibold text-danger">Choose the winning team.</span> : null}
      </div>

      <TextField value={matchId} onChange={setMatchId} isRequired isInvalid={tried && idProblem !== null} className="max-w-110">
        <Label className="text-label font-extrabold">Deadlock match ID</Label>
        <Input inputMode="numeric" autoComplete="off" maxLength={18} placeholder="41207733" className="h-12" />
        <span className="text-caption text-muted">
          In Deadlock: Esc, Match history, copy the number. With it, the postgame gets the timeline, the replay and every number.
        </span>
        <FieldError>{tried ? idProblem : null}</FieldError>
      </TextField>

      <div className="flex flex-col gap-2.5">
        <span id={`${ids}-shot`} className="text-label font-extrabold">
          Scoreboard screenshot <span className="font-semibold text-muted">(optional)</span>
        </span>
        <DropZone
          aria-labelledby={`${ids}-shot`}
          getDropOperation={(types) => (SCREENSHOT_TYPES.some((type) => types.has(type)) ? "copy" : "cancel")}
          onDrop={async (event) => {
            const item = event.items.find((i) => i.kind === "file");
            if (item?.kind === "file") pick(await item.getFile());
          }}
          className={({ isDropTarget }) =>
            cn(
              "flex flex-wrap items-center gap-4 rounded-card border-2 border-dashed px-5 py-4 outline-none",
              isDropTarget
                ? "border-foreground bg-raised"
                : shotProblem
                  ? "border-danger"
                  : shot
                    ? "border-ok"
                    : "border-line-strong",
            )
          }
        >
          <span className={shot && !shotProblem ? "text-ok" : "text-muted"}>
            <Icon name={shot && !shotProblem ? "check" : "upload"} />
          </span>
          <span className="flex min-w-0 flex-1 flex-col gap-0.5">
            <b className="truncate text-body">{shot ? shot.name : "Drop the end-of-match scoreboard screenshot"}</b>
            <span className={cn("text-caption", shotProblem ? "font-semibold text-danger" : "text-muted")}>
              {shotProblem ??
                (shot ? size(shot.size) : "PNG, JPEG or WebP, up to 20 MB. Or paste it: Tab in the game, then Print Screen.")}
            </span>
          </span>
          <FileTrigger acceptedFileTypes={SCREENSHOT_TYPES} onSelect={(files) => (files?.[0] ? pick(files[0]) : undefined)}>
            <Button kind="ghost" size="sm">
              {shot ? "Replace" : "Choose a file"}
            </Button>
          </FileTrigger>
          {shot ? (
            <Button
              kind="quiet"
              size="sm"
              onPress={() => {
                setShot(null);
                setShotProblem(null);
              }}
            >
              Remove
            </Button>
          ) : null}
        </DropZone>
      </div>

      <PlayerChips
        label={
          <>
            MVP <span className="font-semibold text-muted">(optional)</span>
          </>
        }
        match={match}
        players={roster}
        isOn={(id) => mvp === id}
        onChange={(id, on) => {
          setMvp(on ? id : null);
          if (on) setKeys((current) => current.filter((k) => k !== id));
        }}
        myId={myId}
      />
      <PlayerChips
        label={
          <>
            Key players <span className="font-semibold text-muted">(up to 2, optional)</span>
          </>
        }
        match={match}
        players={roster}
        isOn={(id) => keys.includes(id)}
        isDisabled={(id) => id === mvp}
        onChange={toggleKey}
        myId={myId}
      />

      {error ? <InlineAlert title={error} /> : null}
      <div className="flex flex-wrap items-center gap-3 border-t border-line pt-6">
        <Button type="submit" size="lg" team={tone} isPending={report.isPending} pendingLabel="Sending…">
          {winner ? `Send: ${nameOf(match, winner)} won` : "Send the result"}
        </Button>
        <Button kind="quiet" onPress={onDone}>
          Back
        </Button>
        <span className="text-caption text-muted">{otherCaptain ?? "The other captain"} confirms or disputes it next.</span>
      </div>
    </form>
  );
}

function PlayerChips({
  label,
  match,
  players,
  isOn,
  isDisabled,
  onChange,
  myId,
}: {
  label: ReactNode;
  match: MatchSnap;
  players: MatchSnap["players"];
  isOn: (id: string) => boolean;
  isDisabled?: (id: string) => boolean;
  onChange: (id: string, on: boolean) => void;
  myId: string | null;
}) {
  const id = useId();
  return (
    <div role="group" aria-labelledby={id} className="flex flex-col gap-2.5">
      <span id={id} className="text-label font-extrabold">
        {label}
      </span>
      <div className="flex flex-wrap gap-1.5">
        {players.map((p) => {
          const on = isOn(p.id);
          const key = p.team ? teamKey(match, p.team) : null;
          return (
            <ToggleButton
              key={p.id}
              isSelected={on}
              isDisabled={isDisabled?.(p.id)}
              onChange={(next) => onChange(p.id, next)}
              className={cn(
                "inline-flex h-11 cursor-pointer items-center rounded-full border-2 px-4 text-label font-bold outline-none transition-state disabled:cursor-not-allowed disabled:opacity-50",
                on ? (key ? cn(TEAM_CLASS[key].border, TEAM_CLASS[key].soft) : "border-foreground bg-raised") : "border-line",
              )}
            >
              {p.name}
              {p.id === myId ? <span className="ml-1 text-micro text-muted">you</span> : null}
            </ToggleButton>
          );
        })}
      </div>
    </div>
  );
}
