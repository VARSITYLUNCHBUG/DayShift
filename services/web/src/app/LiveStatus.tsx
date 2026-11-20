// The top bar's status chip: what you're in right now. Reads the old `me` topic until the new
// protocol (player:<id>) lands; FE-PAGES rewires it.
import { StatusChip } from "../components/Navigation";
import { STATUS_LABEL } from "../legacy/match/status";
import { useTopic } from "../live/hooks";

export function LiveStatus() {
  const { data: me } = useTopic("me");
  if (!me) return null;
  const match = me.match ?? me.scrim;
  if (match) {
    return (
      <StatusChip to={`/matches/${match.id}`} live>
        No. {match.id} · {STATUS_LABEL[match.status]}
      </StatusChip>
    );
  }
  if (me.queue.in_queue) {
    return (
      <StatusChip to="/" live>
        In the queue
      </StatusChip>
    );
  }
  return null;
}
