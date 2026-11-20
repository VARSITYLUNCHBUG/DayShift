// The lobby (B13, B14, B17): the bot makes a deadlock-api lobby (making, ready, failed); if it
// can't, the host captain makes one in Deadlock and enters its code. The code goes to the 12
// players only. A captain presses Start match once everyone is in the bot's lobby.
import { FieldError, Input, Label, TextField } from "@heroui/react";
import { useState } from "react";
import type { SyntheticEvent } from "react";

import { Button } from "../../components/Button";
import { Countdown } from "../../components/Countdown";
import { Icon } from "../../components/Icon";
import { LobbyCode } from "../../components/LobbyCode";
import { SIDE_NAME } from "../../components/team";
import { TEAM_CLASS } from "../../components/team";
import { errorText, notify } from "../../components/toast";
import { cn } from "../../lib/cn";
import type { MatchSnap } from "../../live/protocol.gen";
import { useMatchAction } from "../../match/live";
import { nameOf, teamKey, teamOfSide } from "../../match/model";
import { Note, StageHead } from "./Parts";
import { Room, useMe } from "./Room";
import type { MatchScreenProps } from "./types";

export const LOBBY_CODE = /^[A-Za-z0-9-]{3,32}$/;

function codeProblem(code: string): string | null {
  const cleaned = code.trim();
  if (!cleaned) return "Enter the lobby code from Deadlock.";
  if (!LOBBY_CODE.test(cleaned)) return "A lobby code is 3 to 32 letters, numbers or dashes.";
  return null;
}

/** `lobby_code`: the bot making its lobby, or the host entering theirs. */
export function LobbyCodeScreen({ match }: MatchScreenProps) {
  const { myId } = useMe(match);
  const isHost = match.host !== null && match.host.id === myId;
  const making = match.lobby.state === "making";
  const hostName = match.host?.name ?? "The host";
  const hostTeam = match.host ? match.players.find((p) => p.id === match.host?.id)?.team : null;
  const tone = hostTeam ? teamKey(match, hostTeam) : null;

  return (
    <Room
      match={match}
      heroes
      acting={!making && hostTeam ? hostTeam : null}
      phaseLine={isHost && !making ? "Lobby · you host" : "Lobby"}
      now={{
        eyebrow: "Draft done",
        title: making ? "Making the lobby" : isHost ? "You host" : `${hostName} hosts`,
        line: making ? "Then the host makes it, if the bot can't" : "Then the other captain is asked",
        tone: making ? null : tone,
        deadline: match.deadline_at,
        announce: isHost && !making ? "to enter the code" : undefined,
      }}
      rail={
        <Note title="Who sees the code">
          Only the {match.players.length} players in this match. Spectators and the Matches page never show it.
        </Note>
      }
    >
      {making ? (
        <>
          <StageHead
            eyebrow="Lobby · Auto Lobby on"
            title="The bot is making your lobby"
            lead="Nothing to do yet. Stay on this page: the code appears here as soon as the lobby is ready."
          />
          <ol aria-label="Lobby steps" className="flex flex-col gap-2">
            <Step n={1} title="Making the lobby" line="Custom lobby, normal mode, bots and cheats off" state="now" />
            <Step n={2} title="Inviting the 12" line="Everyone gets an invite in Deadlock" state="next" />
            <Step
              n={3}
              title="Code ready"
              line={`The code shows here, only for the ${match.players.length} players`}
              state="next"
            />
          </ol>
          <Note title="If it takes too long">{hostName} is asked to make the lobby and enter its code instead.</Note>
        </>
      ) : isHost ? (
        <HostForm match={match} />
      ) : (
        <>
          <StageHead
            eyebrow={match.lobby.state === "failed" ? "Lobby · the bot couldn't make one" : "Lobby"}
            title={`${hostName} is making the lobby`}
            lead={
              match.viewer.is_player
                ? "The code shows here as soon as it's entered. Join it in Deadlock and sit on your team's side."
                : "The code goes to the match's players only."
            }
          />
          {match.lobby_code ? <CodePanel code={match.lobby_code} /> : null}
        </>
      )}
    </Room>
  );
}

function Step({ n, title, line, state }: { n: number; title: string; line: string; state: "done" | "now" | "next" }) {
  return (
    <li
      aria-current={state === "now" ? "step" : undefined}
      className={cn(
        "flex min-h-16 items-center gap-4 rounded-card border bg-surface px-4 py-3",
        state === "now" ? "border-2 border-foreground" : "border-line",
        state === "next" && "text-muted",
      )}
    >
      <span
        aria-hidden="true"
        className={cn(
          "flex size-9 shrink-0 items-center justify-center rounded-full border-2 text-label font-extrabold",
          state === "now"
            ? "border-foreground bg-foreground text-background"
            : state === "done"
              ? "border-ok text-ok"
              : "border-dashed border-line-strong",
        )}
      >
        {state === "done" ? <Icon name="check" size={16} /> : n}
      </span>
      <span className="flex min-w-0 flex-col">
        <b className="text-body font-extrabold">{title}</b>
        <span className="text-caption">{line}</span>
      </span>
      <span className="ml-auto text-caption font-bold">
        {state === "done" ? "Done" : state === "now" ? "Working on it" : "Next"}
      </span>
    </li>
  );
}

