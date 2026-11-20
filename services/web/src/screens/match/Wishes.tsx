// Hero wishes (D10): up to three heroes each player wants, ranked, seen by their own team only.
// Edited from the team sheet, the hero grid and the phone's team chat; shown straight away, then
// put right by the next snapshot.
import { Label, SearchField } from "@heroui/react";
import { useState } from "react";

import { Button, IconButton } from "../../components/Button";
import { HeroCard } from "../../components/HeroCard";
import { InlineAlert } from "../../components/InlineAlert";
import { PickGrid } from "../../components/PickGrid";
import { Portrait } from "../../components/Portrait";
import { TEAM_CLASS } from "../../components/team";
import { errorText } from "../../components/toast";
import { cn } from "../../lib/cn";
import { initials } from "../../lib/format";
import type { ChampionChoice, MatchSnap } from "../../live/protocol.gen";
import { useMatchAction } from "../../match/live";
import { heroById, heroStatus, MAX_WISHES, nameOf, teamKey, teamPlayers, toggleWish, wishesOf } from "../../match/model";
import type { HeroStatus } from "../../match/model";

export const FULL_TITLE = "You have three wishes already";
export const FULL_LINE = "Take one off first, then add another.";

export interface Wishes {
  /** Your wishes, most wanted first, as you last set them (before the server says so). */
  mine: string[];
  canWish: boolean;
  /** Adds the hero, or takes it off if it's there. False (and `full` set) for a fourth. */
  toggle: (heroId: string) => boolean;
  remove: (heroId: string) => void;
  /** You tried a fourth. */
  full: boolean;
  error: string | null;
  pending: boolean;
}

/** Your wishes, optimistic: what you pressed shows at once; the ack arrives after the snapshot
 * that has it, so the server's list takes over then. A refusal puts the server's list back. */
export function useWishes(match: MatchSnap, myId: string | null): Wishes {
  const act = useMatchAction();
  const server = wishesOf(match.wishes, myId);
  const [local, setLocal] = useState<string[] | null>(null);
  const [full, setFull] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mine = local ?? server;
  const canWish = match.viewer.can_wish && myId !== null;

  const send = (next: string[]) => {
    setLocal(next);
    setError(null);
    act.run("wish.set", { match_id: match.id, champion_ids: next }).then(
      () => setLocal((current) => (current === next ? null : current)),
      (reason: unknown) => {
        setLocal((current) => (current === next ? null : current));
        setError(errorText(reason));
      },
    );
  };

  return {
    mine,
    canWish,
    full,
    error,
    pending: act.pending === "wish.set",
    toggle: (heroId) => {
      if (!canWish) return false;
      const next = toggleWish(mine, heroId);
      if (next === null) {
        setFull(true);
        return false;
      }
      setFull(false);
      send(next);
      return true;
    },
    remove: (heroId) => {
      if (!canWish) return;
      setFull(false);
      send(mine.filter((id) => id !== heroId));
    },
  };
}

function statusLine(status: HeroStatus | undefined, match: MatchSnap): string | null {
  if (!status || status.kind === "free") return null;
  if (status.kind === "banned") return "Banned";
  if (status.team && status.team === match.viewer.team) return "Ours";
  return status.team ? `Taken by ${nameOf(match, status.team)}` : "Taken";
}

/** A wished-for hero as a pill: portrait, name, and Banned or Taken struck through. */
function WishChip({
  match,
  hero,
  status,
  rank,
  onRemove,
}: {
  match: MatchSnap;
  hero: ChampionChoice;
  status: HeroStatus | undefined;
  rank?: number;
  onRemove?: () => void;
}) {
  const gone = status && status.kind !== "free";
  const ours = status?.kind === "taken" && status.team === match.viewer.team;
  const line = statusLine(status, match);
  const team = match.viewer.team ? teamKey(match, match.viewer.team) : null;
  return (
    <li
      className={cn(
        "flex min-h-11 items-center gap-2 rounded-full border-2 py-1 pr-1.5 pl-1.5",
        ours && team ? TEAM_CLASS[team].border : "border-line-strong",
        onRemove ? "pr-0.5" : "pr-3",
      )}
    >
      {rank ? <span className="pl-1 text-micro font-extrabold text-muted">{rank}</span> : null}
      <Portrait hero={hero.name} src={hero.icon_url} size="sm" team={ours ? team : null} />
      <span className={cn("text-caption font-extrabold", gone && !ours && "text-muted line-through")}>{hero.name}</span>
      {line ? (
        <span className={cn("text-micro font-bold", status?.kind === "banned" ? "text-danger" : "text-muted")}>{line}</span>
      ) : null}
      {onRemove ? <IconButton icon="close" kind="quiet" label={`Take ${hero.name} off your wishes`} onPress={onRemove} /> : null}
    </li>
  );
}

