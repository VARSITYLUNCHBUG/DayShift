import { Button, Skeleton, Spinner, Tabs } from "@heroui/react";
import type { Key } from "@heroui/react";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";

import { useRecentMatches } from "../../../api/matches";
import { AppShell } from "../../components/AppShell";
import type { Column } from "../../components/DataTable";
import { DataTable } from "../../components/DataTable";
import { StatusChip } from "../../components/StatusChip";
import { ago, teamName } from "../../lib/format";
import { useElapsed, useServerNow, useTopic } from "../../../live/hooks";
import type { ByTeam, LiveMatch, MatchKind, MatchRow, MatchStatus, Side, Sides, Team } from "../../../live/types";

export type MatchFilter = "all" | "live" | "mine";

/** A row of the list: a live match (from the `live` topic) or a finished one (over HTTP). */
export interface ListedMatch {
  id: string;
  status: MatchStatus;
  kind: MatchKind;
  draft_name: string;
  captains: ByTeam;
  team_names: ByTeam;
  sides: Sides;
  winner: Team | null;
  /** When the game started (live) or ended (finished). */
  at: string | null;
  live: boolean;
  yours: boolean;
}

function fromLive(match: LiveMatch, mine: string | null): ListedMatch {
  const names = {
    A: match.captains.A ? `${match.captains.A}'s Team` : null,
    B: match.captains.B ? `${match.captains.B}'s Team` : null,
  };
  return { ...match, team_names: names, winner: null, at: match.started_at, live: true, yours: match.id === mine };
}

function fromRow(row: MatchRow): ListedMatch {
  return { ...row, at: row.ended_at ?? row.started_at, live: false, yours: row.your_team !== null };
}

/** The live ones first, then the finished, each match once (one that just finished can be in
 * both until the live list catches up). */
export function listed(live: LiveMatch[], recent: MatchRow[], mine: string | null, filter: MatchFilter): ListedMatch[] {
  const rows = live.map((m) => fromLive(m, mine)).filter((m) => filter !== "mine" || m.yours);
  if (filter === "live") return rows;
  const seen = new Set(rows.map((r) => r.id));
  return [...rows, ...recent.filter((r) => !seen.has(r.id)).map(fromRow)];
}

/** 5.1 Matches: what's being played now, live, and this season's finished matches. */
export function MatchesPage() {
  const [filter, setFilter] = useState<MatchFilter>("all");
  const { data: live } = useTopic("live");
  const { data: me } = useTopic("me");
  const recent = useRecentMatches(filter === "mine");
  useRefreshWhenLiveEnds(live?.matches);
  const rows = live ? listed(live.matches, recent.data?.pages.flatMap((p) => p.matches) ?? [], me?.match?.id ?? null, filter) : null;
  return (
    <AppShell>
      <MatchesView
        filter={filter}
        onFilter={setFilter}
        rows={rows}
        loadingRecent={filter !== "live" && recent.isPending}
        failed={filter !== "live" && recent.isError}
        onRetry={() => void recent.refetch()}
        hasMore={filter !== "live" && recent.hasNextPage}
        loadingMore={recent.isFetchingNextPage}
        onLoadMore={() => void recent.fetchNextPage()}
      />
    </AppShell>
  );
}

/** A live match that ends lands in the finished list: ask for it again then. */
function useRefreshWhenLiveEnds(matches: LiveMatch[] | undefined) {
  const client = useQueryClient();
  const before = useRef<Set<string> | null>(null);
  useEffect(() => {
    if (!matches) return;
    const now = new Set(matches.map((m) => m.id));
    const ended = before.current ? [...before.current].some((id) => !now.has(id)) : false;
    before.current = now;
    if (ended) void client.invalidateQueries({ queryKey: ["matches", "recent"] });
  }, [matches, client]);
}

interface ViewProps {
  filter: MatchFilter;
  onFilter: (filter: MatchFilter) => void;
  /** Null until the live list arrives. */
  rows: ListedMatch[] | null;
  loadingRecent: boolean;
  failed: boolean;
  onRetry: () => void;
  hasMore: boolean;
  loadingMore: boolean;
  onLoadMore: () => void;
}

