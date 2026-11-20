// Advanced (R10): every number for every player, in four sortable sets, and one player opened up:
// where their souls came from, their damage to each enemy, their build and their deaths. A row
// opens that player's numbers for this match only: profiles stay private.
import { useMemo } from "react";
import { useSearchParams } from "react-router";

import type { MatchDetail, PlayerLine, Postgame, YourNight } from "../../api/types";
import { Bar, StackedBar } from "../../components/Data";
import { Segmented } from "../../components/Navigation";
import { Panel } from "../../components/Layout";
import { Portrait } from "../../components/Portrait";
import { SortableTable } from "../../components/SortableTable";
import type { SortColumn } from "../../components/SortableTable";
import { TEAM_CLASS } from "../../components/team";
import { cn } from "../../lib/cn";
import { number } from "../../lib/format";
import { compact, gameClock, heroArt, share } from "../shared/format";
import type { Names } from "./model";
import { namesOf, playerBySlot, who } from "./model";

type SetName = "combat" | "economy" | "survival" | "builds";

const SETS: { id: SetName; label: string }[] = [
  { id: "combat", label: "Combat" },
  { id: "economy", label: "Economy" },
  { id: "survival", label: "Objectives and survival" },
  { id: "builds", label: "Builds" },
];

const SOURCE_LABEL = { troopers: "Troopers", players: "Kills", neutrals: "Neutrals", bosses: "Objectives", treasure: "Other" } as const;
const SOURCE_TONE = { troopers: "text", players: "hk", neutrals: "muted", bosses: "am", treasure: "muted" } as const;

/** The item's name from the shop catalogue, or "Item 1998374645" for one it doesn't know yet. */
export function itemName(doc: Postgame, id: number): string {
  return doc.item_names[String(id)] ?? `Item ${id}`;
}

function columnsFor(set: SetName, open: (slot: number) => void): SortColumn<PlayerLine>[] {
  const player: SortColumn<PlayerLine> = {
    key: "player",
    header: "Player",
    isRowHeader: true,
    sortValue: (row) => row.name,
    cell: (row) => (
      <button type="button" onClick={() => open(row.slot)} className="flex min-h-11 items-center gap-3 rounded-row text-left">
        <Portrait hero={row.hero} src={heroArt(row.hero_slug)} team={row.team} size="sm" />
        <span className="flex flex-col">
          <b className="text-label font-extrabold">{row.name}</b>
          <span className="text-micro text-muted">{row.hero}</span>
        </span>
        <span className="sr-only">: open their numbers</span>
      </button>
    ),
  };
  const num = (key: string, header: string, value: (row: PlayerLine) => number | null, show: (v: number) => string = number): SortColumn<PlayerLine> => ({
    key,
    header,
    align: "right",
    sortValue: (row) => value(row) ?? -1,
    cell: (row) => {
      const v = value(row);
      return v === null ? "–" : show(v);
    },
  });
  switch (set) {
    case "combat":
      return [
        player,
        num("kills", "K", (r) => r.kills),
        num("deaths", "D", (r) => r.deaths),
        num("assists", "A", (r) => r.assists),
        num("kda", "KDA", (r) => r.kda, (v) => v.toFixed(1)),
        num("damage", "Hero damage", (r) => r.damage, compact),
        num("dpm", "Per min", (r) => r.damage_per_min),
        num("accuracy", "Accuracy", (r) => r.accuracy, share),
        num("crit", "Headshots", (r) => r.crit_rate, share),
      ];
    case "economy":
      return [
        player,
        num("souls", "Souls", (r) => r.souls, compact),
        num("spm", "Per min", (r) => r.souls_per_min),
        num("last_hits", "Last hits", (r) => r.last_hits),
        num("denies", "Denies", (r) => r.denies),
        num("level", "Level", (r) => r.level),
      ];
    case "survival":
      return [
        player,
        num("objective", "Objective damage", (r) => r.objective_damage, compact),
        num("taken", "Taken", (r) => r.taken, compact),
        num("mitigated", "Shrugged off", (r) => r.mitigated, compact),
        num("healing", "Healing", (r) => r.healing, compact),
        num("dead", "Time dead", (r) => r.time_dead_s, gameClock),
      ];
    case "builds":
      return [
        player,
        num("items", "Items bought", (r) => r.build.length),
        num("sold", "Sold", (r) => r.build.filter((b) => b.sold_t !== null).length),
        num("last", "Last buy", (r) => r.build.at(-1)?.t ?? null, gameClock),
      ];
  }
}

