// The coinflip (B07) and what everyone else sees meanwhile: the team sheet (B08). Ranked: the
// winner chooses a side only; The Hidden King always bans and picks first (D7). Scrims choose
// twice (a pick order or a side, then the other), then a captain starts the draft. The scrim
// claim (E07) is here too.
import { useState } from "react";
import { ToggleButton } from "react-aria-components/ToggleButton";

import { Button } from "../../components/Button";
import { Sticker } from "../../components/Sticker";
import type { TeamKey } from "../../components/team";
import { SIDE_NAME, TEAM_CLASS } from "../../components/team";
import { notify } from "../../components/toast";
import { cn } from "../../lib/cn";
import { clockTime } from "../../lib/format";
import type { CoinflipChoice, MatchSnap, Side, Team } from "../../live/protocol.gen";
import { useMatchAction } from "../../match/live";
import { nameOf, other, teamKey, teamOfSide } from "../../match/model";
import { Note, StageHead } from "./Parts";
import { Room, useMe } from "./Room";
import { Rosters, TeamSheet } from "./TeamSheet";
import type { MatchScreenProps } from "./types";
import { useWishes } from "./Wishes";

const CHOICE_NAME: Record<CoinflipChoice, string> = {
  hidden_king: SIDE_NAME.hk,
  archmother: SIDE_NAME.am,
  first_pick: "First pick",
  last_pick: "Last pick",
};

const CHOICE_TONE: Record<CoinflipChoice, TeamKey | null> = {
  hidden_king: "hk",
  archmother: "am",
  first_pick: null,
  last_pick: null,
};

/** What each choice means, in the draft's own order. */
function choiceLine(match: MatchSnap, choice: CoinflipChoice, otherName: string): string {
  const firstSide: Side = match.champion_steps[0]?.side ?? "hk";
  switch (choice) {
    case "hidden_king":
    case "archmother": {
      const side: Side = choice === "hidden_king" ? "hk" : "am";
      if (match.kind === "scrim") return `Play ${SIDE_NAME[side]}. ${otherName} plays the other side.`;
      return side === firstSide
        ? "Your team bans and picks heroes first."
        : `${otherName} bans and picks first; you get the last pick.`;
    }
    case "first_pick":
      return `Your team bans and picks first. ${otherName} chooses the side.`;
    case "last_pick":
      return `${otherName} bans and picks first; you get the last pick and choose the side.`;
  }
}

export function Coinflip({ match }: MatchScreenProps) {
  const { myId } = useMe(match);
  const wishes = useWishes(match, myId);
  const flip = match.coinflip;
  const chooserTeam = flip?.chooser_team ?? flip?.winner ?? null;
  const winner = flip?.winner ?? null;
  const acting = match.viewer.is_acting && (flip?.options.length ?? 0) > 0;
  const tone = chooserTeam ? teamKey(match, chooserTeam) : null;
  const chooser = chooserTeam ? (match.captains[chooserTeam] ?? nameOf(match, chooserTeam)) : "A captain";
  const winnerName = winner ? (match.captains[winner] ?? nameOf(match, winner)) : null;
  const firstTook = flip?.winner_choice ?? null;
  const eyebrows: Partial<Record<Team, string>> = winner
    ? { [winner]: "Won the flip", [other(winner)]: "Gets the other choice" }
    : {};

  return (
    <Room
      match={match}
      acting={chooserTeam}
      eyebrows={eyebrows}
      phaseLine={acting ? "Sides · your choice" : "Sides"}
      now={{
        title: acting ? "Your choice" : `${chooser} is choosing`,
        line: `${winnerName ?? "A captain"} won the flip · no choice in time: picked at random`,
        tone,
        deadline: match.deadline_at,
        announce: acting ? "to choose" : undefined,
      }}
    >
      {firstTook && winnerName ? (
        <p role="status" className="flex flex-wrap items-center gap-2 text-body">
          <b>{winnerName}</b> won the flip and took{" "}
          <Sticker tone={CHOICE_TONE[firstTook] ?? "cream"}>{CHOICE_NAME[firstTook]}</Sticker>
        </p>
      ) : null}
      {acting && flip && chooserTeam ? (
        <Choose match={match} team={chooserTeam} options={flip.options} />
      ) : (
        <>
          <StageHead
            eyebrow="Coinflip"
            title={winnerName && !firstTook ? `${winnerName} won the flip` : `${chooser} is choosing`}
            lead={
              match.kind === "scrim"
                ? "Then a captain starts the hero draft."
                : `${chooser} chooses a side. The Hidden King bans and picks heroes first. Add what you want to play while the clock runs.`
            }
            tone={tone ? TEAM_CLASS[tone].text : undefined}
          />
          {match.kind === "scrim" ? (
            <Rosters match={match} myId={myId} />
          ) : (
            <TeamSheet match={match} myId={myId} wishes={wishes} />
          )}
        </>
      )}
      {acting && match.kind === "ranked" ? <TeamSheet match={match} myId={myId} wishes={wishes} /> : null}
    </Room>
  );
}

