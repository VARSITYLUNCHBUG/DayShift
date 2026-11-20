// Subs in the room (I01–I06, I11): asking for a sub, naming one, the other captain's approval,
// and the paused banner while the spot is being filled. The server decides who can do what
// (league/services/subs.py); these only choose which controls to show.
import { Label, SearchField } from "@heroui/react";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";

import { getJson } from "../../api/http";
import { useDebounced } from "../../api/players";
import { Avatar } from "../../components/Avatar";
import { Banner } from "../../components/Banner";
import { Button } from "../../components/Button";
import { Countdown } from "../../components/Countdown";
import { Dialog } from "../../components/Dialog";
import { InlineAlert } from "../../components/InlineAlert";
import { NoticeSheet } from "../../components/NoticeSheet";
import { RadioCards } from "../../components/RadioCards";
import { errorText, notify } from "../../components/toast";
import { plural } from "../../lib/format";
import type { MatchSnap, PlayerSearch, SubEntry, SubOutOptions, SubRequested } from "../../live/protocol.gen";
import { useMatchAction } from "../../match/live";
import { approver, canNameSub, nameOf, other, pausedFor, playerKey } from "../../match/model";

export interface SubDialogState {
  requesting: boolean;
  naming: string | null;
  request: () => void;
  name: (requestId: string) => void;
  close: () => void;
}

export function useSubDialogs(_match: MatchSnap): SubDialogState {
  const [requesting, setRequesting] = useState(false);
  const [naming, setNaming] = useState<string | null>(null);
  const request = useCallback(() => setRequesting(true), []);
  const name = useCallback((id: string) => {
    setRequesting(false);
    setNaming(id);
  }, []);
  const close = useCallback(() => {
    setRequesting(false);
    setNaming(null);
  }, []);
  return { requesting, naming, request, name, close };
}

export function SubDialogs({ match, state }: { match: MatchSnap; state: SubDialogState }) {
  const line = state.naming ? match.subs.find((s) => s.id === state.naming) : undefined;
  return (
    <>
      {state.requesting && match.viewer.can_request_sub ? (
        <SubRequestDialog
          match={match}
          onClose={state.close}
          onRequested={(id, isSelf) => (isSelf ? state.name(id) : state.close())}
        />
      ) : null}
      {line ? <SubNameDialog match={match} line={line} onClose={state.close} /> : null}
    </>
  );
}

// --- Asking for a sub (I01) --------------------------------------------------------------------

/** Need a sub? Who comes out (you, or as captain a teammate), what it costs, then send. A
 * captain's request for a teammate goes to the other captain to approve. */
export function SubRequestDialog({
  match,
  onClose,
  onRequested,
}: {
  match: MatchSnap;
  onClose: () => void;
  onRequested: (requestId: string, isSelf: boolean) => void;
}) {
  const act = useMatchAction();
  const [options, setOptions] = useState<SubOutOptions | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [who, setWho] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const { run } = act;
  // Ask the server who this player may sub out, and what it would cost, once per opening.
  useEffect(() => {
    let live = true;
    run("subs.options", { match_id: match.id }).then(
      (ack) => {
        if (!live) return;
        const result = ack.result as SubOutOptions | null | undefined;
        if (!result) {
          setLoadError("Couldn't load who can sub out. Try again.");
          return;
        }
        setOptions(result);
        const only = result.choices.length === 1 ? result.choices[0] : undefined;
        if (only) setWho(only.player_id);
      },
      (reason: unknown) => {
        if (live) setLoadError(errorText(reason));
      },
    );
    return () => {
      live = false;
    };
  }, [run, match.id]);

  const choice = options?.choices.find((c) => c.player_id === who) ?? null;
  const team = match.viewer.team;
  const otherCaptain = team ? match.captains[other(team)] : null;
  const cost = options?.game_on
    ? "The game is on: subbing yourself out counts as leaving"
    : options?.dodge
      ? "Before the game: subbing yourself out counts as a dodge"
      : null;
  const strikes = options && options.strikes > 0 ? `, with ${plural(options.strikes, "strike")}` : "";
  const toApprove = choice !== null && !choice.is_self && otherCaptain;

  const send = () => {
    if (!choice) return;
    setError(null);
    act.run("subs.request", { match_id: match.id, player_id: choice.player_id }).then(
      (ack) => {
        const done = ack.result as SubRequested | null | undefined;
        notify.info(
          toApprove ? `Sent to ${otherCaptain}` : "Sub requested",
          `The match pauses until ${choice.is_self ? "your" : `${choice.name}'s`} sub is in.`,
        );
        onRequested(done?.request_id ?? "", choice.is_self);
      },
      (reason: unknown) => setError(errorText(reason)),
    );
  };

  return (
    <Dialog
      isOpen
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      tone={team ? playerKey(match, team) : null}
      eyebrow={`No. ${match.id}${match.viewer.is_captain && team ? ` · you captain ${nameOf(match, team)}` : ""}`}
      title="Need a sub?"
      actions={
        <>
          <Button
            team={team ? playerKey(match, team) : null}
            onPress={send}
            isDisabled={!choice}
            isPending={act.pending === "subs.request"}
            pendingLabel="Sending…"
            autoFocus
          >
            {toApprove ? `Send to ${otherCaptain}` : "Ask for a sub"}
          </Button>
          <Button kind="quiet" onPress={onClose}>
            Cancel
          </Button>
        </>
      }
    >
      <p>
        The match pauses until the sub is in.
        {match.viewer.is_captain && otherCaptain ? ` Subbing out a teammate needs ${otherCaptain} to agree.` : ""}
      </p>
      {loadError ? <InlineAlert title={loadError} /> : null}
      {!options && !loadError ? <p role="status">Checking who can sub out…</p> : null}
      {options ? (
        <RadioCards
          label="Who needs to come out?"
          value={who}
          onChange={setWho}
          options={options.choices.map((c) => ({
            id: c.player_id,
            title: c.is_self ? "Sub me out" : c.name,
            line: c.is_self
              ? cost
                ? `${cost}${strikes}.`
                : "Nobody's playing yet: no strike."
              : `Needs ${otherCaptain ?? "the other captain"} to agree. No strike for them.`,
            tone: playerKey(match, team),
          }))}
        />
      ) : null}
      {error ? <InlineAlert title={error} /> : null}
    </Dialog>
  );
}