function PlayerPanel({ line, doc, names }: { line: PlayerLine; doc: Postgame; names: Names }) {
  const slots = playerBySlot(doc);
  const sources = Object.entries(line.sources) as [keyof typeof SOURCE_LABEL, number][];
  const total = Math.max(1, sources.reduce((sum, [, v]) => sum + v, 0));
  const topDamage = Math.max(1, ...line.damage_to.map((d) => d.damage));
  const deaths = doc.deaths.filter((death) => death.victim === line.slot);
  const rank = [...doc.players].sort((a, b) => b.damage_per_min - a.damage_per_min).findIndex((p) => p.slot === line.slot) + 1;
  return (
    <Panel as="section" aria-labelledby="player-heading" className="flex flex-col gap-5 p-6">
      <div className="flex flex-wrap items-center gap-4">
        <Portrait hero={line.hero} src={heroArt(line.hero_slug)} team={line.team} size="lg" />
        <div className="flex min-w-0 flex-1 basis-44 flex-col">
          <h3 id="player-heading" tabIndex={-1} className="type-display text-coin outline-none">
            {line.name}
          </h3>
          <span className={cn("text-label font-bold", TEAM_CLASS[line.team].text)}>
            {line.hero} · {names.side[line.team]} · level {line.level}
          </span>
        </div>
        <div className="flex flex-col rounded-card bg-background px-4 py-3 max-sm:basis-full">
          <span className="text-micro font-bold text-muted">Damage per minute</span>
          <b className="type-display text-stat tabular-nums">{number(line.damage_per_min)}</b>
          <span className="text-micro font-bold text-muted">
            {rank} of {doc.players.length} in the match
          </span>
        </div>
      </div>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <section className="flex flex-col gap-2.5">
          <h4 className="text-body font-extrabold">Where the souls came from</h4>
          <StackedBar parts={sources.map(([key, v]) => ({ share: v / total, tone: SOURCE_TONE[key] }))} />
          <ul className="flex flex-col gap-1">
            {sources.map(([key, v]) => (
              <li key={key} className="flex justify-between gap-3 text-label tabular-nums">
                <span>{SOURCE_LABEL[key]}</span>
                <span className="font-bold">
                  {compact(v)} · {Math.round((v / total) * 100)}%
                </span>
              </li>
            ))}
          </ul>
        </section>
        <section className="flex flex-col gap-2.5">
          <h4 className="text-body font-extrabold">Hero damage to each enemy</h4>
          <ul className="flex flex-col gap-2">
            {line.damage_to.map((hit) => {
              const foe = slots.get(hit.slot);
              return (
                <li key={hit.slot} className="flex flex-col gap-1">
                  <span className="flex justify-between gap-3 text-label tabular-nums">
                    <span>
                      <b>{foe?.name ?? "Someone"}</b> <span className="text-muted">({foe?.hero})</span>
                    </span>
                    <b>{compact(hit.damage)}</b>
                  </span>
                  <Bar value={hit.damage} max={topDamage} tone={foe?.team ?? "muted"} />
                </li>
              );
            })}
          </ul>
        </section>
        <section className="flex flex-col gap-2.5">
          <h4 className="text-body font-extrabold">Build, in the order it was bought</h4>
          <ol className="flex flex-col gap-1">
            {line.build.map((buy, index) => (
              <li key={`${buy.item_id}-${index}`} className={cn("flex justify-between gap-3 text-label tabular-nums", buy.sold_t !== null && "text-muted")}>
                <span>
                  <span className="font-bold text-muted">{gameClock(buy.t)}</span> {itemName(doc, buy.item_id)}
                </span>
                {buy.sold_t !== null ? <span className="text-caption">sold {gameClock(buy.sold_t)}</span> : null}
              </li>
            ))}
          </ol>
          <p className="text-caption text-muted">Faded items were sold. An item the game added since our last look shows its number.</p>
        </section>
      </div>
      <section className="flex flex-col gap-2">
        <h4 className="text-body font-extrabold">Deaths</h4>
        {deaths.length === 0 ? (
          <p className="text-label text-muted">Didn&apos;t die once.</p>
        ) : (
          <ul className="flex flex-wrap gap-x-5 gap-y-1">
            {deaths.map((death, index) => (
              <li key={index} className="text-label tabular-nums">
                <span className="font-bold text-muted">{gameClock(death.t)}</span> · {who(death.killer !== null ? slots.get(death.killer) : undefined, true)}
              </li>
            ))}
          </ul>
        )}
      </section>
    </Panel>
  );
}

interface Props {
  detail: MatchDetail;
  doc: Postgame;
  you: YourNight | null;
}

export default function Advanced({ detail, doc, you }: Props) {
  const [params, setParams] = useSearchParams();
  const names = useMemo(() => namesOf(detail, doc), [detail, doc]);
  const rawSet = params.get("set");
  const set: SetName = SETS.some((s) => s.id === rawSet) ? (rawSet as SetName) : "combat";
  const slot = Number(params.get("slot") ?? you?.slot ?? doc.players[0]?.slot ?? 0);
  const line = playerBySlot(doc).get(slot) ?? doc.players[0];
  const update = (next: Record<string, string>) => setParams({ set, slot: String(slot), ...next }, { replace: true, preventScrollReset: true });
  const open = (s: number) => {
    update({ slot: String(s) });
    requestAnimationFrame(() => document.getElementById("player-heading")?.focus());
  };
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center gap-4">
        <h2 className="text-title max-md:text-coin">Advanced</h2>
        <Segmented label="Numbers" value={set} onChange={(next) => update({ set: next })} options={SETS} />
      </div>
      <SortableTable
        columns={columnsFor(set, open)}
        rows={doc.players}
        rowKey={(row) => String(row.slot)}
        caption={`${SETS.find((s) => s.id === set)?.label ?? ""} for all ${doc.players.length} players`}
        initialSort={set === "combat" ? "damage" : set === "economy" ? "souls" : set === "survival" ? "objective" : "items"}
        highlight={(row) => row.slot === line?.slot}
        rowClass={(row) => TEAM_CLASS[row.team].soft}
      />
      {line ? <PlayerPanel line={line} doc={doc} names={names} /> : null}
    </div>
  );
}
