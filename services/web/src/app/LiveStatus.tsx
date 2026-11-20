// The top bar's status chip (A05 to A07): what you're in right now, linking back there.
import { useMe, useQueue } from "../api/live";
import { StatusChip } from "../components/Navigation";
import { useCountdown, useServerNow } from "../live/hooks";
import { clockTime } from "../lib/format";
import { matchNo, ordinal, STATUS_LABEL } from "../screens/shared/format";

function HeldChip({ until }: { until: string }) {
  const left = useCountdown(until);
  return (
    <StatusChip to="/" live>
      Place held · {left?.label}
    </StatusChip>
  );
}

export function LiveStatus() {
  const me = useMe().data;
  const queue = useQueue().data;
  const now = useServerNow(5_000);
  if (!me) return null;
  const match = me.match ?? me.scrim;
  if (match) {
    return (
      <StatusChip to={`/matches/${match.id}`} live>
        {matchNo(match.id)} · {STATUS_LABEL[match.status]}
      </StatusChip>
    );
  }
  if (me.cooldown && Date.parse(me.cooldown.until) > now) {
    return <StatusChip to="/">Can&apos;t queue until {clockTime(me.cooldown.until)}</StatusChip>;
  }
  if (me.queue.in_queue) {
    const place = me.queue.place?.position ?? me.queue.position;
    return (
      <StatusChip to="/" live>
        In the queue{place ? ` · ${ordinal(place)}` : ""}
        {queue ? ` · ${queue.count}/${queue.size}` : ""}
      </StatusChip>
    );
  }
  const held = me.queue.place?.held_until;
  if (held && Date.parse(held) > now) return <HeldChip until={held} />;
  return null;
}
