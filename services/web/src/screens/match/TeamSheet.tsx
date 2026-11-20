// The team sheet (B08, the user's "post-coinflip screen for the team pick"): both rosters in their
// colours and sides, your team's wishes, and the captains' player swap (B16). The coinflip's
// waiting state, and a panel in the hero draft's rail.
import { useState } from "react";

import { Button } from "../../components/Button";
import { Countdown } from "../../components/Countdown";
import { Icon } from "../../components/Icon";
import { InlineAlert } from "../../components/InlineAlert";
import { NoticeSheet } from "../../components/NoticeSheet";
import { RadioCards } from "../../components/RadioCards";
import { TeamPanel } from "../../components/TeamPanel";
import { SIDE_NAME } from "../../components/team";
import { errorText, notify } from "../../components/toast";
import type { MatchSnap, SwapOffer, Team } from "../../live/protocol.gen";
import { useMatchAction } from "../../match/live";
import { leftRight, nameOf, other, teamKey, teamPlayers } from "../../match/model";
import type { Wishes } from "./Wishes";
import { TeamWants, WishesEditor } from "./Wishes";

/** Both rosters, The Hidden King's first. */
export function Rosters({ match, myId }: { match: MatchSnap; myId: string | null }) {
  const [left, right] = leftRight(match);
  return (
    <div className="flex flex-wrap gap-4">
      {[left, right].map((team) => (
        <TeamPanel
          key={team}
          team={teamKey(match, team)}
          name={nameOf(match, team)}
          line={rosterLine(match, team)}
          players={teamPlayers(match, team).map((p) => ({
            id: p.id,
            name: p.name,
            avatar: p.avatar_url,
            isYou: p.id === myId,
            line: p.is_captain ? "Captain" : undefined,
          }))}
        />
      ))}
    </div>
  );
}

function rosterLine(match: MatchSnap, team: Team): string {
  const side = match.sides[team];
  const first = match.champion_steps[0]?.side;
  const order = side && first ? (side === first ? "bans and picks first" : "bans and picks second") : null;
  return [side ? SIDE_NAME[side] : null, order, match.viewer.team === team ? "yours" : null].filter(Boolean).join(" · ");
}

/** The team sheet's body: rosters, wishes, swap. Spectators see the rosters only. */
export function TeamSheet({ match, myId, wishes }: { match: MatchSnap; myId: string | null; wishes: Wishes }) {
  const onTeam = match.viewer.is_player && match.viewer.team !== null;
  return (
    <div className="flex flex-col gap-8">
      <Rosters match={match} myId={myId} />
      {onTeam ? <TeamWants match={match} myId={myId} wishes={wishes} /> : null}
      {onTeam && wishes.canWish ? <WishesEditor match={match} myId={myId} wishes={wishes} /> : null}
      <SwapPanel match={match} myId={myId} />
    </div>
  );
}

// --- Swaps -------------------------------------------------------------------------------------

/** "Swap a player": a captain offers one of theirs for one of the other team's; the other
 * captain answers in time. Open in the coinflip, the hero draft and the lobby. */
export function SwapPanel({ match, myId }: { match: MatchSnap; myId: string | null }) {
  const pending = match.swap.pending;
  const team = match.viewer.team;
  if (!match.swap.open && !pending) return null;
  if (!match.viewer.is_captain || !team) {
    if (!pending) return null;
    return (
      <section aria-label="Player swap" className="flex flex-col gap-2 border-t border-line pt-6">
        <h2 className="text-card">Swap asked</h2>
        <p className="text-body text-muted">
          {pending.requested_by_name} asked to swap {pending.give_name} for {pending.take_name}. The other captain has{" "}
          <Countdown deadline={pending.deadline_at} /> to answer.
        </p>
      </section>
    );
  }
  return (
    <section aria-labelledby="swap-title" className="flex flex-col gap-3 border-t border-line pt-6">
      <h2 id="swap-title" className="text-card">
        Swap a player
      </h2>
      <p className="text-body text-muted">
        Captains can offer one of theirs for one of the other team&apos;s. {match.captains[other(team)] ?? "The other captain"}{" "}
        has a minute to answer.
      </p>
      {pending ? (
        <PendingSwap match={match} offer={pending} mine={pending.requested_by_id === myId} />
      ) : (
        <SwapRequest match={match} team={team} />
      )}
    </section>
  );
}

