// The hero draft (B09–B12): the 18-step strip, every hero with search and "Only what we want",
// wish stickers on the cards. The captain on the clock chooses, then locks in (or takes a random
// hero); teammates press heroes to wish for them; spectators only watch (no chat, wishes or code).
import { Label, SearchField } from "@heroui/react";
import { useState } from "react";
import { ToggleButton } from "react-aria-components/ToggleButton";

import { Button } from "../../components/Button";
import { DraftStrip } from "../../components/DraftStrip";
import { HeroGrid } from "../../components/HeroGrid";
import type { HeroChoice } from "../../components/HeroGrid";
import { EmptyState } from "../../components/States";
import { TEAM_CLASS } from "../../components/team";
import { notify } from "../../components/toast";
import { cn } from "../../lib/cn";
import type { MatchSnap } from "../../live/protocol.gen";
import { useMatchAction } from "../../match/live";
import { heroDraftLine, heroStatus, heroStepNow, heroSteps, nameOf, teamKey, turnTitle, wishersByHero } from "../../match/model";
import { StageHead } from "./Parts";
import { Room, useMe } from "./Room";
import { SwapPanel } from "./TeamSheet";
import type { MatchScreenProps } from "./types";
import type { Wishes } from "./Wishes";
import { FULL_LINE, FULL_TITLE, TeamWants, useWishes, wishStickers } from "./Wishes";
import { InlineAlert } from "../../components/InlineAlert";

export function HeroDraft({ match }: MatchScreenProps) {
  const { myId } = useMe(match);
  const act = useMatchAction();
  const wishes = useWishes(match, myId);
  const turn = match.turn;
  const acting = match.viewer.is_acting && turn !== null && turn.action !== "player_pick";
  const tone = turn ? teamKey(match, turn.team) : null;
  const verb = turn?.action === "ban" ? "Ban" : "Lock in";
  // Your choice belongs to this step: a new step starts with nothing chosen.
  const [choice, setChoice] = useState<{ step: number; id: string } | null>(null);
  const chosen = choice?.step === match.step_index ? choice.id : null;
  const chosenName = match.champions.find((h) => h.id === chosen)?.name ?? null;
  const onTeam = match.viewer.is_player && match.viewer.team !== null;

  const lock = () => {
    if (!chosen) return;
    act.run("draft.champion", { match_id: match.id, step_index: match.step_index, champion_id: chosen }).catch(notify.error);
  };
  const random = () => {
    act.run("draft.random_champion", { match_id: match.id, step_index: match.step_index }).catch(notify.error);
  };

  const lockButton = acting ? (
    <Button
      team={tone}
      kind={turn.action === "ban" ? "danger-solid" : "primary"}
      isDisabled={!chosen || act.pending === "draft.random_champion"}
      onPress={lock}
      isPending={act.pending === "draft.champion"}
      pendingLabel={`${turn.action === "ban" ? "Banning" : "Locking in"} ${chosenName ?? ""}…`}
    >
      {chosenName ? `${verb} ${chosenName}` : `Choose a hero to ${verb.toLowerCase()}`}
    </Button>
  ) : null;
  const randomButton = acting ? (
    <Button
      kind="ghost"
      icon="dice"
      onPress={random}
      isDisabled={act.pending === "draft.champion"}
      isPending={act.pending === "draft.random_champion"}
      pendingLabel="Rolling…"
    >
      Random
    </Button>
  ) : null;

  const lead = acting
    ? turn.action === "ban"
      ? "Choose a hero to ban, then press Ban. No choice in time and one is picked at random."
      : "Choose a hero, then lock it in. No choice in time and one is picked at random."
    : onTeam && wishes.canWish
      ? "Press a hero to wish for it, press again to take it off. Stickers show who on your team wants a hero."
      : onTeam
        ? "Stickers show who on your team wants a hero."
        : undefined;

  return (
    <Room
      match={match}
      acting={turn?.team ?? null}
      heroes
      phaseLine={acting ? `Heroes · your ${turn.action === "ban" ? "ban" : "pick"}` : "Heroes"}
      now={{
        title: turnTitle(match),
        line: heroDraftLine(match),
        tone,
        deadline: match.deadline_at,
        announce: acting ? `to ${turn.action === "ban" ? "ban" : "pick"}` : undefined,
        action: acting ? (
          <>
            {randomButton}
            {lockButton}
          </>
        ) : undefined,
      }}
      footer={
        acting ? (
          <>
            {randomButton}
            {lockButton}
          </>
        ) : undefined
      }
      rail={
        onTeam ? (
          <>
            <section className="rounded-panel border border-line bg-surface p-5">
              <TeamWants match={match} myId={myId} wishes={wishes} heading="h2" />
            </section>
            <SwapPanel match={match} myId={myId} />
          </>
        ) : undefined
      }
    >
      <DraftStrip steps={heroSteps(match)} current={heroStepNow(match)} />
      <StageHead
        eyebrow={turn ? `${nameOf(match, turn.team)} · on the clock` : "Hero draft"}
        title="Heroes"
        lead={lead}
        tone={tone ? TEAM_CLASS[tone].text : undefined}
      />
      <Grid
        match={match}
        myId={myId}
        wishes={wishes}
        acting={acting}
        chosen={chosen}
        onChoose={(id) => setChoice({ step: match.step_index, id })}
      />
    </Room>
  );
}