const FILTERS: { id: MatchFilter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "live", label: "Live" },
  { id: "mine", label: "Mine" },
];

const EMPTY: Record<MatchFilter, string> = {
  all: "No matches this season yet",
  live: "No matches right now",
  mine: "You haven't played this season",
};

export function MatchesView({ filter, onFilter, rows, loadingRecent, failed, onRetry, hasMore, loadingMore, onLoadMore }: ViewProps) {
  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-5">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-3xl font-bold">Matches</h1>
        <Tabs selectedKey={filter} onSelectionChange={(key: Key) => onFilter(String(key) as MatchFilter)}>
          <Tabs.ListContainer>
            <Tabs.List aria-label="Show">
              {FILTERS.map((f) => (
                <Tabs.Tab key={f.id} id={f.id}>
                  {f.label}
                  <Tabs.Indicator />
                </Tabs.Tab>
              ))}
            </Tabs.List>
          </Tabs.ListContainer>
        </Tabs>
      </div>
      {rows === null || (loadingRecent && rows.length === 0) ? (
        <Skeleton className="h-96 w-full rounded-2xl" />
      ) : (
        <DataTable
          label="Matches"
          columns={COLUMNS}
          rows={rows}
          rowKey={(row) => row.id}
          rowClassName={(row) => (row.yours ? "bg-accent-soft/40" : undefined)}
          empty={failed ? "Couldn't load the finished matches." : EMPTY[filter]}
        />
      )}
      {failed ? (
        <Button variant="secondary" className="self-center" onPress={onRetry}>
          Try again
        </Button>
      ) : hasMore ? (
        <Button variant="outline" size="lg" className="self-center font-semibold" isPending={loadingMore} onPress={onLoadMore}>
          {({ isPending }) => (
            <>
              {isPending ? <Spinner color="current" size="sm" /> : null}
              Load more
            </>
          )}
        </Button>
      ) : null}
    </div>
  );
}

const SIDE_TEXT: Record<Side, string> = { hk: "text-team-hk", am: "text-team-am" };

function sideText(sides: Sides, team: Team): string {
  const side = sides[team];
  return side ? SIDE_TEXT[side] : "";
}

const COLUMNS: Column<ListedMatch>[] = [
  {
    id: "match",
    header: "Match",
    isRowHeader: true,
    cell: (row) => (
      <Link to={`/matches/${row.id}`} className="font-semibold hover:underline">
        {row.draft_name ? `Match ${row.id} · ${row.draft_name}` : `Match ${row.id}`}
        {row.yours ? <span className="sr-only"> (yours)</span> : null}
      </Link>
    ),
  },
  { id: "status", header: "Status", cell: (row) => <StatusChip status={row.status} /> },
  {
    id: "captains",
    header: "Captains",
    cell: (row) =>
      row.captains.A || row.captains.B ? (
        <span>
          <span className={sideText(row.sides, "A")}>{row.captains.A ?? "–"}</span>
          <span className="text-muted"> · </span>
          <span className={sideText(row.sides, "B")}>{row.captains.B ?? "–"}</span>
        </span>
      ) : (
        <span className="text-muted">{row.kind === "scrim" ? "Scrim" : "–"}</span>
      ),
  },
  {
    id: "winner",
    header: "Winner",
    cell: (row) =>
      row.winner ? (
        <span className={`font-semibold ${sideText(row.sides, row.winner)}`}>{teamName(row.team_names, row.winner)}</span>
      ) : (
        <span className="text-muted">–</span>
      ),
  },
  { id: "when", header: "When", align: "end", cell: (row) => <When row={row} /> },
];

function When({ row }: { row: ListedMatch }) {
  const now = useServerNow(60_000);
  const elapsed = useElapsed(row.live && row.status === "in_progress" ? row.at : null);
  if (row.live) return <span className="text-muted">{elapsed ?? "Now"}</span>;
  return <span className="text-muted">{row.at ? ago(row.at, now) : "–"}</span>;
}
