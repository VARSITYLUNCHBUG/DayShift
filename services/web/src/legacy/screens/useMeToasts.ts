// Toasts from changes to the player's own state, on any page.
import { useEffect, useRef } from "react";
import { useNavigate } from "react-router";

import { notify } from "../components/toast";
import { useTopic } from "../../live/hooks";
import type { MeSnap } from "../../live/types";
import { toastOnce } from "./match/useMatchToasts";
import { wasAcceptedHere } from "./subs/subs";

/** Raises the player's own one-off toasts as `me` changes. Only for changes seen live.
 *
 * - **You're in**: an offer they had was accepted (here or on Discord), so they're on that
 *   match's roster now. With "Open" to go to it, unless they accepted on this page, which
 *   already went there.
 * - **Offer expired** / **Offer withdrawn**: an offer they had ended without their answer: time
 *   ran out, or the spot was filled or closed. Declining needs no toast.
 * - **Strike removed**: their strikes went down (clean matches work them off). */
export function useMeToasts(): void {
  const { data: me } = useTopic("me");
  const navigate = useNavigate();
  const previous = useRef<MeSnap | null>(null);

  useEffect(() => {
    if (!me) return;
    const before = previous.current?.player.id === me.player.id ? previous.current : null;
    previous.current = me;
    if (!before) return;

    const ended = me.last_offer;
    if (ended && before.last_offer?.id !== ended.id && before.offers.some((o) => o.id === ended.id)) {
      const key = `offer:${ended.id}`;
      if (ended.status === "accepted") {
        const where = [`Match ${ended.match_id}`, ended.team_name].filter(Boolean).join(" · ");
        // Accepted from this page: that already went to the match, so no "Open".
        toastOnce(key, () =>
          wasAcceptedHere(ended.id)
            ? notify.success("You're in", where)
            : notify.success("You're in", where, { label: "Open", onPress: () => void navigate(`/matches/${ended.match_id}`) }),
        );
      } else if (ended.status === "expired") {
        toastOnce(key, () => notify.warning("Offer expired", `Match ${ended.match_id}`));
      } else if (ended.status === "withdrawn") {
        toastOnce(key, () => notify.info("Offer withdrawn", "The spot was filled or closed"));
      }
    }

    if (me.strikes < before.strikes) {
      notify.success("Strike removed", me.strikes > 0 ? `${me.strikes} left` : "No strikes left");
    }
  }, [me, navigate]);
}

/** Mounted once, under the live connection. */
export function MeToasts(): null {
  useMeToasts();
  return null;
}
