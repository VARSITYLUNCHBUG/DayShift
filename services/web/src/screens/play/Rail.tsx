// Play's right rail (A04): you (only you see this), tonight's matches, your last match.
import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Link } from "react-router";

import { useLiveMatches } from "../../api/live";
import type { LiveMatch } from "../../api/live";
import { queries } from "../../api/queries";
import type { MyProfile } from "../../api/types";
import { Avatar } from "../../components/Avatar";
import { Panel } from "../../components/Layout";
import { Skeleton } from "../../components/States";
import { Sticker } from "../../components/Sticker";
import { useElapsed, useServerNow } from "../../live/hooks";
import { cn } from "../../lib/cn";
import { ago, clockTime, plural, signed } from "../../lib/format";
import { SIDE_NAME } from "../shared/format";
import { MatchCard } from "../shared/parts";

function RailPanel({ title, aside, children, id }: { title: string; aside?: ReactNode; children: ReactNode; id: string }) {
  return (
    <Panel as="section" className="flex flex-col gap-3">
      <div className="flex items-baseline justify-between gap-2">
        <h2 id={id} className="text-card">
          {title}
        </h2>
        {aside ? <span className="text-caption font-semibold text-muted">{aside}</span> : null}
      </div>
      {children}
    </Panel>
  );
}

/** "No strikes · you can captain", "2 strikes · 1 of 3 clean matches to take one off". */
export function standingLine(profile: Pick<MyProfile, "strikes" | "captain">): string {
  const { strikes, captain } = profile;
  if (strikes.count === 0) return captain.eligible ? "No strikes · you can captain" : `No strikes · captain: ${captain.reason}`;
  const toGo = `${strikes.progress} of ${strikes.games_per_strike} clean matches to take one off`;
  return `${plural(strikes.count, "strike")} · ${toGo}`;
}

export function YouPanel() {
  const profile = useQuery(queries.me(null));
  return (
    <RailPanel id="you-heading" title="You" aside="Only you see this">
      {profile.isPending ? (
        <Skeleton label="Loading your standing" lines={1} />
      ) : profile.isError ? (
        <p className="text-label text-muted">Your rating isn&apos;t loading right now. It&apos;s all on Me.</p>
      ) : (
        <Link to="/me" className="flex flex-col gap-3 rounded-card">
          <span className="flex items-center gap-3.5">
            <Avatar name={profile.data.player.name} src={profile.data.accounts.avatar_url} size="xl" />
            <span className="flex min-w-0 flex-col gap-0.5">
              <b className="truncate text-body font-extrabold">{profile.data.player.name}</b>
              <span className="flex flex-wrap items-center gap-2.5">
                <span className="type-display text-stat tabular-nums">{profile.data.rating.toLocaleString("en-GB")}</span>
                {profile.data.tier ? (
                  <Sticker tone="raised" size="sm" tilt="slight">
                    {profile.data.tier}
                  </Sticker>
                ) : null}
                <span className="text-label font-semibold text-muted tabular-nums">
                  {profile.data.rank ? `#${profile.data.rank} on the ladder` : profile.data.placement ? `${profile.data.placement.played} of ${profile.data.placement.total} placement matches` : "Not on the ladder yet"}
                </span>
              </span>
            </span>
          </span>
          <span className="text-label text-muted">{standingLine(profile.data)}</span>
        </Link>
      )}
    </RailPanel>
  );
}

function LiveLine({ match }: { match: LiveMatch }) {
  const elapsed = useElapsed(match.status === "in_progress" ? match.started_at : null);
  if (elapsed && match.started_at) return <>{`${elapsed} · started ${clockTime(match.started_at)}`}</>;
  if (match.status === "champion_draft" || match.status === "player_draft") return <>Watch the draft</>;
  return <>{match.mode_name}</>;
}

export function TonightPanel({ limit = 4 }: { limit?: number }) {
  const live = useLiveMatches();
  const matches = live.data?.matches ?? [];
  return (
    <RailPanel id="tonight-heading" title="Tonight" aside={live.data ? `${matches.length} live` : undefined}>
      {live.state === "loading" ? (
        <Skeleton label="Loading tonight's matches" lines={2} avatar={false} />
      ) : matches.length === 0 ? (
        <p className="text-label text-muted">Nothing live right now. The next match starts when 12 are in the queue.</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {matches.slice(0, limit).map((match) => (
            <li key={match.id}>
              <MatchCard id={match.id} status={match.status} captains={match.captains} sides={match.sides} line={<LiveLine match={match} />} size="sm" />
            </li>
          ))}
        </ul>
      )}
      <Link to="/matches" className="inline-flex min-h-11 items-center self-start text-label font-extrabold underline underline-offset-2">
        All matches
      </Link>
    </RailPanel>
  );
}

const RESULT = { win: "Won", loss: "Lost", void: "Void" } as const;

export function LastMatchPanel() {
  const profile = useQuery(queries.me(null));
  const now = useServerNow(60_000);
  const last = profile.data?.recent[0];
  if (!last) return null;
  const side = last.side;
  const when = last.ended_at ? ago(last.ended_at, now) : null;
  return (
    <RailPanel id="last-heading" title="Your last match">
      <Link to={`/matches/${last.match_id}/summary`} className="flex items-center justify-between gap-3 rounded-card border border-line bg-background px-4 py-3.5 hover:border-line-strong">
        <span className="flex min-w-0 flex-col gap-0.5">
          <b className="text-body font-extrabold">
            No. {last.match_id}
            {last.result ? (
              <>
                {" · "}
                <span className={cn(last.result === "win" && side ? (side === "hk" ? "text-team-hk" : "text-team-am") : "text-muted")}>{RESULT[last.result]}</span>
              </>
            ) : null}
          </b>
          <span className="text-caption text-muted">{[when, side ? `as ${SIDE_NAME[side]}` : null, last.hero?.name].filter(Boolean).join(" · ")}</span>
        </span>
        {last.delta !== null ? <span className="type-display text-stat tabular-nums">{signed(last.delta)}</span> : null}
      </Link>
    </RailPanel>
  );
}
