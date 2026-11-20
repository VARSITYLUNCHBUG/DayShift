// A spot in someone else's match, offered to you (I05): a notice sheet on any page, with its own
// clock. Esc hides it for that offer (it still runs out on its own); the buttons answer it.
import { useState } from "react";
import { useNavigate } from "react-router";

import { useMe, usePageAction } from "../../api/live";
import type { Offer } from "../../api/live";
import { Button } from "../../components/Button";
import { InlineAlert } from "../../components/InlineAlert";
import { NoticeSheet } from "../../components/NoticeSheet";
import { errorText } from "../../components/toast";
import { useElapsed } from "../../live/hooks";
import { matchNo, STATUS_LABEL } from "../../screens/shared/format";

/** Offers this tab accepted, so the "You're in" toast doesn't offer to open what's already open. */
const acceptedHere = new Set<string>();

export function wasAcceptedHere(offerId: string): boolean {
  return acceptedHere.has(offerId);
}

export function SpotOfferView({ offer, onDismiss }: { offer: Offer; onDismiss: () => void }) {
  const navigate = useNavigate();
  const action = usePageAction();
  const [error, setError] = useState<string | null>(null);
  const elapsed = useElapsed(offer.match_status === "in_progress" ? offer.started_at : null);
  const invite = offer.source === "invite";
  const answer = (accept: boolean) => {
    setError(null);
    if (accept) acceptedHere.add(offer.id);
    action.run("subs.answer_offer", { offer_id: offer.id, accept }).then(
      () => {
        if (accept) void navigate(`/matches/${offer.match_id}`);
        else onDismiss();
      },
      (reason: unknown) => setError(errorText(reason)),
    );
  };
  const where = [matchNo(offer.match_id), offer.team_name, elapsed ? `${STATUS_LABEL[offer.match_status]} · ${elapsed}` : STATUS_LABEL[offer.match_status]]
    .filter(Boolean)
    .join(" · ");
  return (
    <NoticeSheet
      isOpen
      eyebrow={invite ? "Sub invite" : "Spot offered"}
      title={invite ? `${offer.invited_by_name ?? offer.leaving_name} wants you to sub in` : "A spot opened for you"}
      deadline={offer.deadline_at}
      onDismiss={onDismiss}
      actions={
        <>
          <Button isPending={action.pending === "subs.answer_offer"} pendingLabel="Answering…" onPress={() => answer(true)}>
            {invite ? "Accept" : "Take the spot"}
          </Button>
          <Button kind="ghost" isDisabled={action.pending !== null} onPress={() => answer(false)}>
            {invite ? "Decline" : "Can't right now"}
          </Button>
        </>
      }
    >
      <p className="text-body">{where}</p>
      <p className="text-label text-muted">In for {offer.leaving_name}. Taking it puts you straight into the match.</p>
      {error ? <InlineAlert title="That didn't go through">{error}</InlineAlert> : null}
    </NoticeSheet>
  );
}

export function SpotOffer() {
  const me = useMe();
  const [dismissed, setDismissed] = useState<ReadonlySet<string>>(new Set());
  const offer = me.data?.offers.find((o) => !dismissed.has(o.id)) ?? null;
  if (!offer) return null;
  return <SpotOfferView key={offer.id} offer={offer} onDismiss={() => setDismissed((old) => new Set([...old, offer.id]))} />;
}