function Choose({ match, team, options }: { match: MatchSnap; team: Team; options: CoinflipChoice[] }) {
  const act = useMatchAction();
  const [choice, setChoice] = useState<CoinflipChoice | null>(null);
  const key = teamKey(match, team);
  const otherName = match.captains[other(team)] ?? nameOf(match, other(team));
  const confirm = () => {
    if (!choice) return;
    act.run("draft.coinflip", { match_id: match.id, choice }).catch(notify.error);
  };
  return (
    <section aria-labelledby="choose" className="flex flex-col gap-5">
      <StageHead
        eyebrow="Coinflip"
        title={match.coinflip?.winner_choice ? "Your choice" : "You won the flip"}
        lead={`Choose one. ${otherName} gets the other. No choice in time and one is picked at random.`}
        tone={TEAM_CLASS[key].text}
      />
      <div role="group" aria-labelledby="choose" className="grid gap-4 sm:grid-cols-2">
        <h2 id="choose" className="sr-only">
          Which do you want?
        </h2>
        {options.map((option) => {
          const optionTone = CHOICE_TONE[option] ?? key;
          const selected = choice === option;
          return (
            <ToggleButton
              key={option}
              isSelected={selected}
              onChange={() => setChoice(option)}
              className={cn(
                "relative flex min-h-36 cursor-pointer flex-col items-start gap-3 rounded-panel border-3 p-6 text-left outline-none transition-state",
                selected
                  ? cn(TEAM_CLASS[optionTone].border, TEAM_CLASS[optionTone].soft, "shadow-lift")
                  : "border-line bg-surface",
              )}
            >
              {selected ? (
                <span className="absolute top-3 right-3">
                  <Sticker tone={optionTone} size="sm" tilt="right">
                    Chosen
                  </Sticker>
                </span>
              ) : null}
              <span className={cn("text-label font-bold", TEAM_CLASS[optionTone].text)}>{nameOf(match, team)} · your call</span>
              <span className={cn("font-display text-coin", TEAM_CLASS[optionTone].text)}>{CHOICE_NAME[option]}</span>
              <span className="text-body text-muted">{choiceLine(match, option, otherName)}</span>
            </ToggleButton>
          );
        })}
      </div>
      <Button
        size="lg"
        team={choice ? (CHOICE_TONE[choice] ?? key) : key}
        isDisabled={!choice}
        onPress={confirm}
        isPending={act.pending === "draft.coinflip"}
        pendingLabel="Choosing…"
        className="self-start max-md:self-stretch"
      >
        {choice ? `Take ${CHOICE_NAME[choice]}` : "Choose one first"}
      </Button>
      <Note title={`${otherName} is waiting for your choice`}>
        They see that you won the flip and are choosing, and get the other choice the moment you confirm.
      </Note>
    </section>
  );
}

// --- Scrims ------------------------------------------------------------------------------------

/** Scrim: the two captains have chosen; either starts the hero draft. */
export function ScrimReady({ match }: MatchScreenProps) {
  const { myId } = useMe(match);
  const act = useMatchAction();
  const flip = match.coinflip;
  const start = () => {
    act.run("scrims.start", { match_id: match.id }).catch(notify.error);
  };
  const button = match.viewer.is_captain ? (
    <Button size="lg" onPress={start} isPending={act.pending === "scrims.start"} pendingLabel="Starting…">
      Start the hero draft
    </Button>
  ) : null;
  const winner = flip?.winner ? (match.captains[flip.winner] ?? null) : null;
  return (
    <Room
      match={match}
      now={{ title: "Ready to draft", line: "A captain starts the hero draft", deadline: match.deadline_at }}
      footer={button}
    >
      <StageHead
        eyebrow="Scrim"
        title="Ready to draft"
        lead={
          flip?.winner_choice && flip.loser_choice
            ? `${winner ?? "The winner"} took ${CHOICE_NAME[flip.winner_choice]}; the other captain took ${CHOICE_NAME[flip.loser_choice]}.`
            : "Both captains have chosen."
        }
        action={button}
      />
      <Rosters match={match} myId={myId} />
      {!match.viewer.is_captain ? <p className="text-body text-muted">Waiting for a captain to start the draft.</p> : null}
    </Room>
  );
}

/** Scrim: two captains claim a side each, then the coinflip. */
export function ScrimClaim({ match }: MatchScreenProps) {
  const act = useMatchAction();
  const claim = (side: Side) => {
    act.run("scrims.claim", { match_id: match.id, side }).catch(notify.error);
  };
  const sides: Side[] = ["hk", "am"];
  return (
    <Room
      match={match}
      now={{
        title: "Claim a side",
        line: match.deadline_at ? `Open until ${clockTime(match.deadline_at)}` : undefined,
        deadline: match.deadline_at,
      }}
    >
      <StageHead
        eyebrow="Scrim"
        title="Claim a side"
        lead="Two captains claim a side each, then a coinflip decides the pick order."
      />
      <div className="grid gap-4 sm:grid-cols-2">
        {sides.map((side) => {
          const team = teamOfSide(match, side);
          const captain = team ? match.captains[team] : null;
          return (
            <section
              key={side}
              aria-label={SIDE_NAME[side]}
              className={cn("flex flex-col gap-3 rounded-panel border-2 p-6", TEAM_CLASS[side].softBorder)}
            >
              <span className={cn("text-label font-bold", TEAM_CLASS[side].text)}>{SIDE_NAME[side]}</span>
              <span className={cn("font-display text-coin", TEAM_CLASS[side].text)}>
                {captain ? (team ? nameOf(match, team) : captain) : "Open"}
              </span>
              {captain ? (
                <span className="text-caption text-muted">Captain {captain}</span>
              ) : match.viewer.is_captain ? (
                <span className="text-caption text-muted">Waiting for another captain.</span>
              ) : (
                <Button
                  team={side}
                  onPress={() => claim(side)}
                  isPending={act.pending === "scrims.claim"}
                  pendingLabel="Claiming…"
                  className="self-start"
                >
                  Claim {SIDE_NAME[side]}
                </Button>
              )}
            </section>
          );
        })}
      </div>
    </Room>
  );
}