// --- Naming a sub (I02) ------------------------------------------------------------------------

const SEARCH_MIN = 2;

function usePlayerSearch(text: string) {
  const query = useDebounced(text.trim());
  return useQuery({
    queryKey: ["players", "search", query],
    queryFn: () => getJson<PlayerSearch>(`/api/players/search/?${new URLSearchParams({ q: query }).toString()}`),
    enabled: query.length >= SEARCH_MIN,
    staleTime: 10_000,
    placeholderData: keepPreviousData,
    select: (data) => data.players,
  });
}

/** Name a sub: search the server's players by name (names only, no stats: D9), invite one, or
 * offer the spot to the queue. No name in time and the queue is asked anyway. */
export function SubNameDialog({ match, line, onClose }: { match: MatchSnap; line: SubEntry; onClose: () => void }) {
  const act = useMatchAction();
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const search = usePlayerSearch(text);
  const players = text.trim().length >= SEARCH_MIN ? (search.data ?? []) : [];
  const onRoster = new Set(match.players.map((p) => p.id));

  const invite = (id: string, name: string) => {
    setError(null);
    act.run("subs.invite", { request_id: line.id, player_id: id }).then(
      () => {
        notify.info(`Asked ${name}`, `They have a minute to take ${line.leaving_name}'s spot.`);
        onClose();
      },
      (reason: unknown) => setError(errorText(reason)),
    );
  };
  const queue = () => {
    setError(null);
    act.run("subs.offer_queue", { request_id: line.id }).then(onClose, (reason: unknown) => setError(errorText(reason)));
  };

  return (
    <Dialog
      isOpen
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      eyebrow={`No. ${match.id} · ${line.leaving_name} is coming out`}
      title="Name a sub"
      deadline={line.name_until}
      tone={playerKey(match, line.team)}
      actions={
        <>
          <Button kind="ghost" onPress={queue} isPending={act.pending === "subs.offer_queue"} pendingLabel="Asking the queue…">
            Offer it to the queue
          </Button>
          <Button kind="quiet" onPress={onClose}>
            Not now
          </Button>
        </>
      }
    >
      <p>
        Ask someone you know, or offer the spot to the queue.{line.name_until ? " No name in time and the queue is asked." : ""}
      </p>
      <SearchField value={text} onChange={setText} aria-label="Find a player" autoFocus>
        <Label className="text-label font-extrabold text-foreground">Find a player</Label>
        <SearchField.Group className="h-12">
          <SearchField.SearchIcon />
          <SearchField.Input placeholder="Their name" className="text-foreground placeholder:text-faint" />
          <SearchField.ClearButton />
        </SearchField.Group>
      </SearchField>
      {text.trim().length >= SEARCH_MIN && search.isSuccess && players.length === 0 ? (
        <p role="status">Nobody called that here.</p>
      ) : null}
      {players.length ? (
        <ul aria-label="Players found" className="flex max-h-72 flex-col gap-1 overflow-y-auto">
          {players.map((p) => {
            const busy = p.in_match || onRoster.has(p.id);
            return (
              <li key={p.id} className="flex min-h-14 items-center gap-3 rounded-row px-2 py-1.5">
                <Avatar name={p.name} src={p.avatar_url} size="md" />
                <span className="flex min-w-0 flex-1 flex-col">
                  <b className="truncate text-body">{p.name}</b>
                  {busy ? <span className="text-caption text-muted">In a match</span> : null}
                </span>
                <Button
                  kind="ghost"
                  size="sm"
                  isDisabled={busy || act.pending !== null}
                  onPress={() => invite(p.id, p.name)}
                  aria-label={`Ask ${p.name}`}
                >
                  Ask
                </Button>
              </li>
            );
          })}
        </ul>
      ) : null}
      {error ? <InlineAlert title={error} /> : null}
    </Dialog>
  );
}

