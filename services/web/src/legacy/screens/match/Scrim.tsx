import { Button, Card, Spinner } from "@heroui/react";

import { MatchShell } from "../../components/MatchShell";
import { PlayerAvatar } from "../../components/PlayerAvatar";
import { SIDE_NAME } from "../../components/SideChip";
import { notify } from "../../components/toast";
import { clockTime } from "../../lib/format";
import { teamOfSide } from "../../match/draft";
import { useAction, usePlayerId } from "../../../live/hooks";
import type { MatchSnap, Side } from "../../../live/types";
import { Teams } from "./TeamSummary";
import type { MatchScreenProps } from "./types";

const SIDES: Side[] = ["hk", "am"];

const SIDE_CARD: Record<Side, { open: string; claimed: string; title: string; text: string; button: string }> = {
  hk: {
    open: "border-dashed border-team-hk/40 bg-team-hk-soft",
    claimed: "border-team-hk/40 bg-team-hk-soft",
    title: "text-team-hk",
    text: "text-team-hk-soft-foreground",
    button: "bg-team-hk text-team-hk-foreground hover:bg-team-hk-hover",
  },
  am: {
    open: "border-dashed border-team-am/40 bg-team-am-soft",
    claimed: "border-team-am/40 bg-team-am-soft",
    title: "text-team-am",
    text: "text-team-am-soft-foreground",
    button: "bg-team-am text-team-am-foreground hover:bg-team-am-hover",
  },
};

/** 5.6 Scrim: claim a side. The first two to press become its captains, and the draft starts. */
export function ScrimClaim({ match }: MatchScreenProps) {
  return (
    <MatchShell match={match}>
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h1 className="text-3xl font-bold tracking-tight">Claim a side</h1>
        {match.deadline_at ? (
          <span className="text-sm text-muted tabular-nums">Closes {clockTime(match.deadline_at)}</span>
        ) : null}
      </div>
      <ul aria-label="Sides" className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {SIDES.map((side) => (
          <li key={side}>
            <SideCard match={match} side={side} />
          </li>
        ))}
      </ul>
    </MatchShell>
  );
}

function SideCard({ match, side }: { match: MatchSnap; side: Side }) {
  const myId = usePlayerId();
  const action = useAction();
  const team = teamOfSide(match, side);
  const captain = team ? (match.players.find((p) => p.team === team && p.is_captain) ?? null) : null;
  const style = SIDE_CARD[side];
  const headingId = `side-${side}`;

  const claim = () => {
    action.run("scrims.claim", { match_id: match.id, side }).catch(notify.error);
  };

  return (
    <Card
      aria-labelledby={headingId}
      className={`gap-4.5 border-2 p-6 ${captain ? style.claimed : style.open}`}
    >
      <h2 id={headingId} className={`text-lg font-bold ${style.title}`}>
        {SIDE_NAME[side]}
      </h2>
      <div className="flex min-h-10 items-center gap-3">
        {captain ? (
          <>
            <PlayerAvatar name={captain.name} url={captain.avatar_url} size="md" />
            <span className={`text-base font-semibold ${style.text}`}>
              {captain.id === myId ? `${captain.name} (you)` : captain.name}
            </span>
          </>
        ) : (
          <>
            <span aria-hidden="true" className="size-10 rounded-full border-2 border-dashed border-default" />
            <span className={`text-base ${style.text}`}>Open</span>
          </>
        )}
      </div>
      {captain ? (
        <span className={`flex h-13 items-center justify-center rounded-2xl bg-background/40 text-base font-semibold ${style.text}`}>
          Claimed
        </span>
      ) : match.viewer.is_captain ? (
        <span className={`flex h-13 items-center justify-center text-sm ${style.text}`}>Waiting for a captain</span>
      ) : (
        <Button
          size="lg"
          fullWidth
          onPress={claim}
          isPending={action.pending}
          className={`h-13 rounded-2xl font-bold ${style.button}`}
        >
          {({ isPending }) => (
            <>
              {isPending ? <Spinner color="current" size="sm" /> : null}
              Become captain
            </>
          )}
        </Button>
      )}
    </Card>
  );
}

/** A scrim whose draft is done: both teams' heroes and bans. */
export function ScrimDrafted({ match }: MatchScreenProps) {
  return (
    <MatchShell match={match} width="wide">
      <h1 className="text-3xl font-bold tracking-tight">Draft done</h1>
      <Teams match={match} tinted />
    </MatchShell>
  );
}
