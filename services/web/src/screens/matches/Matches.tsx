// /matches (E01): what's live now (open one to watch) and this season's finished matches, newest
// first, a page at a time. All, Mine or Live.
import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import type { ReactNode } from "react";
import { Link, useSearchParams } from "react-router";

import { useLiveMatches } from "../../api/live";
import { queries } from "../../api/queries";
import type { MatchRow } from "../../api/types";
import { Button } from "../../components/Button";
import { Segmented } from "../../components/Navigation";
import { EmptyState, ErrorState, Skeleton } from "../../components/States";
import { useServerNow } from "../../live/hooks";
import { dayAndTime } from "../../lib/format";
import { teamLabel } from "../shared/format";
import { MatchCard } from "../shared/parts";

export type MatchesFilter = "all" | "mine" | "live";

const FILTERS: { id: MatchesFilter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "mine", label: "Mine" },
  { id: "live", label: "Live" },
];

const DAY = 24 * 60 * 60 * 1000;

function startOfDay(ms: number): number {
  const day = new Date(ms);
  day.setHours(0, 0, 0, 0);
  return day.getTime();
}

/** Finished matches by when they ended, in the viewer's own calendar. */
export function groupByDay(rows: readonly MatchRow[], nowMs: number): { title: string; rows: MatchRow[] }[] {
  const today = startOfDay(nowMs);
  const order = ["Tonight", "Yesterday", "Earlier this week", "Earlier this season"] as const;
  const groups = new Map<string, MatchRow[]>();
  for (const row of rows) {
    const ended = row.ended_at ? Date.parse(row.ended_at) : nowMs;
    const title = ended >= today ? order[0] : ended >= today - DAY ? order[1] : ended >= today - 6 * DAY ? order[2] : order[3];
    groups.set(title, [...(groups.get(title) ?? []), row]);
  }
  return order.filter((title) => groups.has(title)).map((title) => ({ title, rows: groups.get(title) ?? [] }));
}

const RESULT = { win: "Won", loss: "Lost" } as const;

function FinishedCard({ row, now }: { row: MatchRow; now: number }) {
  const result = row.your_team && row.winner ? (row.your_team === row.winner ? RESULT.win : RESULT.loss) : null;
  const winnerSide = row.winner ? row.sides[row.winner] : null;
  return (
    <MatchCard
      id={row.id}
      status={row.status}
      captains={row.captains}
      sides={row.sides}
      played={row.your_team !== null}
      sticker={row.winner && row.status === "completed" ? { label: `${teamLabel(row.captains[row.winner], row.winner)} won`, side: winnerSide } : null}
      line={[row.draft_name, row.mode_name, row.ended_at ? dayAndTime(row.ended_at, now) : null].filter(Boolean).join(" · ")}
      aside={result}
    />
  );
}

function Group({ title, note, children }: { title: string; note: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <h2 className="flex items-baseline gap-3 text-section">
        {title}
        <span className="font-sans text-label font-semibold tracking-normal text-muted">{note}</span>
      </h2>
      <ul className="flex flex-col gap-2.5">{children}</ul>
    </section>
  );
}

export function MatchesPage() {
  const [params, setParams] = useSearchParams();
  const raw = params.get("show");
  const filter: MatchesFilter = raw === "mine" || raw === "live" ? raw : "all";
  const mine = filter === "mine";
  const client = useQueryClient();
  const now = useServerNow(60_000);
  const seasons = useQuery(queries.seasons());
  const live = useInfiniteQuery(queries.matches("live", mine));
  const recent = useInfiniteQuery({ ...queries.matches("recent", mine), enabled: filter !== "live" });
  const liveTopic = useLiveMatches().data;

  // The live topic says when a match moves on: ask for the lists again.
  useEffect(() => {
    if (liveTopic) void client.invalidateQueries({ queryKey: ["matches", "list"] });
  }, [liveTopic, client]);

  const season = seasons.data?.seasons.find((s) => s.is_open)?.name;
  const liveRows = live.data?.pages.flatMap((page) => page.matches) ?? [];
  const finished = recent.data?.pages.flatMap((page) => page.matches) ?? [];
  const loading = live.isPending || (filter !== "live" && recent.isPending);
  const failed = live.isError || (filter !== "live" && recent.isError);
  const nothing = !loading && !failed && liveRows.length === 0 && (filter === "live" || finished.length === 0);

  return (
    <>
      <header className="flex flex-wrap items-end justify-between gap-4 border-b border-line pb-4">
        <div className="flex flex-col gap-2">
          <h1 className="text-poster max-md:text-title">Matches</h1>
          <p className="text-body text-muted">
            {season ? `${season} · ` : null}
            <Link to="/welcome" className="font-bold text-foreground underline underline-offset-2">
              New here?
            </Link>
          </p>
        </div>
        <Segmented
          label="Show"
          value={filter}
          onChange={(next) => setParams(next === "all" ? {} : { show: next }, { replace: true })}
          options={FILTERS}
        />
      </header>

      {loading ? (
        <Skeleton label="Loading matches" lines={5} avatar={false} />
      ) : failed ? (
        <ErrorState
          title="We can't load the matches right now"
          action={
            <Button
              kind="ghost"
              onPress={() => {
                void live.refetch();
                void recent.refetch();
              }}
            >
              Try again
            </Button>
          }
        >
          Nothing is lost: your queue place and any match you&apos;re in are safe. Try again in a moment.
        </ErrorState>
      ) : nothing ? (
        <EmptyState
          title={mine ? "No matches of yours yet" : "Nothing here"}
          action={
            filter !== "all" ? (
              <Button kind="ghost" onPress={() => setParams({}, { replace: true })}>
                Show all
              </Button>
            ) : null
          }
        >
          {mine
            ? "Your matches land here after your first one, each with its postgame. Live matches are always open to watch."
            : filter === "live"
              ? "Nothing live right now. The next match starts when 12 are in the queue."
              : "No matches this season yet. The first one starts when 12 are in the queue."}
        </EmptyState>
      ) : (
        <>
          {liveRows.length > 0 ? (
            <Group title="Live now" note="Open one to watch">
              {liveRows.map((row) => (
                <li key={row.id}>
                  <MatchCard
                    id={row.id}
                    status={row.status}
                    captains={row.captains}
                    sides={row.sides}
                    played={row.your_team !== null}
                    line={[row.draft_name, row.mode_name].join(" · ")}
                  />
                </li>
              ))}
            </Group>
          ) : null}
          {filter !== "live"
            ? groupByDay(finished, now).map((group) => (
                <Group key={group.title} title={group.title} note="Finished">
                  {group.rows.map((row) => (
                    <li key={row.id}>
                      <FinishedCard row={row} now={now} />
                    </li>
                  ))}
                </Group>
              ))
            : null}
          {filter !== "live" && recent.hasNextPage ? (
            <Button
              kind="ghost"
              className="self-start"
              isPending={recent.isFetchingNextPage}
              pendingLabel="Loading more…"
              onPress={() => void recent.fetchNextPage()}
            >
              Show more
            </Button>
          ) : null}
        </>
      )}
      <p className="text-label text-muted">
        A live match opens its room to watch (no lobby codes for spectators). A finished one opens its result; your own open your postgame.
      </p>
    </>
  );
}

export default MatchesPage;
