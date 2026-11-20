// The timeline (R08): the soul or kill lead over the match, every objective and fight on it, and
// the moment you pick: the lead then, who died around it, and Watch from here.
import { ToggleButton } from "react-aria-components";
import { useId, useMemo, useState } from "react";
import { useSearchParams } from "react-router";

import type { MatchDetail, Postgame, YourNight } from "../../api/types";
import { ButtonLink } from "../../components/Button";
import { Segmented } from "../../components/Navigation";
import { Panel } from "../../components/Layout";
import { TEAM_CLASS } from "../../components/team";
import { cn } from "../../lib/cn";
import { gameClock } from "../shared/format";
import { CHART_H, CHART_W, leadGeometry } from "./leadGeometry";
import type { Moment } from "./model";
import { killsBy, leadAt, leadText, moments, namesOf, OBJECTIVE_LETTER, playerBySlot, who } from "./model";

type Unit = "souls" | "kills";
type Filter = "objective" | "kill" | "fight";

const FILTERS: { id: Filter; label: string }[] = [
  { id: "objective", label: "Objectives" },
  { id: "kill", label: "Kills" },
  { id: "fight", label: "Fights" },
];

function filterOf(moment: Moment): Filter {
  return moment.kind === "mid_boss" ? "objective" : moment.kind;
}

/** A moment's letter on the chart: an objective's, F for a fight, K for first blood, M for the
 * Mid Boss. */
function markOf(moment: Moment, doc: Postgame, refs: Map<Moment, number>): string {
  if (moment.kind === "fight") return "F";
  if (moment.kind === "kill") return "K";
  if (moment.kind === "mid_boss") return "M";
  const objective = doc.objectives[refs.get(moment) ?? -1];
  return objective ? OBJECTIVE_LETTER[objective.kind] : "O";
}

interface Props {
  detail: MatchDetail;
  doc: Postgame;
  you: YourNight | null;
}

