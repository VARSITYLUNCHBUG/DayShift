import { Shuffle } from "@gravity-ui/icons";
import { Button, Card, Spinner } from "@heroui/react";
import { useState } from "react";

import { HeroGrid, heroTags } from "../../components/HeroGrid";
import { MatchShell } from "../../components/MatchShell";
import { TeamPanel } from "../../components/TeamPanel";
import { notify } from "../../components/toast";
import { TurnBanner } from "../../components/TurnBanner";
import { championSteps, TurnStrip } from "../../components/TurnStrip";
import { heroDraftLine, stepIndex, turnTitle } from "../../match/draft";
import { useAction } from "../../../live/hooks";
import type { MatchSnap } from "../../../live/types";
import type { MatchScreenProps } from "./types";

/** 2.7–2.9 Hero draft: your turn (pick from the grid, then lock in, or Random), the other
 * captain's turn, and watching. Scrims draft heroes on the same screen. */
export function HeroDraft({ match }: MatchScreenProps) {
  const turn = match.turn;
  const acting = match.viewer.is_acting && turn !== null && turn.action !== "player_pick";
  return (
    <MatchShell match={match} width="wide">
      {acting ? (
        // Keyed by step: a new turn starts with nothing selected.
        <ActingDraft key={match.champion_step ?? -1} match={match} />
      ) : (
        <>
          <TurnBanner line={heroDraftLine(match)} title={turnTitle(match)} deadline={match.deadline_at} showBar />
          <Board match={match} />
        </>
      )}
    </MatchShell>
  );
}

function ActingDraft({ match }: { match: MatchSnap }) {
  const action = useAction();
  const [selected, setSelected] = useState<string | null>(null);
  const turn = match.turn;
  const side = turn ? match.sides[turn.team] : null;
  const step = stepIndex(match);
  const choice = match.champions.find((c) => c.id === selected && !c.taken) ?? null;
  const verb = turn?.action === "ban" ? "Ban" : "Lock in";

  const lockIn = () => {
    if (step === null || !choice) return;
    action.run("draft.champion", { match_id: match.id, step_index: step, champion_id: choice.id }).catch(notify.error);
  };
  const random = () => {
    if (step === null) return;
    action.run("draft.random_champion", { match_id: match.id, step_index: step }).catch(notify.error);
  };

  const outline =
    side === "hk"
      ? "border-team-hk/40 text-team-hk-soft-foreground"
      : side === "am"
        ? "border-team-am/40 text-team-am-soft-foreground"
        : "border-border";
  return (
    <>
      <TurnBanner
        line={heroDraftLine(match)}
        title={turnTitle(match)}
        deadline={match.deadline_at}
        showBar
        tone={side ?? "accent"}
        actions={
          <>
            <Button
              variant="outline"
              size="lg"
              onPress={random}
              isDisabled={action.pending}
              className={`h-13 shrink-0 rounded-2xl bg-transparent px-4.5 font-semibold ${outline}`}
            >
              <Shuffle width={18} height={18} aria-hidden="true" />
              Random
            </Button>
            <Button
              size="lg"
              onPress={lockIn}
              isDisabled={!choice}
              isPending={action.pending}
              className={`h-13 min-w-0 flex-1 rounded-2xl px-5.5 font-bold sm:min-w-50 sm:flex-none ${
                choice ? "bg-success text-success-foreground hover:bg-success-hover" : ""
              }`}
            >
              {({ isPending }) => (
                <>
                  {isPending ? <Spinner color="current" size="sm" /> : null}
                  <span className="truncate">{choice ? `${verb} ${choice.name}` : verb}</span>
                </>
              )}
            </Button>
          </>
        }
      />
      <Board match={match} selectedId={choice?.id ?? null} onSelect={setSelected} />
    </>
  );
}

function Board({
  match,
  selectedId = null,
  onSelect,
}: {
  match: MatchSnap;
  selectedId?: string | null;
  onSelect?: (id: string) => void;
}) {
  const turnTeam = match.turn?.team ?? null;
  return (
    <>
      <TurnStrip steps={championSteps(match)} />
      <div className="flex flex-wrap items-start gap-5">
        <TeamPanel match={match} team="A" showHeroes highlight={turnTeam === "A"} />
        <Card aria-labelledby="heroes" className="min-w-0 flex-999 basis-140 gap-3.5 border border-border p-4.5">
          <h2 id="heroes" className="text-base font-bold">
            Heroes
          </h2>
          <HeroGrid champions={match.champions} tags={heroTags(match)} selectedId={selectedId} onSelect={onSelect} />
        </Card>
        <TeamPanel match={match} team="B" showHeroes highlight={turnTeam === "B"} />
      </div>
    </>
  );
}
