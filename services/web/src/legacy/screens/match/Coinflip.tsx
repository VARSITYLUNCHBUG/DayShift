import { Button, Card, Chip, Spinner } from "@heroui/react";
import { useState } from "react";

import { ChoiceCard } from "../../components/ChoiceCard";
import { Countdown } from "../../components/Countdown";
import { MatchShell } from "../../components/MatchShell";
import { notify } from "../../components/toast";
import { teamName } from "../../lib/format";
import { choiceName, COINFLIP_CHOICE, playerName } from "../../match/draft";
import { useAction } from "../../../live/hooks";
import type { CoinflipChoice, MatchSnap } from "../../../live/types";
import type { MatchScreenProps } from "./types";

const RANKED_CHOICES: CoinflipChoice[] = ["hk_pick1", "hk_pick2", "am_pick1", "am_pick2"];
const ORDER_CHOICES: CoinflipChoice[] = ["first_pick", "last_pick"];
const SIDE_CHOICES: CoinflipChoice[] = ["hidden_king", "archmother"];

/** 2.6 Coinflip (ranked): the winner picks a side and an order in one go. Scrims choose twice
 * (5.7), so they get their own layout. */
export function Coinflip({ match }: MatchScreenProps) {
  if (match.kind === "scrim") return <ScrimCoinflip match={match} />;
  const flip = match.coinflip;
  const chooserTeam = flip?.chooser_team ?? flip?.winner ?? null;
  const chooser = playerName(match, flip?.chooser_id) ?? (chooserTeam ? match.captains[chooserTeam] : null);
  const acting = match.viewer.is_acting;
  return (
    <MatchShell match={match}>
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex flex-col gap-1">
          {chooserTeam ? <span className="text-sm text-muted">{teamName(match.team_names, chooserTeam)}</span> : null}
          <h1 className="text-4xl font-bold tracking-tight">
            {acting ? "You won the flip" : `${chooser ?? "A captain"} is choosing`}
          </h1>
        </div>
        <Countdown deadline={match.deadline_at} className="text-3xl font-bold" />
      </div>
      <Choices match={match} choices={RANKED_CHOICES} acting={acting} />
      <span className="text-sm text-muted">Pick 1 bans and picks first.</span>
    </MatchShell>
  );
}

/** The cards. The captain on turn presses one; everyone else sees what's on offer. */
function Choices({
  match,
  choices,
  acting,
  selected = null,
}: {
  match: MatchSnap;
  choices: CoinflipChoice[];
  acting: boolean;
  selected?: CoinflipChoice | null;
}) {
  const action = useAction();
  const [sent, setSent] = useState<CoinflipChoice | null>(null);
  const offered = new Set(match.coinflip?.options ?? []);
  const choose = (choice: CoinflipChoice) => {
    setSent(choice);
    action
      .run("draft.coinflip", { match_id: match.id, choice })
      .catch(notify.error)
      .finally(() => setSent(null));
  };
  return (
    <ul aria-label="Choices" className="grid grid-cols-1 gap-4 sm:grid-cols-2">
      {choices.map((choice) => {
        const text = COINFLIP_CHOICE[choice];
        const canPress = acting && offered.has(choice);
        return (
          <li key={choice}>
            <ChoiceCard
              eyebrow={text.eyebrow}
              title={text.title}
              tone={text.tone}
              onPress={canPress ? () => choose(choice) : undefined}
              isDisabled={!canPress || action.pending}
              isPending={sent === choice}
              isSelected={selected === choice}
            />
          </li>
        );
      })}
    </ul>
  );
}

/** 5.7 Scrim coinflip, and the ready-to-draft step after it: the winner takes a pick order or a
 * side, the other captain takes the other kind, then either captain starts the draft. */
export function ScrimCoinflip({ match }: MatchScreenProps) {
  const flip = match.coinflip;
  const action = useAction();
  const ready = match.status === "ready_to_draft";
  const winner = flip?.winner ? match.captains[flip.winner] : null;
  const chooser = playerName(match, flip?.chooser_id);
  const acting = match.viewer.is_acting && !ready;
  const first = flip?.winner_choice ?? null;
  const choices = first === null ? [...ORDER_CHOICES, ...SIDE_CHOICES] : ORDER_CHOICES.includes(first) ? SIDE_CHOICES : ORDER_CHOICES;
  const heading = ready
    ? "Ready to draft"
    : acting
      ? first === null
        ? "You won the flip"
        : choices === SIDE_CHOICES
          ? "Choose your side"
          : "Choose your pick order"
      : first === null
        ? `${winner ?? "A captain"} won the flip`
        : `${chooser ?? "The other captain"} is choosing`;

  const start = () => {
    action.run("scrims.start", { match_id: match.id }).catch(notify.error);
  };

  return (
    <MatchShell match={match}>
      {first !== null ? (
        <Card className="flex-row flex-wrap items-center justify-between gap-3 border border-border px-5 py-4.5">
          <span className="text-base">
            <b>{winner ?? "The winner"}</b> won the flip and took
          </span>
          <Chip color="accent" variant="soft" className="font-bold">
            {choiceName(first)}
          </Chip>
        </Card>
      ) : null}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-3xl font-bold tracking-tight">{heading}</h1>
        {!ready ? <Countdown deadline={match.deadline_at} className="text-2xl font-bold" /> : null}
      </div>
      <Choices match={match} choices={choices} acting={acting} selected={ready ? (flip?.loser_choice ?? null) : null} />
      {ready ? (
        match.viewer.is_captain ? (
          <Button
            size="lg"
            fullWidth
            isPending={action.pending}
            onPress={start}
            className="h-15 rounded-2xl text-lg font-bold"
          >
            {({ isPending }) => (
              <>
                {isPending ? <Spinner color="current" size="sm" /> : null}
                Start draft
              </>
            )}
          </Button>
        ) : (
          <span className="text-sm text-muted">Waiting for a captain to start the draft.</span>
        )
      ) : null}
    </MatchShell>
  );
}
