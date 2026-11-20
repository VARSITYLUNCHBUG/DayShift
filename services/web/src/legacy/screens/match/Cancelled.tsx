import { Alert, Button, Card, Chip, Spinner } from "@heroui/react";

import { ButtonLink } from "../../components/ButtonLink";
import { MatchShell } from "../../components/MatchShell";
import { notify } from "../../components/toast";
import { useAction, useTopic } from "../../../live/hooks";
import { ScoreNames } from "./ScoreNames";
import type { MatchScreenProps } from "./types";

/** 3.8 Match cancelled (`voided`): why, that no ratings changed, and where the viewer stands in
 * the queue now (a cancelled lobby puts its ready players back at the front). */
export function Cancelled({ match }: MatchScreenProps) {
  const { data: me } = useTopic("me");
  const action = useAction();
  const inQueue = me?.queue.in_queue ?? false;
  const position = me?.queue.position ?? null;
  const reason = match.result.void_reason;

  const leave = () => {
    action.run("queue.leave", {}).catch(notify.error);
  };

  return (
    <MatchShell match={match}>
      <div className="flex flex-wrap items-start justify-center gap-5">
        <Card aria-labelledby={`cancelled-${match.id}`} className="w-full max-w-120 gap-4 border border-border p-7">
          <Chip variant="secondary" size="sm" className="self-start font-bold">
            No rating change
          </Chip>
          <h1 id={`cancelled-${match.id}`} className="text-2xl font-bold">
            Match cancelled
          </h1>
          {reason ? <p className="text-base text-muted">{/[.!?]$/.test(reason) ? reason : `${reason}.`}</p> : null}
          {me?.cooldown ? (
            <Alert status="warning">
              <Alert.Indicator />
              <Alert.Content>
                <Alert.Description>{me.cooldown.text}</Alert.Description>
              </Alert.Content>
            </Alert>
          ) : null}
          {inQueue ? (
            <>
              <div className="mt-2 flex items-center justify-between rounded-2xl bg-accent-soft px-4 py-3.5 text-accent-soft-foreground">
                <span className="text-base font-semibold">{match.viewer.is_player ? "Back in queue" : "In queue"}</span>
                {position !== null ? <span className="text-xl font-bold tabular-nums">#{position}</span> : null}
              </div>
              <Button variant="secondary" fullWidth onPress={leave} isPending={action.pending} className="h-11 rounded-xl">
                {({ isPending }) => (
                  <>
                    {isPending ? <Spinner color="current" size="sm" /> : null}
                    Leave queue
                  </>
                )}
              </Button>
            </>
          ) : me && !me.cooldown ? (
            <ButtonLink to="/" size="lg" fullWidth className="mt-2 h-12 rounded-xl font-bold">
              Queue again
            </ButtonLink>
          ) : null}
        </Card>
        {match.scoreboard ? <ScoreNames match={match} scoreboard={match.scoreboard} /> : null}
      </div>
    </MatchShell>
  );
}
