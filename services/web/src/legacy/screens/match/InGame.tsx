import { Copy } from "@gravity-ui/icons";
import { Alert, Button, Card, Chip, Spinner } from "@heroui/react";
import { useState } from "react";

import { Countdown } from "../../components/Countdown";
import { MatchShell } from "../../components/MatchShell";
import { notify } from "../../components/toast";
import { useAction, useElapsed } from "../../../live/hooks";
import type { MatchSnap } from "../../../live/types";
import { EarlyLeaveDialog, EarlyLeaveNotice } from "./EarlyLeave";
import { ReportDialog } from "./ReportDialog";
import { Teams, TeamSummary } from "./TeamSummary";
import type { MatchScreenProps } from "./types";

/** `in_progress`: the bot-hosted lobby until a captain starts it (2.11), then the game (3.1).
 * A lobby a captain made by hand goes straight to the game: its code is already in. */
export function InGame({ match }: MatchScreenProps) {
  if (match.lobby.api_lobby && !match.lobby.api_started) return <Lobby match={match} />;
  return <Game match={match} />;
}

function Game({ match }: { match: MatchSnap }) {
  const elapsed = useElapsed(match.started_at);
  const [reporting, setReporting] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const canReportLeave = match.viewer.is_captain && match.early_leave.open && !match.early_leave.pending;
  const subtitle = [match.draft_name, match.lobby_code].filter(Boolean).join(" · ");
  return (
    <MatchShell match={match} width="wide">
      <Card className="flex-row flex-wrap items-center justify-between gap-6 border border-border p-7">
        <div className="flex flex-col gap-1.5">
          <Chip color="success" variant="soft" size="sm" className="gap-2 self-start font-semibold">
            <span aria-hidden="true" className="size-2 rounded-full bg-success" />
            In game
          </Chip>
          {elapsed ? (
            <span role="timer" aria-label={`${elapsed} in game`} className="text-5xl font-bold tracking-tight tabular-nums">
              {elapsed}
            </span>
          ) : null}
          <span className="text-sm text-muted">{subtitle}</span>
        </div>
        {match.viewer.is_captain ? (
          <div className="flex flex-wrap items-center gap-2.5">
            {canReportLeave ? (
              <Button
                variant="danger-soft"
                size="lg"
                onPress={() => setLeaving(true)}
                className="h-15 rounded-2xl border border-danger/30 px-6 text-base font-bold"
              >
                Someone left early
              </Button>
            ) : null}
            <Button size="lg" onPress={() => setReporting(true)} className="h-15 rounded-2xl px-8 text-lg font-bold">
              Report result
            </Button>
          </div>
        ) : null}
      </Card>
      <EarlyLeaveNotice match={match} />
      {match.viewer.is_captain ? <ReportDialog match={match} isOpen={reporting} onOpenChange={setReporting} /> : null}
      {canReportLeave || leaving ? <EarlyLeaveDialog match={match} isOpen={leaving} onOpenChange={setLeaving} /> : null}
      <div className="flex flex-wrap gap-5">
        <TeamSummary match={match} team="A" players="grid" />
        <TeamSummary match={match} team="B" players="grid" />
      </div>
    </MatchShell>
  );
}

function Lobby({ match }: { match: MatchSnap }) {
  const action = useAction();
  const code = match.lobby_code;

  const copy = () => {
    if (!code) return;
    const clipboard = typeof navigator !== "undefined" ? navigator.clipboard : undefined;
    if (!clipboard) {
      notify.warning("Copy isn't available here. Select the code instead.");
      return;
    }
    clipboard.writeText(code).then(() => notify.success("Lobby code copied"), notify.error);
  };
  const start = () => {
    // The service asks deadlock-api to start the lobby, which can take a few seconds. A refusal
    // shows under the button (action.error), not as a toast.
    action.run("draft.api_start", { match_id: match.id }).catch(() => {});
  };

  return (
    // The status is still in_progress, but for the player this is the lobby phase.
    <MatchShell match={{ ...match, status: "lobby_code" }} width="wide">
      <Card className="flex-row flex-wrap items-center justify-between gap-6 border border-border p-7">
        <div className="flex flex-col gap-1.5">
          <span className="text-sm text-muted">{match.draft_name} · GLHF</span>
          {code ? (
            <div className="flex items-center gap-3">
              <span className="min-w-0 text-5xl font-bold tracking-widest break-all tabular-nums">
                <span className="sr-only">Lobby code </span>
                {code}
              </span>
              <Button isIconOnly variant="secondary" aria-label="Copy lobby code" onPress={copy} className="size-11">
                <Copy width={18} height={18} aria-hidden="true" />
              </Button>
            </div>
          ) : (
            <span className="text-base font-semibold text-muted">Players only</span>
          )}
          <span className="max-w-120 text-sm text-muted">
            The bot is hosting. Join with the code and sit on your team&apos;s side, then a captain presses Start match.
          </span>
        </div>
        <div className="flex flex-col items-end gap-2">
          <div className="flex items-center gap-4">
            {match.lobby.api_leaves_at ? (
              <span className="flex flex-col items-end gap-0.5">
                <span className="text-xs text-muted">Lobby closes</span>
                <Countdown deadline={match.lobby.api_leaves_at} className="text-2xl font-bold" />
              </span>
            ) : null}
            {match.viewer.is_captain ? (
              <Button
                size="lg"
                onPress={start}
                isPending={action.pending}
                className="h-15 rounded-2xl bg-success px-8 text-lg font-bold text-success-foreground hover:bg-success-hover"
              >
                {({ isPending }) => (
                  <>
                    {isPending ? <Spinner color="current" size="sm" /> : null}
                    {isPending ? "Starting…" : "Start match"}
                  </>
                )}
              </Button>
            ) : null}
          </div>
          {action.error ? (
            <Alert status="danger" className="max-w-96">
              <Alert.Indicator />
              <Alert.Content>
                <Alert.Title>{action.error}</Alert.Title>
              </Alert.Content>
            </Alert>
          ) : null}
        </div>
      </Card>
      <Teams match={match} tinted showName={false} />
    </MatchShell>
  );
}