function Grid({
  match,
  myId,
  wishes,
  acting,
  chosen,
  onChoose,
}: {
  match: MatchSnap;
  myId: string | null;
  wishes: Wishes;
  acting: boolean;
  chosen: string | null;
  onChoose: (id: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [onlyWanted, setOnlyWanted] = useState(false);
  const onTeam = match.viewer.is_player && match.viewer.team !== null;
  const status = heroStatus(match);
  const stickers = onTeam ? wishStickers(match, wishes.mine, myId) : new Map<string, string>();
  const wanted = new Set([...wishersByHero(match.wishes).keys(), ...wishes.mine]);
  const names = new Map(match.players.map((p) => [p.id, p.name]));
  const q = query.trim().toLowerCase();
  const shown = match.champions.filter(
    (hero) => (!q || hero.name.toLowerCase().includes(q)) && (!onlyWanted || wanted.has(hero.id)),
  );

  const heroes: HeroChoice[] = shown.map((hero) => {
    const s = status.get(hero.id);
    const state: HeroChoice["state"] =
      s?.kind === "banned" ? "banned" : s?.kind === "taken" ? (s.team ? teamKey(match, s.team) : "hk") : "free";
    const wishers = onTeam ? [...(wishersByHero(match.wishes).get(hero.id) ?? [])] : [];
    if (onTeam && myId && wishes.mine.includes(hero.id) && !wishers.includes(myId)) wishers.push(myId);
    const tag =
      s?.kind === "banned"
        ? "Banned"
        : s?.kind === "taken"
          ? s.team
            ? nameOf(match, s.team)
            : "Taken"
          : wishers.length
            ? `${wishers.map((id) => (id === myId ? "You" : (names.get(id) ?? "?"))).join(", ")} ${wishers.length === 1 && wishers[0] !== myId ? "wants" : "want"} it`
            : undefined;
    return {
      id: hero.id,
      name: hero.name,
      art: hero.icon_url,
      state,
      tag,
      tagTone: s?.kind === "banned" ? "danger" : s?.kind === "taken" && s.team ? teamKey(match, s.team) : "muted",
      wishes: stickers.get(hero.id) ?? null,
    };
  });

  // On the clock: pressing chooses. A teammate off the clock: pressing wishes. Otherwise read-only.
  const onSelect = acting ? onChoose : onTeam && wishes.canWish ? (id: string) => void wishes.toggle(id) : undefined;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end gap-2.5">
        <SearchField value={query} onChange={setQuery} className="min-w-0 flex-1 basis-60">
          <Label className="sr-only">Find a hero</Label>
          <SearchField.Group className="h-12">
            <SearchField.SearchIcon />
            <SearchField.Input placeholder="Find a hero" className="text-foreground placeholder:text-faint" />
            <SearchField.ClearButton />
          </SearchField.Group>
        </SearchField>
        {onTeam ? (
          <ToggleButton
            isSelected={onlyWanted}
            onChange={setOnlyWanted}
            className={cn(
              "inline-flex h-12 cursor-pointer items-center rounded-full border-2 px-5 text-body font-extrabold outline-none transition-state",
              onlyWanted ? "border-foreground bg-foreground text-background" : "border-line-strong",
            )}
          >
            Only what we want
          </ToggleButton>
        ) : null}
        <span role="status" className="text-caption font-semibold text-muted">
          {shown.length} of {match.champions.length}
        </span>
      </div>
      {!acting && wishes.full ? (
        <InlineAlert kind="info" title={FULL_TITLE}>
          {FULL_LINE}
        </InlineAlert>
      ) : null}
      {!acting && wishes.error ? <InlineAlert title={wishes.error} /> : null}
      {heroes.length ? (
        <HeroGrid
          heroes={heroes}
          selectedId={acting ? chosen : null}
          onSelect={onSelect}
          aria-label={acting ? "Heroes: choose one" : onSelect ? "Heroes: press to wish" : "Heroes"}
        />
      ) : (
        <EmptyState title="No heroes match">
          {onlyWanted ? "Clear the search or turn off Only what we want." : "Clear the search to see every hero."}
        </EmptyState>
      )}
    </div>
  );
}
