import { Alert, Button, Chip, Modal, Spinner } from "@heroui/react";
import { useState } from "react";
import { useNavigate } from "react-router";

import { Countdown } from "../../components/Countdown";
import { errorText } from "../../components/toast";
import { STATUS_LABEL } from "../../match/status";
import { useAction, useElapsed, useTopic } from "../../../live/hooks";
import type { Offer } from "../../../live/types";
import { markAcceptedHere } from "./subs";

/** 4.4 and 4.5: a spot in someone else's match, offered to you. Pops up on any page, like Ready
 * Up, and stays dismissed for that offer; the offer itself still runs out on its own. */
export function OfferDialog() {
  const { data: me } = useTopic("me");
  const offer = me?.offers[0] ?? null;
  const [dismissed, setDismissed] = useState<string | null>(null);
  if (!offer) return null;
  return (
    <OfferView
      key={offer.id}
      offer={offer}
      isOpen={dismissed !== offer.id}
      onClose={() => setDismissed(offer.id)}
    />
  );
}

interface ViewProps {
  offer: Offer;
  isOpen: boolean;
  onClose: () => void;
}

export function OfferView({ offer, isOpen, onClose }: ViewProps) {
  const navigate = useNavigate();
  const action = useAction();
  const [error, setError] = useState<string | null>(null);
  const elapsed = useElapsed(offer.match_status === "in_progress" ? offer.started_at : null);
  const invite = offer.source === "invite";
  const title = invite ? `${offer.invited_by_name ?? offer.leaving_name} wants you to sub in` : "A spot opened";
  const phase = elapsed ? `${STATUS_LABEL[offer.match_status]} · ${elapsed}` : STATUS_LABEL[offer.match_status];

  const answer = (accept: boolean) => {
    setError(null);
    if (accept) markAcceptedHere(offer.id);
    action.run("subs.answer_offer", { offer_id: offer.id, accept }).then(
      () => {
        // Accepting puts you on the roster: the match page is where you're needed.
        if (accept) void navigate(`/matches/${offer.match_id}`);
      },
      (reason: unknown) => setError(errorText(reason)),
    );
  };

  return (
    <Modal.Backdrop isOpen={isOpen} onOpenChange={(open) => !open && onClose()}>
      <Modal.Container size="sm" placement="center">
        <Modal.Dialog aria-label={invite ? "Sub invite" : "Spot offered"} className="flex flex-col gap-4.5 p-7">
          <div className="flex items-center justify-between gap-3">
            <Chip color={invite ? "accent" : "success"} variant="soft" size="sm" className="font-bold">
              {invite ? "Invite" : "You're next in line"}
            </Chip>
            <Countdown deadline={offer.deadline_at} className="text-2xl font-bold" />
          </div>
          <Modal.Heading className="text-2xl font-bold">{title}</Modal.Heading>
          <div className="flex flex-wrap gap-2">
            <Chip size="md" variant="secondary">
              Match {offer.match_id}
            </Chip>
            {offer.team_name ? (
              <Chip size="md" color="warning" variant="soft">
                {offer.team_name}
              </Chip>
            ) : null}
            <Chip size="md" variant="secondary" className="tabular-nums">
              {phase}
            </Chip>
          </div>
          <p className="text-sm text-muted">In for {offer.leaving_name}.</p>
          {error ? (
            <Alert status="danger">
              <Alert.Indicator />
              <Alert.Content>
                <Alert.Title>{error}</Alert.Title>
              </Alert.Content>
            </Alert>
          ) : null}
          <div className="mt-auto grid grid-cols-2 gap-2.5">
            <Button
              variant="outline"
              size="lg"
              fullWidth
              isDisabled={action.pending}
              onPress={() => answer(false)}
              className="h-13 rounded-2xl font-bold"
            >
              {invite ? "Decline" : "Can't right now"}
            </Button>
            <Button
              size="lg"
              fullWidth
              isPending={action.pending}
              onPress={() => answer(true)}
              className="h-13 rounded-2xl bg-success font-bold text-success-foreground hover:bg-success-hover"
            >
              {({ isPending }) => (
                <>
                  {isPending ? <Spinner color="current" size="sm" /> : null}
                  {invite ? "Accept" : "I'll sub in"}
                </>
              )}
            </Button>
          </div>
        </Modal.Dialog>
      </Modal.Container>
    </Modal.Backdrop>
  );
}
