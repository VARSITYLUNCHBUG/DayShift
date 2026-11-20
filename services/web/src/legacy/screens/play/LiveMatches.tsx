import { Card } from "@heroui/react";
import { Link } from "react-router";

import { EmptyState } from "../../components/EmptyState";
import { StatusChip } from "../../components/StatusChip";
import { useElapsed } from "../../../live/hooks";
import type { LiveMatch, LiveSnap } from "../../../live/types";

/** The matches being played now; each opens the match page (watching, if it isn't yours). */
export function LiveMatches({ live, mine }: { live: LiveSnap; mine: string | null }) {
  return (
    <section aria-labelledby="live-heading" className="flex flex-col gap-3.5">
      <h2 id="live-heading" className="text-lg font-bold">
        Live
      </h2>
      {live.matches.length === 0 ? (
        <EmptyState title="No matches right now" />
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {live.matches.map((match) => (
            <li key={match.id}>
              <LiveCard match={match} isMine={match.id === mine} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function LiveCard({ match, isMine }: { match: LiveMatch; isMine: boolean }) {
  const elapsed = useElapsed(match.status === "in_progress" ? match.started_at : null);
  const { A, B } = match.captains;
  return (
    <Link
      to={`/matches/${match.id}`}
      className="block rounded-2xl outline-none focus-visible:ring-2 focus-visible:ring-focus"
    >
      <Card
        className={`gap-3 border px-5 py-4.5 motion-safe:transition-colors hover:bg-surface-hover ${isMine ? "border-accent" : "border-border"}`}
      >
        <span className="flex items-center justify-between gap-2">
          <span className="text-base font-bold">Match {match.id}</span>
          <StatusChip status={match.status} detail={elapsed} />
        </span>
        <span className="text-sm text-foreground/85">
          {A && B ? (
            <>
              {A}&apos;s Team <span className="text-muted">vs</span> {B}&apos;s Team
            </>
          ) : (
            match.mode_name
          )}
        </span>
      </Card>
    </Link>
  );
}