// --- The other captain's approval (I03) --------------------------------------------------------

export function SubApproveSheet({ match, line }: { match: MatchSnap; line: SubEntry }) {
  const act = useMatchAction();
  const answer = (approve: boolean) => {
    act.run("subs.answer_request", { request_id: line.id, approve }).catch(notify.error);
  };
  const tone = playerKey(match, line.team);
  return (
    <NoticeSheet
      isOpen
      eyebrow={`No. ${match.id} · sub request`}
      title={`${line.requested_by_name ?? "Their captain"} wants to sub out ${line.leaving_name}`}
      deadline={line.deadline_at}
      tone={tone}
      actions={
        <>
          <Button onPress={() => answer(true)} isPending={act.pending === "subs.answer_request"} pendingLabel="Sending…">
            Approve
          </Button>
          <Button kind="ghost" onPress={() => answer(false)} isDisabled={act.pending !== null}>
            Refuse
          </Button>
        </>
      }
    >
      {line.team ? `${nameOf(match, line.team)} would name the sub. ` : ""}The match pauses until they&apos;re in. No answer
      counts as no.
    </NoticeSheet>
  );
}

// --- Paused (I06) ------------------------------------------------------------------------------

/** "Waiting for Orrin", "Waiting for Vesper to approve"… */
function waitingText(match: MatchSnap, line: SubEntry, nameable: boolean): string {
  if (line.status === "approval") {
    const captain = approver(match, line);
    return captain ? `Waiting for ${captain.name} to approve.` : "Waiting for the other captain to approve.";
  }
  if (line.offer) return `${line.offer.name} has been asked to come in.`;
  if (line.name_until)
    return nameable ? "Name a sub, or the queue is asked." : `${line.requested_by_name ?? "Their captain"} is naming a sub.`;
  return nameable
    ? "Nobody in the queue can take it yet. You can still name someone."
    : "Waiting for someone in the queue to take it.";
}

/** The banner over every phase while someone is subbing out: who, what it waits on, the clock,
 * and Name a sub or Cancel for whoever can. */
export function PausedBanners({ match, myId, onName }: { match: MatchSnap; myId: string | null; onName: (id: string) => void }) {
  const act = useMatchAction();
  const lines = pausedFor(match);
  if (lines.length === 0) return null;
  return (
    <>
      {lines.map((line) => {
        const nameable = canNameSub(match, line, myId);
        const mine = myId !== null && line.requested_by_id === myId;
        const deadline = line.status === "open" && line.name_until && !line.offer ? line.name_until : line.deadline_at;
        const cancel = () => {
          act.run("subs.cancel", { request_id: line.id }).catch(notify.error);
        };
        return (
          <Banner
            key={line.id}
            kind="info"
            title="Paused."
            action={
              nameable || mine ? (
                <span className="flex flex-wrap gap-2">
                  {nameable ? (
                    <Button size="sm" onPress={() => onName(line.id)}>
                      Name a sub
                    </Button>
                  ) : null}
                  {mine ? (
                    <Button
                      kind="ghost"
                      size="sm"
                      onPress={cancel}
                      isPending={act.pending === "subs.cancel"}
                      pendingLabel="Cancelling…"
                    >
                      Cancel the sub
                    </Button>
                  ) : null}
                </span>
              ) : undefined
            }
          >
            {line.leaving_name} is subbing out. {waitingText(match, line, nameable)}{" "}
            <Countdown deadline={deadline} label="Time left" /> left.
          </Banner>
        );
      })}
    </>
  );
}
