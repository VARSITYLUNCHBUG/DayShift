import { Button, Skeleton, Spinner } from "@heroui/react";

import { isNotFound, useLeaderboard } from "../../../api/matches";
import { AppShell } from "../../components/AppShell";
import { ButtonLink } from "../../components/ButtonLink";
import type { Column } from "../../components/DataTable";
import { DataTable } from "../../components/DataTable";
import { EmptyState } from "../../components/EmptyState";
import { PlayerAvatar } from "../../components/PlayerAvatar";
import { SeasonPicker, useSeasonParam } from "../../components/SeasonPicker";
import { TierChip } from "../../components/TierChip";
import { number, plural, record, winRate } from "../../lib/format";
import type { Leaderboard, LeaderboardEntry } from "../../../live/types";

/** 5.3 Leaderboard: a season's table, the open one unless `?season=` says otherwise, 50 rows
 * at a time. The viewer's own row is highlighted, and added at the foot when they're not in the
 * rows shown (short of the minimum, or further down). */
export function LeaderboardPage() {
  const season = useSeasonParam();
  const { data, error, isError, refetch, hasNextPage, fetchNextPage, isFetchingNextPage } = useLeaderboard(season);
  const board = data ? joinPages(data.pages) : undefined;
  return (
    <AppShell>
      {board ? (
        <LeaderboardView
          board={board}
          more={hasNextPage ? { onPress: () => void fetchNextPage(), isPending: isFetchingNextPage } : null}
        />
      ) : isNotFound(error) ? (
        <EmptyState
          title="No such season"
          action={
            <ButtonLink to="/ladder" variant="secondary">
              This season&apos;s leaderboard
            </ButtonLink>
          }
        />
      ) : isError ? (
        <EmptyState
          title="Couldn't load the leaderboard"
          description="Check your connection and try again."
          action={
            <Button variant="secondary" onPress={() => void refetch()}>
              Try again
            </Button>
          }
        />
      ) : (
        <Skeleton className="mx-auto h-120 w-full max-w-5xl rounded-2xl" />
      )}
    </AppShell>
  );
}

/** The pages so far as one table: the first page's details, every page's rows. */
export function joinPages(pages: Leaderboard[]): Leaderboard | undefined {
  const [first] = pages;
  if (!first) return undefined;
  return { ...first, rows: pages.flatMap((page) => page.rows), next_offset: pages.at(-1)?.next_offset ?? null };
}

interface Row extends LeaderboardEntry {
  isYou: boolean;
  /** The viewer's row, added after the list. */
  pinned: boolean;
}

export function rowsOf(board: Leaderboard): Row[] {
  const myId = board.me?.player.id ?? null;
  const rows: Row[] = board.rows.map((row) => ({ ...row, isYou: row.player.id === myId, pinned: false }));
  if (board.me && !rows.some((row) => row.isYou)) rows.push({ ...board.me, isYou: true, pinned: true });
  return rows;
}

const RANK_CLASS: Record<number, string> = {
  1: "text-tier-gold font-bold",
  2: "text-tier-silver font-bold",
  3: "text-tier-bronze font-bold",
};

const COLUMNS: Column<Row>[] = [
  {
    id: "rank",
    header: "#",
    cell: (row) => (
      <span className={row.rank ? (RANK_CLASS[row.rank] ?? "text-muted") : "text-muted"}>
        {row.rank ?? "–"}
      </span>
    ),
  },
  {
    id: "player",
    header: "Player",
    isRowHeader: true,
    cell: (row) => (
      <span className="flex items-center gap-2.5">
        <PlayerAvatar name={row.player.name} url={row.player.avatar_url} />
        <span className={row.isYou ? "font-bold" : "font-medium"}>
          {row.player.name}
        </span>
        {row.isYou ? <span className="text-xs text-muted">You</span> : null}
      </span>
    ),
  },
  { id: "tier", header: "Tier", cell: (row) => <TierChip tier={row.tier} /> },
  { id: "rating", header: "Rating", align: "end", cell: (row) => <span className="font-bold">{number(row.rating)}</span> },
  { id: "games", header: "Games", align: "end", cell: (row) => <span className="text-muted">{row.games}</span> },
  { id: "record", header: "W–L", align: "end", cell: (row) => <span className="text-muted">{record(row.wins, row.losses)}</span> },
  { id: "rate", header: "Win %", align: "end", cell: (row) => <span className="text-muted">{winRate(row.wins, row.games)}</span> },
];

interface ViewProps {
  board: Leaderboard;
  /** "Show more", while there are rows past the ones shown. */
  more?: { onPress: () => void; isPending: boolean } | null;
}

export function LeaderboardView({ board, more = null }: ViewProps) {
  const rows = rowsOf(board);
  const me = rows.find((row) => row.isYou);
  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-5">
      <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
        <h1 className="text-3xl font-bold">Leaderboard</h1>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <p className="text-sm text-muted">
            {board.season} · ranked after {plural(board.min_games, "game")}
          </p>
          <SeasonPicker value={board.season_id} />
        </div>
      </div>
      <DataTable
        label={`Leaderboard, ${board.season}`}
        columns={COLUMNS}
        rows={rows}
        rowKey={(row) => row.player.id}
        rowClassName={(row) => (row.isYou ? `bg-accent-soft text-accent-soft-foreground ${row.pinned ? "border-t-2 border-border" : ""}` : undefined)}
        empty={`Nobody's ranked yet. Players show here after ${plural(board.min_games, "game")}.`}
      />
      {more ? (
        <Button variant="secondary" onPress={more.onPress} isPending={more.isPending} className="self-center">
          {({ isPending }) => (
            <>
              {isPending ? <Spinner color="current" size="sm" /> : null}
              Show more
            </>
          )}
        </Button>
      ) : null}
      {me && me.rank === null ? (
        <p className="text-sm text-muted">
          You&apos;re ranked once you&apos;ve played {plural(board.min_games, "game")}: {me.games} so far.
        </p>
      ) : null}
    </div>
  );
}
