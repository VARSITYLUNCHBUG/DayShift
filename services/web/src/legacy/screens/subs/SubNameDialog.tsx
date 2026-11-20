import { Alert, Button, Description, Label, Modal, SearchField, Spinner } from "@heroui/react";
import { useEffect, useState } from "react";

import { SEARCH_MIN, usePlayerSearch } from "../../../api/players";
import { Countdown } from "../../components/Countdown";
import { PlayerAvatar } from "../../components/PlayerAvatar";
import { errorText, notify } from "../../components/toast";
import { number } from "../../lib/format";
import { useAction, usePlayerId } from "../../../live/hooks";
import type { MatchSnap, SearchPlayer, SubEntry } from "../../../live/types";
import { canNameSub } from "./subs";

interface Props {
  match: MatchSnap;
  /** The open request to name a sub for; null when closed. */
  requestId: string | null;
  onClose: () => void;
}

/** 4.2 Name a sub: find someone and invite them, or hand the spot to the queue. Closes by itself
 * once naming is over (someone was asked, the spot filled, the request ended). */
export function SubNameDialog({ match, requestId, onClose }: Props) {
  const myId = usePlayerId();
  const line = requestId ? (match.subs.find((s) => s.id === requestId) ?? null) : null;
  const nameable = line !== null && canNameSub(match, line, myId);
  const over = requestId !== null && line !== null && !nameable;
  useEffect(() => {
    if (over) onClose();
  }, [over, onClose]);

  return (
    <Modal.Backdrop isOpen={nameable} onOpenChange={(open) => !open && onClose()}>
      <Modal.Container size="sm" scroll="inside">
        <Modal.Dialog>
          <Modal.CloseTrigger aria-label="Close" />
          <Modal.Header className="flex-row items-center justify-between gap-3 pr-12">
            <Modal.Heading className="text-2xl font-bold">Who&apos;s subbing in?</Modal.Heading>
            {line?.name_until ? <Countdown deadline={line.name_until} className="text-2xl font-bold" /> : null}
          </Modal.Header>
          <Modal.Body>{line ? <NameForm match={match} line={line} onDone={onClose} /> : null}</Modal.Body>
        </Modal.Dialog>
      </Modal.Container>
    </Modal.Backdrop>
  );
}

function NameForm({ match, line, onDone }: { match: MatchSnap; line: SubEntry; onDone: () => void }) {
  const [text, setText] = useState("");
  const search = usePlayerSearch(text);
  const action = useAction();
  const [error, setError] = useState<string | null>(null);
  const roster = new Set(match.players.map((p) => p.id));
  const long = text.trim().length >= SEARCH_MIN;
  const found = long ? (search.data ?? []).filter((p) => !roster.has(p.id)) : [];

  const invite = (player: SearchPlayer) => {
    setError(null);
    action.run("subs.invite", { request_id: line.id, player_id: player.id }).then(
      () => {
        notify.success(`Asked ${player.name}`, `To sub in for ${line.leaving_name}`);
        onDone();
      },
      (reason: unknown) => setError(errorText(reason)),
    );
  };
  const toQueue = () => {
    setError(null);
    action.run("subs.offer_queue", { request_id: line.id }).then(onDone, (reason: unknown) => setError(errorText(reason)));
  };

  return (
    <div className="flex flex-col gap-4">
      <SearchField value={text} onChange={setText} fullWidth autoFocus>
        <Label>Find a player</Label>
        <SearchField.Group>
          <SearchField.SearchIcon />
          <SearchField.Input placeholder="Name" className="h-12" />
          <SearchField.ClearButton />
        </SearchField.Group>
        <Description>For {line.leaving_name}&apos;s spot</Description>
      </SearchField>

      {long && search.isPending ? (
        <div className="flex justify-center py-4">
          <Spinner size="sm" aria-label="Searching" />
        </div>
      ) : null}
      {long && search.isError ? <p className="text-sm text-danger">Search isn&apos;t working right now.</p> : null}
      {long && search.isSuccess && found.length === 0 ? <p className="text-sm text-muted">Nobody by that name.</p> : null}
      {found.length > 0 ? (
        <ul aria-label="Players" className="flex flex-col gap-1.5">
          {found.map((player) => (
            <ResultRow key={player.id} player={player} pending={action.pending} onInvite={() => invite(player)} />
          ))}
        </ul>
      ) : null}

      {error ? (
        <Alert status="danger">
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Title>{error}</Alert.Title>
          </Alert.Content>
        </Alert>
      ) : null}

      <Button
        variant="secondary"
        size="lg"
        fullWidth
        onPress={toQueue}
        isDisabled={action.pending}
        className="h-13 rounded-2xl text-base font-bold"
      >
        Offer to the queue
      </Button>
    </div>
  );
}

/** "In queue · 1,250", "In a match", "On cooldown". */
function status(player: SearchPlayer): string {
  if (player.in_match) return "In a match";
  if (player.on_cooldown) return "On cooldown";
  return [player.in_queue ? "In queue" : null, number(player.rating)].filter(Boolean).join(" · ");
}

function ResultRow({ player, pending, onInvite }: { player: SearchPlayer; pending: boolean; onInvite: () => void }) {
  const busy = player.in_match || player.on_cooldown;
  return (
    <li
      aria-disabled={busy || undefined}
      className={`flex min-h-14 items-center gap-3 rounded-xl bg-background px-3 py-2 ${busy ? "opacity-55" : ""}`}
    >
      <PlayerAvatar name={player.name} url={player.avatar_url} />
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="truncate text-sm font-semibold">{player.name}</span>
        <span className="text-xs text-muted">{status(player)}</span>
      </span>
      {busy ? null : (
        <Button size="sm" onPress={onInvite} isDisabled={pending} aria-label={`Invite ${player.name}`} className="h-11 px-4">
          Invite
        </Button>
      )}
    </li>
  );
}
