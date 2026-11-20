import { Button, Card, Chip, FieldError, Form, Input, Label, Spinner, TextField } from "@heroui/react";
import { useState } from "react";

import { Countdown } from "../../components/Countdown";
import { MatchShell } from "../../components/MatchShell";
import { useAction, usePlayerId } from "../../../live/hooks";
import type { MatchSnap } from "../../../live/types";
import { Teams } from "./TeamSummary";
import type { MatchScreenProps } from "./types";

/** The custom lobby settings the host sets (the bot's checklist). */
const LOBBY_SETTINGS = ["Normal mode", "Bots off", "Cheats off", "Duplicate heroes off"];

/** 2.10 Enter lobby code: the chosen host makes the lobby and posts its code; everyone else
 * waits for it. */
export function LobbyCode({ match }: MatchScreenProps) {
  const myId = usePlayerId();
  const isHost = match.host !== null && match.host.id === myId;
  return (
    <MatchShell match={match}>
      <div className="flex justify-center">{isHost ? <HostCard match={match} /> : <WaitCard match={match} />}</div>
      <Teams match={match} />
    </MatchShell>
  );
}

function HostCard({ match }: { match: MatchSnap }) {
  const action = useAction();
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const cleaned = code.trim();

  const submit = () => {
    if (!cleaned) return;
    setError(null);
    action.run("draft.lobby_code", { match_id: match.id, code: cleaned }).catch((reason: unknown) => {
      setError(reason instanceof Error ? reason.message : String(reason));
    });
  };

  return (
    <Card aria-labelledby="host" className="w-full max-w-120 gap-4.5 border border-border p-7">
      <div className="flex items-center justify-between gap-3">
        <h1 id="host" className="text-2xl font-bold">
          You host
        </h1>
        <Countdown deadline={match.deadline_at} className="text-2xl font-bold" />
      </div>
      {match.lobby.auto_lobby ? (
        <p className="text-sm text-muted">The bot is creating the lobby. If it can&apos;t, create it yourself and post the code.</p>
      ) : null}
      <ul aria-label="Lobby settings" className="flex flex-wrap gap-1.5">
        {LOBBY_SETTINGS.map((setting) => (
          <li key={setting}>
            <Chip size="md" variant="secondary">
              {setting}
            </Chip>
          </li>
        ))}
      </ul>
      <Form
        className="flex flex-col gap-4.5"
        validationBehavior="aria"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <TextField
          name="code"
          value={code}
          onChange={(value) => {
            setCode(value.toUpperCase());
            setError(null);
          }}
          isInvalid={error !== null}
          fullWidth
        >
          <Label>Lobby code</Label>
          <Input
            variant="secondary"
            autoComplete="off"
            autoCapitalize="characters"
            spellCheck={false}
            maxLength={32}
            className="h-14 text-2xl font-bold tracking-widest"
          />
          <FieldError>{error}</FieldError>
        </TextField>
        <Button
          type="submit"
          size="lg"
          fullWidth
          isDisabled={!cleaned}
          isPending={action.pending}
          className="h-13 rounded-2xl font-bold"
        >
          {({ isPending }) => (
            <>
              {isPending ? <Spinner color="current" size="sm" /> : null}
              Post code
            </>
          )}
        </Button>
      </Form>
    </Card>
  );
}

function WaitCard({ match }: { match: MatchSnap }) {
  const host = match.host?.name ?? "The host";
  const text = match.lobby.auto_lobby
    ? `The bot is creating the lobby. If it can't, ${host} makes it.`
    : `${host} is creating the lobby.`;
  return (
    <Card aria-labelledby="wait" className="w-full max-w-120 gap-3 border border-border p-7">
      <div className="flex items-center justify-between gap-3">
        <h1 id="wait" className="text-2xl font-bold">
          {match.host ? `${match.host.name} hosts` : "Lobby"}
        </h1>
        <Countdown deadline={match.deadline_at} className="text-2xl font-bold" />
      </div>
      <p className="text-base text-foreground/85">{text}</p>
      <div className="flex items-center gap-2 text-sm text-muted">
        <Spinner size="sm" color="current" />
        <span>
          {match.viewer.is_player ? "The code shows here once it's posted." : "Players only: the code goes to the match's players."}
        </span>
      </div>
    </Card>
  );
}
