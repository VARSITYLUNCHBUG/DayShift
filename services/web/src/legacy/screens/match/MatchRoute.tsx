import { Spinner } from "@heroui/react";
import { useParams } from "react-router";

import { useTopic } from "../../../live/hooks";
import { matchTopic } from "../../../live/types";
import type { MatchSnap } from "../../../live/types";
import { MatchNotFound, PastMatch } from "../matches/PastMatch";
import { MatchSubs } from "../subs/MatchSubs";
import { MATCH_SCREENS } from "./screens";
import { useMatchToasts } from "./useMatchToasts";

const MATCH_ID = /^[1-9][0-9]{0,18}$/;

/** /matches/:id — the match, live, on the screen for its status. A match the live connection
 * doesn't serve shows its record instead, if it has one. */
export function MatchRoute() {
  const { id = "" } = useParams();
  const valid = MATCH_ID.test(id);
  const { data, state } = useTopic(valid ? matchTopic(id) : null);
  useMatchToasts(data);
  if (!valid) return <MatchNotFound />;
  if (state === "gone") return <PastMatch id={id} />;
  if (!data) {
    return (
      <div className="flex min-h-dvh items-center justify-center">
        <Spinner aria-label="Loading the match" />
      </div>
    );
  }
  return <MatchView match={data} />;
}

export function MatchView({ match }: { match: MatchSnap }) {
  const Screen = MATCH_SCREENS[match.status];
  return (
    <MatchSubs match={match}>
      <Screen match={match} />
    </MatchSubs>
  );
}