/** Your team's wishes, player by player (B08 "Rook's Team wants", B09 "Your team wants"). Only
 * your team sees them. */
export function TeamWants({
  match,
  myId,
  wishes,
  heading = "h2",
}: {
  match: MatchSnap;
  myId: string | null;
  wishes: Wishes;
  heading?: "h2" | "h3";
}) {
  const team = match.viewer.team;
  if (!team) return null;
  const heroes = heroById(match);
  const status = heroStatus(match);
  const H = heading;
  const key = teamKey(match, team);
  return (
    <section aria-label={`${nameOf(match, team)} wants`} className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <H className={cn("text-section", TEAM_CLASS[key].text)}>{nameOf(match, team)} wants</H>
        <span className="text-caption font-semibold text-muted">
          Only you and your teammates see this. {nameOf(match, team === "A" ? "B" : "A")} can&apos;t.
        </span>
      </div>
      <ul className="flex flex-col divide-y divide-line">
        {teamPlayers(match, team).map((p) => {
          const isYou = p.id === myId;
          const ids = isYou ? wishes.mine : wishesOf(match.wishes, p.id);
          return (
            <li
              key={p.id}
              className={cn(
                "flex flex-wrap items-center gap-x-4 gap-y-2 px-3 py-2.5",
                isYou && cn(TEAM_CLASS[key].soft, "rounded-row"),
              )}
            >
              <span className="flex w-40 min-w-0 items-center gap-2 font-bold">
                <span className="truncate">{p.name}</span>
                {isYou ? <span className="text-micro font-semibold text-muted">you</span> : null}
              </span>
              {ids.length ? (
                <ul aria-label={`${p.name}'s wishes`} className="flex flex-wrap gap-2">
                  {ids.map((id, index) => {
                    const hero = heroes.get(id);
                    return hero ? (
                      <WishChip
                        key={id}
                        match={match}
                        hero={hero}
                        status={status.get(id)}
                        rank={index + 1}
                        onRemove={isYou && wishes.canWish ? () => wishes.remove(id) : undefined}
                      />
                    ) : null;
                  })}
                </ul>
              ) : (
                <span className="text-caption text-faint">{isYou ? "No wishes yet" : "Nothing yet"}</span>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/** Your wishes: the chips, and a hero picker to add more ("Press a hero to add it, press again
 * to take it off"). Compact on the phone's chat view. */
export function WishesEditor({
  match,
  myId,
  wishes: given,
  compact = false,
}: {
  match: MatchSnap;
  myId: string | null;
  wishes?: Wishes;
  compact?: boolean;
}) {
  const own = useWishes(match, myId);
  const wishes = given ?? own;
  const [picking, setPicking] = useState(!compact);
  const heroes = heroById(match);
  const status = heroStatus(match);
  const count = `${wishes.mine.length} of ${MAX_WISHES}`;
  return (
    <section aria-label="Your wishes" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className={compact ? "text-card" : "text-section"}>Your wishes</h2>
        <span className="text-caption font-bold">{count}</span>
      </div>
      <p className="text-caption text-muted">
        {wishes.canWish
          ? compact
            ? "Up to 3 heroes. Only your captain and teammates see them."
            : "Press a hero to add it, press again to take it off. You can change them until the hero draft ends."
          : "Wishes are read-only now."}
      </p>
      {compact && wishes.mine.length ? (
        <ul aria-label="Your wishes, most wanted first" className="flex flex-wrap gap-2">
          {wishes.mine.map((id, index) => {
            const hero = heroes.get(id);
            return hero ? (
              <WishChip
                key={id}
                match={match}
                hero={hero}
                status={status.get(id)}
                rank={index + 1}
                onRemove={wishes.canWish ? () => wishes.remove(id) : undefined}
              />
            ) : null;
          })}
        </ul>
      ) : null}
      {wishes.full ? (
        <InlineAlert kind="info" title={FULL_TITLE}>
          {FULL_LINE}
        </InlineAlert>
      ) : null}
      {wishes.error ? <InlineAlert title={wishes.error} /> : null}
      {wishes.canWish ? (
        compact && !picking ? (
          <Button kind="ghost" size="sm" icon="wish" onPress={() => setPicking(true)} className="self-start">
            Add a hero
          </Button>
        ) : (
          <WishPicker match={match} wishes={wishes} compact={compact} onDone={compact ? () => setPicking(false) : undefined} />
        )
      ) : null}
    </section>
  );
}

/** Every hero to wish for, searchable: your wishes carry their rank. */
function WishPicker({
  match,
  wishes,
  compact,
  onDone,
}: {
  match: MatchSnap;
  wishes: Wishes;
  compact: boolean;
  onDone?: () => void;
}) {
  const [query, setQuery] = useState("");
  const status = heroStatus(match);
  const shown = match.champions.filter((hero) => hero.name.toLowerCase().includes(query.trim().toLowerCase()));
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-end gap-2">
        <SearchField value={query} onChange={setQuery} className="min-w-0 flex-1 basis-56">
          <Label className="sr-only">Find a hero</Label>
          <SearchField.Group className="h-11">
            <SearchField.SearchIcon />
            <SearchField.Input placeholder="Find a hero" className="text-foreground placeholder:text-faint" />
            <SearchField.ClearButton />
          </SearchField.Group>
        </SearchField>
        {onDone ? (
          <Button kind="quiet" size="sm" onPress={onDone}>
            Done
          </Button>
        ) : null}
      </div>
      <PickGrid
        aria-label="Heroes to wish for"
        items={shown}
        getKey={(hero) => hero.id}
        getLabel={(hero) => {
          const rank = wishes.mine.indexOf(hero.id);
          const line = statusLine(status.get(hero.id), match);
          return [hero.name, rank >= 0 ? `your wish ${rank + 1}` : null, line].filter(Boolean).join(", ");
        }}
        selectedKey={null}
        onSelect={(id) => wishes.toggle(id)}
        columns={compact ? "grid-cols-4 sm:grid-cols-6" : "grid-cols-4 sm:grid-cols-6 lg:grid-cols-8 xl:grid-cols-10"}
        className="gap-2"
        renderItem={(hero) => {
          const rank = wishes.mine.indexOf(hero.id);
          const s = status.get(hero.id);
          return (
            <HeroCard
              name={hero.name}
              art={hero.icon_url}
              state={s?.kind === "banned" ? "banned" : rank >= 0 ? "selected" : "free"}
              wishes={rank >= 0 ? String(rank + 1) : null}
              tag={statusLine(s, match)}
              tagTone={s?.kind === "banned" ? "danger" : "muted"}
            />
          );
        }}
      />
    </div>
  );
}

/** The initials of everyone on your team who wants each hero, for the hero grid's stickers:
 * "PK", "PK RK". */
export function wishStickers(match: MatchSnap, mine: readonly string[], myId: string | null): Map<string, string> {
  const names = new Map(match.players.map((p) => [p.id, initials(p.name)]));
  const by = new Map<string, string[]>();
  const add = (heroId: string, playerId: string) => {
    const list = by.get(heroId) ?? [];
    if (!list.includes(playerId)) list.push(playerId);
    by.set(heroId, list);
  };
  for (const wish of [...match.wishes].sort((a, b) => a.rank - b.rank)) {
    if (wish.player_id !== myId) add(wish.champion_id, wish.player_id);
  }
  if (myId) for (const id of mine) add(id, myId);
  return new Map([...by].map(([hero, ids]) => [hero, ids.map((id) => names.get(id) ?? "?").join(" ")]));
}
