import { Button, Chip, Modal } from "@heroui/react";
import { useState } from "react";
import { useLocation, useNavigate } from "react-router";

import { Countdown, CountdownBar } from "../components/Countdown";
import { useTopic } from "../../live/hooks";
import { matchTopic } from "../../live/types";
import type { MatchPlayer, MatchSnap } from "../../live/types";
import { ReadyButton } from "./match/ReadyCheck";

/** 2.2: pops up on any page when the player's match turns into a ready check they haven't
 * readied for. Not on that match's own page, which has the same button. */
export function ReadyUpDialog() {
  const { data: me } = useTopic("me");
  const { pathname } = useLocation();
  const live = me?.match?.status === "ready_check" ? me.match : null;
  const onMatchPage = live !== null && pathname === `/matches/${live.id}`;
  const { data: match } = useTopic(live && !onMatchPage ? matchTopic(live.id) : null);
  const [dismissed, setDismissed] = useState<string | null>(null);

  const mine = match && me ? (match.players.find((p) => p.id === me.player.id) ?? null) : null;
  const isOpen =
    !!match && !!mine && !onMatchPage && match.status === "ready_check" && !mine.is_ready && dismissed !== match.id;
  if (!match || !mine) return null;
  return (
    <ReadyUpView
      match={match}
      me={mine}
      isOpen={isOpen}
      onClose={() => setDismissed(match.id)}
    />
  );
}

interface ViewProps {
  match: MatchSnap;
  me: MatchPlayer;
  isOpen: boolean;
  onClose: () => void;
}

export function ReadyUpView({ match, me, isOpen, onClose }: ViewProps) {
  const navigate = useNavigate();
  const ready = match.players.filter((p) => p.is_ready).length;
  return (
    <Modal.Backdrop isOpen={isOpen} onOpenChange={(open) => !open && onClose()}>
      <Modal.Container size="sm" placement="center">
        <Modal.Dialog aria-label="Ready Up" className="flex flex-col gap-4.5 p-7">
          <div className="flex items-center justify-between">
            <Chip color="success" variant="soft" size="sm" className="font-bold">
              Match {match.id}
            </Chip>
            <Countdown deadline={match.deadline_at} className="text-2xl font-bold" />
          </div>
          <Modal.Heading className="text-3xl font-bold tracking-tight">Ready Up</Modal.Heading>
          <CountdownBar deadline={match.deadline_at} tone="success" />
          <span className="text-sm text-muted tabular-nums">
            {ready} / {match.players.length} ready
          </span>
          <div className="mt-auto">
            <ReadyButton match={match} me={me} size="lg" />
          </div>
          <Button
            variant="ghost"
            className="self-center font-semibold text-link"
            onPress={() => void navigate(`/matches/${match.id}`)}
          >
            Open match
          </Button>
        </Modal.Dialog>
      </Modal.Container>
    </Modal.Backdrop>
  );
}