function PendingSwap({ match, offer, mine }: { match: MatchSnap; offer: SwapOffer; mine: boolean }) {
  return (
    <div role="status" className="flex flex-wrap items-center gap-3 rounded-card border border-line bg-surface px-4.5 py-4">
      <Icon name="swap" />
      <span className="text-body">
        {mine ? "You asked" : `${offer.requested_by_name} asked`} to swap <b>{offer.give_name}</b> for <b>{offer.take_name}</b>.{" "}
        {mine
          ? `Waiting for ${match.captains[match.viewer.team === "A" ? "B" : "A"] ?? "the other captain"}: `
          : "Answer within "}
        <Countdown deadline={offer.deadline_at} label="Time to answer" />.
      </span>
    </div>
  );
}

function SwapRequest({ match, team }: { match: MatchSnap; team: Team }) {
  const act = useMatchAction();
  const [open, setOpen] = useState(false);
  const [give, setGive] = useState<string | null>(null);
  const [take, setTake] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const gives = match.viewer.swap_give;
  const takes = match.viewer.swap_take;
  if (gives.length === 0 || takes.length === 0) return null;
  const otherCaptain = match.captains[other(team)] ?? "the other captain";
  const giveName = gives.find((g) => g.player_id === give)?.name;
  const takeName = takes.find((t) => t.player_id === take)?.name;

  if (!open) {
    return (
      <Button kind="ghost" icon="swap" onPress={() => setOpen(true)} className="self-start">
        Request a player swap
      </Button>
    );
  }
  const send = () => {
    if (!give || !take) return;
    setError(null);
    act.run("swap.propose", { match_id: match.id, give_id: give, take_id: take }).then(
      () => {
        notify.info(`Asked ${otherCaptain}`, `${giveName ?? "Yours"} for ${takeName ?? "theirs"}`);
        setOpen(false);
      },
      (reason: unknown) => setError(errorText(reason)),
    );
  };
  return (
    <div className="flex flex-col gap-4 rounded-panel border border-line bg-surface p-5">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-card">Ask {otherCaptain} for a swap</h3>
        <Button kind="quiet" size="sm" onPress={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <RadioCards
          label="One of yours"
          value={give}
          onChange={setGive}
          options={gives.map((g) => ({ id: g.player_id, title: g.name, tone: teamKey(match, team) }))}
        />
        <RadioCards
          label="For one of theirs"
          value={take}
          onChange={setTake}
          options={takes.map((t) => ({ id: t.player_id, title: t.name, tone: teamKey(match, other(team)) }))}
        />
      </div>
      {error ? <InlineAlert title={error} /> : null}
      <Button
        team={teamKey(match, team)}
        onPress={send}
        isDisabled={!give || !take}
        isPending={act.pending === "swap.propose"}
        pendingLabel="Asking…"
        className="self-start"
      >
        {giveName && takeName ? `Offer ${giveName} for ${takeName}` : "Choose both players"}
      </Button>
    </div>
  );
}

/** The other captain's answer (B16), as a notice sheet: it can wait while they finish a pick. */
export function SwapAnswerSheet({ match, offer }: { match: MatchSnap; offer: SwapOffer }) {
  const act = useMatchAction();
  const answer = (accept: boolean) => {
    act.run("swap.answer", { match_id: match.id, swap_id: offer.id, accept }).catch(notify.error);
  };
  const team = match.viewer.team;
  return (
    <NoticeSheet
      isOpen
      eyebrow="Swap request"
      title={`${offer.requested_by_name} asks to swap ${offer.give_name} for ${offer.take_name}`}
      deadline={offer.deadline_at}
      tone={team ? teamKey(match, team) : null}
      actions={
        <>
          <Button
            team={team ? teamKey(match, team) : null}
            onPress={() => answer(true)}
            isPending={act.pending === "swap.answer"}
            pendingLabel="Sending…"
          >
            Accept the swap
          </Button>
          <Button kind="ghost" onPress={() => answer(false)} isDisabled={act.pending !== null}>
            Decline
          </Button>
        </>
      }
    >
      {offer.give_name} would join your team and {offer.take_name} theirs. Their wishes go with them. No answer counts as no.
    </NoticeSheet>
  );
}