function HostForm({ match }: { match: MatchSnap }) {
  const act = useMatchAction();
  const [code, setCode] = useState("");
  const [tried, setTried] = useState(false);
  const [refusal, setRefusal] = useState<string | null>(null);
  const problem = codeProblem(code);
  const hk = teamOfSide(match, "hk");
  const myTeam = match.viewer.team;
  const tone = myTeam ? teamKey(match, myTeam) : null;
  const error = refusal ?? (tried ? problem : null);

  const submit = (event: SyntheticEvent) => {
    event.preventDefault();
    setTried(true);
    setRefusal(null);
    if (problem) return;
    act.run("draft.lobby_code", { match_id: match.id, code: code.trim() }).then(
      () => notify.success("Code shared with the 12"),
      (reason: unknown) => setRefusal(errorText(reason)),
    );
  };

  return (
    <>
      <StageHead
        eyebrow={match.lobby.state === "failed" ? "Lobby · the bot couldn't make one" : "Lobby · Auto Lobby off"}
        title="You host the lobby"
        lead="Make a custom lobby in Deadlock, check the settings below, then enter its code."
      />
      <form
        onSubmit={submit}
        noValidate
        className={cn(
          "flex flex-col gap-3 rounded-panel border-2 bg-surface p-6",
          tone ? TEAM_CLASS[tone].border : "border-line-strong",
        )}
      >
        <div className="flex flex-wrap items-start gap-3">
          <TextField
            value={code}
            onChange={(value) => {
              setCode(value);
              setRefusal(null);
            }}
            isInvalid={error !== null}
            className="min-w-0 flex-1 basis-64"
          >
            <Label className="text-label font-extrabold">Lobby code</Label>
            <Input
              autoComplete="off"
              autoCapitalize="characters"
              spellCheck={false}
              maxLength={32}
              placeholder="K7Q2PX"
              className="h-14 text-lead font-extrabold tracking-code"
            />
            <FieldError>{error}</FieldError>
          </TextField>
          <Button
            type="submit"
            size="lg"
            team={tone}
            isPending={act.pending === "draft.lobby_code"}
            pendingLabel="Sharing…"
            className="mt-6 max-md:mt-0 max-md:w-full"
          >
            Share code with the {match.players.length}
          </Button>
        </div>
      </form>
      <div className="grid gap-4 md:grid-cols-2">
        <section aria-labelledby="settings" className="rounded-panel border border-line bg-surface p-5">
          <h2 id="settings" className="text-card">
            Lobby settings
          </h2>
          <ul className="mt-3 flex flex-col gap-2 text-body">
            {[
              "Normal mode",
              "Bots off",
              "Cheats off",
              "Duplicate heroes off",
              hk ? `${nameOf(match, hk)} on ${SIDE_NAME.hk}'s side` : null,
            ]
              .filter((line): line is string => line !== null)
              .map((line) => (
                <li key={line} className="flex items-center gap-2">
                  <Icon name="check" size={16} />
                  {line}
                </li>
              ))}
          </ul>
        </section>
        <Note title="If you can't host">Run out of time and the other captain is asked to host instead, with a fresh clock.</Note>
      </div>
    </>
  );
}

function CodePanel({ code }: { code: string }) {
  return (
    <section aria-label="Lobby code" className="flex flex-col gap-2 rounded-panel border-2 border-line-strong bg-surface p-6">
      <span className="text-label font-extrabold">Lobby code</span>
      <LobbyCode code={code} />
      <span className="text-caption text-muted">Join it in Deadlock and sit on your team&apos;s side.</span>
    </section>
  );
}

/** `in_progress` with the bot's lobby still open (B14): the code, who's joining, Start match. */
export function BotLobby({ match }: MatchScreenProps) {
  const act = useMatchAction();
  const canStart = match.viewer.is_captain && match.viewer.is_acting;
  const start = () => {
    act.run("draft.api_start", { match_id: match.id }).catch(notify.error);
  };
  const button = match.viewer.is_captain ? (
    <Button
      size="lg"
      onPress={start}
      isDisabled={!canStart}
      isPending={act.pending === "draft.api_start"}
      pendingLabel="Starting…"
    >
      Start match
    </Button>
  ) : null;
  return (
    <Room
      match={match}
      heroes
      phaseLine="Lobby · ready"
      now={{
        eyebrow: "Lobby ready",
        title: canStart ? "Start when everyone's in" : "Join the lobby",
        line: match.lobby.api_leaves_at ? "The bot leaves the lobby when the clock runs out" : undefined,
        deadline: match.lobby.api_leaves_at,
        action: button,
      }}
      footer={button}
      rail={
        <Note title="Who sees the code">
          Only the {match.players.length} players in this match. Spectators and the Matches page never show it.
        </Note>
      }
    >
      <StageHead
        eyebrow="Lobby · made by the bot"
        title="Your lobby is ready"
        lead={
          match.viewer.is_player
            ? "Join with the code and sit on your team's side. A captain presses Start match once all 12 are in."
            : "The players are joining the bot's lobby. The code goes to them only."
        }
      />
      {match.lobby_code ? <CodePanel code={match.lobby_code} /> : null}
      {match.lobby.api_leaves_at ? (
        <p className="text-body text-muted">
          The bot leaves the lobby in <Countdown deadline={match.lobby.api_leaves_at} label="Time until the bot leaves" />. Start
          before then.
        </p>
      ) : null}
    </Room>
  );
}