export default function Timeline({ detail, doc }: Props) {
  const id = useId().replace(/:/g, "");
  const [params, setParams] = useSearchParams();
  const names = useMemo(() => namesOf(detail, doc), [detail, doc]);
  const all = useMemo(() => moments(doc, names), [doc, names]);
  const refs = useMemo(() => new Map(all.map((moment, index) => [moment, doc.events[index]?.ref ?? -1])), [all, doc.events]);
  const [unit, setUnit] = useState<Unit>("souls");
  const [filters, setFilters] = useState<ReadonlySet<Filter>>(new Set(["objective", "kill", "fight"]));
  const slots = playerBySlot(doc);

  const asked = Number(params.get("t"));
  const t = Number.isFinite(asked) && params.has("t") ? Math.max(0, Math.min(doc.duration_s, asked)) : (all[0]?.t ?? 0);
  const select = (next: number) => setParams({ t: String(Math.round(next)) }, { replace: true, preventScrollReset: true });

  const series = unit === "souls" ? doc.timeline.souls : doc.timeline.kills;
  const geometry = leadGeometry(doc.timeline.t, series, doc.duration_s);
  const shown = all.filter((moment) => filters.has(filterOf(moment)));
  const selected = all.find((moment) => moment.t === t) ?? null;
  const soul = leadAt(doc, t, "souls");
  const kills = killsBy(doc, t);
  const around = doc.deaths.filter((death) => death.t >= t - 20 && death.t <= t + 30);
  const pct = (x: number) => `${((x / CHART_W) * 100).toFixed(2)}%`;
  const unitWord = unit === "souls" ? "Soul lead" : "Kill lead";

  return (
    <div className="flex flex-wrap items-start gap-x-8 gap-y-6">
      <div className="flex min-w-0 flex-999 basis-160 flex-col gap-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-4">
            <h2 className="text-title max-md:text-coin">Timeline</h2>
            <Segmented
              label="Lead"
              value={unit}
              onChange={setUnit}
              options={[
                { id: "souls", label: "Soul lead" },
                { id: "kills", label: "Kill lead" },
              ]}
            />
          </div>
          <div role="group" aria-label="Show on the timeline" className="flex flex-wrap gap-2">
            {FILTERS.map((filter) => (
              <ToggleButton
                key={filter.id}
                isSelected={filters.has(filter.id)}
                onChange={(on) =>
                  setFilters((old) => {
                    const next = new Set(old);
                    if (on) next.add(filter.id);
                    else next.delete(filter.id);
                    return next;
                  })
                }
                className="flex h-11 cursor-pointer items-center rounded-full border-2 border-line-strong px-4 text-label font-extrabold text-foreground outline-none transition-state focus-visible:ring-3 focus-visible:ring-brand focus-visible:ring-offset-2 focus-visible:ring-offset-background data-selected:border-foreground data-selected:bg-foreground data-selected:text-background"
              >
                {filter.label}
              </ToggleButton>
            ))}
          </div>
        </div>

        <Panel className="flex flex-col gap-2 p-4">
          <div className="relative h-72 max-md:h-48">
            <div role="img" aria-label={`${unitWord} over the match: ${leadText(series.at(-1) ?? 0, names, unit)} at the end.`} className="absolute inset-0">
              <svg viewBox={`0 0 ${CHART_W} ${CHART_H}`} preserveAspectRatio="none" width="100%" height="100%" aria-hidden="true" className="block">
                <defs>
                  <clipPath id={`${id}-top`}>
                    <rect x="0" y="0" width={CHART_W} height={CHART_H / 2} />
                  </clipPath>
                  <clipPath id={`${id}-bottom`}>
                    <rect x="0" y={CHART_H / 2} width={CHART_W} height={CHART_H / 2} />
                  </clipPath>
                </defs>
                {geometry.grid.map((mark) => (
                  <line key={mark.t} x1={mark.x} x2={mark.x} y1="0" y2={CHART_H} className="stroke-line" strokeWidth="1" vectorEffect="non-scaling-stroke" />
                ))}
                <path d={geometry.area} className="fill-team-hk" fillOpacity="0.32" clipPath={`url(#${id}-top)`} />
                <path d={geometry.area} className="fill-team-am" fillOpacity="0.32" clipPath={`url(#${id}-bottom)`} />
                <line x1="0" x2={CHART_W} y1={CHART_H / 2} y2={CHART_H / 2} className="stroke-line-strong" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
                {filters.has("kill")
                  ? doc.deaths.map((death, index) => {
                      const victim = slots.get(death.victim);
                      const up = victim?.team === "am";
                      return (
                        <line
                          key={index}
                          x1={geometry.x(death.t)}
                          x2={geometry.x(death.t)}
                          y1={up ? 0 : CHART_H}
                          y2={up ? 12 : CHART_H - 12}
                          className={up ? "stroke-team-hk" : "stroke-team-am"}
                          strokeWidth="2"
                          vectorEffect="non-scaling-stroke"
                        />
                      );
                    })
                  : null}
                <path d={geometry.line} fill="none" className="stroke-foreground" strokeWidth="2.5" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
              </svg>
            </div>
            <span aria-hidden="true" className="absolute top-0 bottom-0 w-1 -translate-x-1/2 rounded-full bg-foreground" style={{ left: pct(geometry.x(t)) }} />
            {shown.map((moment, index) => {
              const up = moment.side !== "am";
              return (
                <button
                  key={`${moment.t}-${index}`}
                  type="button"
                  onClick={() => select(moment.t)}
                  aria-label={`${gameClock(moment.t)}: ${moment.title}`}
                  aria-pressed={moment.t === t}
                  className={cn(
                    "absolute flex size-7 -translate-x-1/2 items-center justify-center rounded-full text-micro font-extrabold shadow-sticker transition-state focus-visible:z-10",
                    moment.side ? TEAM_CLASS[moment.side].fill : "bg-raised text-foreground",
                    up ? "top-4" : "bottom-4",
                    moment.t === t && "ring-3 ring-foreground",
                  )}
                  style={{ left: pct(geometry.x(moment.t)) }}
                >
                  {markOf(moment, doc, refs)}
                </button>
              );
            })}
          </div>
          <div aria-hidden="true" className="relative h-5 text-micro font-semibold text-muted tabular-nums">
            <span className="absolute left-0">0:00</span>
            {geometry.grid.map((mark) => (
              <span key={mark.t} className="absolute -translate-x-1/2" style={{ left: pct(mark.x) }}>
                {gameClock(mark.t)}
              </span>
            ))}
          </div>
        </Panel>
        <p className="text-label text-muted">
          Above the line, {names.side.hk} lead; below, {names.side.am}. Moments sit on the side that won them: G Guardian, W Walker, B Base Guardian,
          S Shrine, P Patron, M Mid Boss, F fight, K first blood. Pick one to see it.
        </p>

        <section aria-labelledby="every-moment" className="flex flex-col gap-3">
          <h2 id="every-moment" className="text-section">
            Every moment
          </h2>
          {shown.length === 0 ? (
            <p className="text-label text-muted">Nothing to show with these filters.</p>
          ) : (
            <ol className="flex flex-col gap-1.5">
              {shown.map((moment, index) => (
                <li key={`${moment.t}-${index}`}>
                  <button
                    type="button"
                    onClick={() => select(moment.t)}
                    aria-current={moment.t === t ? "true" : undefined}
                    className={cn(
                      "flex min-h-11 w-full items-baseline gap-4 rounded-row border px-4 py-2.5 text-left transition-state",
                      moment.t === t ? "border-foreground bg-raised" : "border-line bg-surface hover:border-line-strong",
                    )}
                  >
                    <span className="w-12 shrink-0 text-caption font-bold text-muted tabular-nums">{gameClock(moment.t)}</span>
                    <span className="flex min-w-0 flex-col">
                      <b className={cn("text-body font-extrabold", moment.side ? TEAM_CLASS[moment.side].text : "text-foreground")}>{moment.title}</b>
                      <span className="text-label text-muted">{moment.text}</span>
                    </span>
                  </button>
                </li>
              ))}
            </ol>
          )}
        </section>
      </div>

      <aside aria-label="The moment you picked" aria-live="polite" className="flex min-w-0 flex-1 basis-80 flex-col gap-4 rounded-panel border border-line bg-surface p-5 md:sticky md:top-4">
        <span className="text-caption font-bold text-muted tabular-nums">{gameClock(t)}</span>
        <h2 className="text-sheet">{selected?.title ?? `At ${gameClock(t)}`}</h2>
        {selected ? <p className="text-label text-muted">{selected.text}</p> : null}
        <div className="grid grid-cols-2 gap-2.5">
          <div className="flex flex-col gap-1 rounded-card bg-background p-3">
            <span className="text-micro font-bold text-muted">Soul lead</span>
            <b className="type-display text-card tabular-nums">{leadText(soul, names, "souls")}</b>
          </div>
          <div className="flex flex-col gap-1 rounded-card bg-background p-3">
            <span className="text-micro font-bold text-muted">Kills</span>
            <b className="type-display text-card tabular-nums">
              <span className="text-team-hk">{kills.hk}</span>
              <span className="text-faint"> – </span>
              <span className="text-team-am">{kills.am}</span>
            </b>
          </div>
        </div>
        <div className="flex flex-col gap-1.5">
          <b className="text-label font-extrabold">{around.length ? `${around.length} ${around.length === 1 ? "death" : "deaths"} around then` : "No deaths around then"}</b>
          <ul className="flex flex-col gap-1">
            {around.slice(0, 8).map((death, index) => (
              <li key={index} className="text-caption text-muted tabular-nums">
                <span className="font-bold">{gameClock(death.t)}</span> {who(death.killer !== null ? slots.get(death.killer) : undefined)} killed {who(slots.get(death.victim), true)}
              </li>
            ))}
          </ul>
        </div>
        <ButtonLink to={`/matches/${detail.id}/replay?t=${Math.max(0, t - 10)}`} icon="replay" fullWidth>
          Watch from here
        </ButtonLink>
      </aside>
    </div>
  );
}
