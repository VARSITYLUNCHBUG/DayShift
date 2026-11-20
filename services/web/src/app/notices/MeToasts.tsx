// The player's own one-off toasts (I09), from changes to `me` seen live, on any page:
// - You're in: an offer of theirs was accepted (here or on Discord). With Open, unless this tab
//   accepted it, which already went there.
// - Offer expired / withdrawn: an offer ended without their answer.
// - Strike removed: clean matches worked one off.
import { useEffect, useRef } from "react";
import { useNavigate } from "react-router";

import { useMe } from "../../api/live";
import type { MeSnap } from "../../api/live";
import { notify } from "../../components/toast";
import { matchNo } from "../../screens/shared/format";
import { wasAcceptedHere } from "./SpotOffer";

/** Toast keys already shown in this tab, so a resent snapshot never repeats one. */
const shown = new Set<string>();

function once(key: string, show: () => void): void {
  if (shown.has(key)) return;
  shown.add(key);
  show();
}

export function useMeToasts(): void {
  const me = useMe().data;
  const navigate = useNavigate();
  const previous = useRef<MeSnap | null>(null);

  useEffect(() => {
    if (!me) return;
    const before = previous.current?.player.id === me.player.id ? previous.current : null;
    previous.current = me;
    if (!before) return;

    const ended = me.last_offer;
    if (ended && before.last_offer?.id !== ended.id && before.offers.some((offer) => offer.id === ended.id)) {
      const where = [matchNo(ended.match_id), ended.team_name].filter(Boolean).join(" · ");
      once(`offer:${ended.id}`, () => {
        if (ended.status === "accepted") {
          if (wasAcceptedHere(ended.id)) notify.success("You're in", where);
          else notify.success("You're in", where, { label: "Open", onPress: () => void navigate(`/matches/${ended.match_id}`) });
        } else if (ended.status === "expired") {
          notify.info("The offer ran out", where);
        } else if (ended.status === "withdrawn") {
          notify.info("The offer was withdrawn", "The spot was filled or closed.");
        }
      });
    }

    if (me.strikes < before.strikes) {
      notify.success("A strike came off", me.strikes > 0 ? `${me.strikes} left` : "No strikes left");
    }
  }, [me, navigate]);
}

/** Mounted once under the live connection. */
export function MeToasts(): null {
  useMeToasts();
  return null;
}
