import { Check } from "@gravity-ui/icons";
import { Button, Card, Chip, Spinner } from "@heroui/react";

import { Countdown, CountdownBar, CountdownRing } from "../../components/Countdown";
import { MatchShell } from "../../components/MatchShell";
import { PlayerAvatar } from "../../components/PlayerAvatar";
import { PlayerTile } from "../../components/PlayerTile";
import { notify } from "../../components/toast";
import { byName, plural } from "../../lib/format";
import { useAction, usePlayerId } from "../../../live/hooks";
import type { MatchPlayer, MatchSnap, SubDone, SubEntry } from "../../../live/types";
import type { MatchScreenProps } from "./types";

/** 2.1 Ready check, and 2.3 when it closed short and the missing seats are being refilled. */
export function ReadyCheck({ match }: MatchScreenProps) {
  const myId = usePlayerId();
  const me = match.players.find((p) => p.id === myId) ?? null;
  // Seats the bot opened itself: missed the ready check, or left empty by a restart.
  const missing = match.subs.filter((s) => s.reason !== "sub_out");
  const joined = match.subs_done.filter((s) => s.reason !== "sub_out" && s.status === "filled");
  const ready = match.players.filter((p) => p.is_ready).length;
  const seats = match.players.length + missing.length;
  return (
    <MatchShell match={match}>
      {missing.length > 0 ? (
        <div className="flex justify-center">
          <NeedSub missing={missing} joined={joined} ready={ready} seats={seats} />
        </div>
      ) : (
        <div className="flex flex-wrap items-center justify-center gap-10 sm:gap-14">
          <CountdownRing deadline={match.deadline_at} caption={`${ready} / ${seats}`} />
          <div className="flex w-80 max-w-full flex-col gap-3">
            <h1 className="mb-2 text-4xl font-bold tracking-tight">
              {match.viewer.is_player ? "Match found" : "Ready check"}
            </h1>
            {me ? <ReadyButton match={match} me={me} /> : null}
          </div>
        </div>
      )}
      <ul aria-label="Players" className="grid w-full grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-6">
        {sortPlayers(match.players, myId).map((player) => (
          <li key={player.id}>
            <PlayerTile
              name={player.name}
              state={player.is_ready ? "ready" : player.id === myId ? "you" : "waiting"}
            />
          </li>
        ))}
      </ul>
    </MatchShell>
  );
}

/** Ready ones first, then you, then everyone still to ready up. */
function sortPlayers(players: MatchPlayer[], myId: string | null): MatchPlayer[] {
  return [...players].sort(
    (a, b) =>
      Number(b.is_ready) - Number(a.is_ready) ||
      Number(b.id === myId) - Number(a.id === myId) ||
      byName(a, b),
  );
}

export function ReadyButton({ match, me, size = "xl" }: { match: Pick<MatchSnap, "id">; me: MatchPlayer; size?: "lg" | "xl" }) {
  const action = useAction();
  const height = size === "xl" ? "h-17 text-2xl" : "h-15 text-xl";
  if (me.is_ready) {
    return (
      <div
        role="status"
        className={`flex items-center justify-center gap-2.5 rounded-2xl border border-success/30 bg-success-soft font-bold text-success-soft-foreground ${height}`}
      >
        <Check width={22} height={22} aria-hidden="true" />
        Ready
      </div>
    );
  }
  return (
    <Button
      size="lg"
      fullWidth
      isPending={action.pending}
      onPress={() => {
        action.run("lobby.ready", { match_id: match.id }).catch(notify.error);
      }}
      className={`rounded-2xl bg-success font-bold text-success-foreground hover:bg-success-hover ${height}`}
    >
      {({ isPending }) => (
        <>
          {isPending ? <Spinner color="current" size="sm" /> : null}
          Ready
        </>
      )}
    </Button>
  );
}

function NeedSub({
  missing,
  joined,
  ready,
  seats,
}: {
  missing: SubEntry[];
  joined: SubDone[];
  ready: number;
  seats: number;
}) {
  const deadline = missing.map((s) => s.deadline_at).sort()[0] ?? null;
  const waitingOn = missing.flatMap((s) => (s.offer ? [s.offer.name] : []));
  return (
    <Card aria-labelledby="need-sub" className="w-full max-w-120 gap-4.5 rounded-3xl border border-border p-7">
      <div className="flex items-center justify-between gap-3">
        <h1 id="need-sub" className="text-2xl font-bold">
          Need {plural(missing.length, "Sub")}
        </h1>
        <Chip color="warning" variant="soft" className="font-semibold tabular-nums">
          <span>
            Cancels in <Countdown deadline={deadline} />
          </span>
        </Chip>
      </div>
      {waitingOn.length > 0 ? (
        <span className="text-base text-foreground/85">
          Waiting on response from <b>{waitingOn.join(", ")}</b>
        </span>
      ) : null}
      <CountdownBar deadline={deadline} tone="warning" />
      <ul className="flex flex-col gap-2">
        {missing.map((sub) => (
          <li
            key={sub.id}
            className="flex min-h-11 items-center gap-3 rounded-xl border border-dashed border-default p-3"
          >
            <span aria-hidden="true" className="size-8 shrink-0 rounded-full border-2 border-dashed border-default" />
            <span className="flex-1 text-sm text-muted">
              {sub.leaving_name} {sub.reason === "restart" ? "left before the game" : "missed the ready check"}
            </span>
          </li>
        ))}
        {joined.map((sub) => (
          <li
            key={sub.id}
            className="flex min-h-11 items-center gap-3 rounded-xl border border-success/30 bg-success-soft p-3 text-success-soft-foreground"
          >
            <PlayerAvatar name={sub.joined_name ?? "?"} url={null} />
            <span className="flex-1 text-sm text-foreground">{sub.joined_name}</span>
            <span className="text-sm font-semibold">Joined</span>
          </li>
        ))}
      </ul>
      <span className="mt-auto text-sm text-muted tabular-nums">
        {ready} / {seats} ready
      </span>
    </Card>
  );
}
