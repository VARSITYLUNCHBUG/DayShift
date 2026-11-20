import { Card } from "@heroui/react";

import { ButtonLink } from "../../components/ButtonLink";
import type { MeMatch } from "../../../live/types";
import { STATUS_LABEL } from "../../match/status";

/** In place of the queue while you're in a live match: which match and phase, and Open match.
 * The queue would only refuse you until it ends. A scrim you captain gets one too, above the
 * queue: scrim captains can queue meanwhile. */
export function YourMatchCard({ match }: { match: MeMatch }) {
  const scrim = match.kind === "scrim";
  const headingId = scrim ? "your-scrim" : "your-match";
  return (
    <Card aria-labelledby={headingId} className="gap-5.5 rounded-3xl border border-accent p-5 sm:p-7">
      <div className="flex flex-col gap-1.5">
        <span className="text-sm text-muted">{scrim ? "Your scrim" : "Your match"}</span>
        <h1 id={headingId} className="text-3xl font-bold tracking-tight sm:text-4xl">
          Match {match.id} · {STATUS_LABEL[match.status]}
        </h1>
      </div>
      <ButtonLink to={`/matches/${match.id}`} size="lg" fullWidth className="h-15 text-lg font-bold">
        {scrim ? "Open scrim" : "Open match"}
      </ButtonLink>
    </Card>
  );
}
