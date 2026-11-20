// /ladder (E03): a season's table, a page at a time, your own row highlighted and pinned above.
// Names only: profiles are private, so no row links anywhere.
import { useInfiniteQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router";

import { queries } from "../../api/queries";
import type { Ladder, LadderRow } from "../../api/types";
import { Avatar } from "../../components/Avatar";
import { Button } from "../../components/Button";
import { EmptyState, ErrorState, Skeleton } from "../../components/States";
import { Sticker } from "../../components/Sticker";
import { cn } from "../../lib/cn";
import { number, record } from "../../lib/format";
import { SeasonSwitch, useSeasonParam } from "../shared/SeasonSwitch";

function YouBar({ ladder }: { ladder: Ladder }) {
  const me = ladder.me;
  return (
    <section aria-label="Your place" className="flex flex-wrap items-center gap-x-6 gap-y-2 rounded-panel border border-line bg-surface px-5 py-3.5">
      {me ? (
        <>
          <b className="text-body font-extrabold">{me.name}</b>
          <span className="text-body font-extrabold tabular-nums">
            You&apos;re #{me.rank}
            {me.tier ? ` · ${me.tier}` : ""} · {number(me.rating)} {ladder.rating_label === "Points" ? "points" : ""}
          </span>
          <span className="text-label text-muted tabular-nums">{record(me.wins, me.losses)}</span>
        </>
      ) : (
        <span className="text-body text-muted">You&apos;re not on this table yet: you get a place once you&apos;ve finished your placement matches.</span>
      )}
      <Link to="/me" className="ml-auto inline-flex min-h-11 items-center text-label font-extrabold underline underline-offset-2">
        Your rating history is on Me
      </Link>
    </section>
  );
}

/** Padding for every cell: tighter on a phone, so the record fits beside the rating. */
const CELL = "px-2 py-2.5 sm:px-3";

function Row({ row, label }: { row: LadderRow; label: string }) {
  return (
    <tr className={cn(row.is_you && "bg-raised")}>
      <td className={cn(CELL, "type-display text-card tabular-nums")}>{row.rank}</td>
      <th scope="row" className={cn(CELL, "text-left font-normal")}>
        <span className="flex min-w-0 items-center gap-2.5 sm:gap-3">
          <Avatar name={row.name} src={row.avatar_url} size="sm" />
          <span className="flex min-w-0 flex-col">
            <span className="flex min-w-0 items-baseline gap-2">
              <b className="truncate text-body font-extrabold">{row.name}</b>
              {row.is_you ? <span className="text-micro font-semibold text-muted">you</span> : null}
            </span>
            {/* On a phone the tier sits under the name, rather than in a column of its own. */}
            {row.tier !== null ? <span className="text-micro font-semibold text-muted sm:hidden">{row.tier}</span> : null}
          </span>
        </span>
      </th>
      {row.tier !== null ? (
        <td className={cn(CELL, "max-sm:hidden")}>
          <Sticker tone="raised" size="sm" tilt="slight">
            {row.tier}
          </Sticker>
        </td>
      ) : null}
      <td className={cn(CELL, "text-right font-extrabold tabular-nums")} aria-label={`${label} ${row.rating}`}>
        {number(row.rating)}
      </td>
      <td className={cn(CELL, "text-right whitespace-nowrap text-muted tabular-nums")}>{record(row.wins, row.losses)}</td>
    </tr>
  );
}

export function LadderPage() {
  const [, setParams] = useSearchParams();
  const season = useSeasonParam();
  const ladder = useInfiniteQuery(queries.ladder(season));
  const first = ladder.data?.pages[0];
  const rows = ladder.data?.pages.flatMap((page) => page.rows) ?? [];
  const tiers = first ? first.tiers.length > 0 : true;

  return (
    <>
      <header className="flex flex-wrap items-end justify-between gap-4 border-b border-line pb-4">
        <div className="flex flex-col gap-2">
          <h1 className="text-poster max-md:text-title">Ladder</h1>
          <p className="text-body text-muted">
            {first ? `${first.season} · ${first.total} ${first.total === 1 ? "player" : "players"} · ` : null}
            <Link to="/welcome" className="font-bold text-foreground underline underline-offset-2">
              New here?
            </Link>
          </p>
        </div>
        <SeasonSwitch value={season} onChange={(id) => setParams(id ? { season: id } : {}, { replace: true })} />
      </header>
      {ladder.isPending ? (
        <Skeleton label="Loading the ladder" lines={8} />
      ) : ladder.isError ? (
        <ErrorState
          title="We can't load the ladder right now"
          action={
            <Button kind="ghost" onPress={() => void ladder.refetch()}>
              Try again
            </Button>
          }
        >
          Ratings are safe; this page just didn&apos;t load.
        </ErrorState>
      ) : first ? (
        <>
          <YouBar ladder={first} />
          {rows.length === 0 ? (
            <EmptyState title="Nobody's on the table yet">Players get a place once they&apos;ve finished their placement matches.</EmptyState>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-label">
                <caption className="sr-only">
                  {first.season} ladder. Names only: profiles are private.
                </caption>
                <thead>
                  <tr className="text-micro font-extrabold text-faint">
                    <th scope="col" className="px-2 py-2 text-left sm:px-3">
                      #
                    </th>
                    <th scope="col" className="px-2 py-2 text-left sm:px-3">
                      Player
                    </th>
                    {tiers ? (
                      <th scope="col" className="px-3 py-2 text-left max-sm:hidden">
                        Tier
                      </th>
                    ) : null}
                    <th scope="col" className="px-3 py-2 text-right">
                      {first.rating_label}
                    </th>
                    <th scope="col" className="px-3 py-2 text-right">
                      Record
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <Row key={`${row.rank}-${row.name}`} row={row} label={first.rating_label} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {ladder.hasNextPage ? (
            <Button
              kind="ghost"
              className="self-start"
              isPending={ladder.isFetchingNextPage}
              pendingLabel="Loading more…"
              onPress={() => void ladder.fetchNextPage()}
            >
              Show more
            </Button>
          ) : null}
          <p className="text-label text-muted">
            Names only: profiles are private, so a name here doesn&apos;t open anyone&apos;s page. Unranked players get a place after their placement
            matches.
            {first.tiers.length ? ` Tiers, lowest first: ${first.tiers.join(", ")}.` : " While the server shows points, there are no tiers."}
          </p>
        </>
      ) : null}
    </>
  );
}

export default LadderPage;
