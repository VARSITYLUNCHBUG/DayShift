// The replay (R09): every hero on the overview map every few seconds, in their team's ring,
// greyed with an × while dead. Starts paused; plays at 10, 30 or 60 times speed; steps instead of
// gliding with reduced motion. No game footage, no GIF: positions only.
import { useEffect, useMemo, useRef, useState } from "react";
import { ToggleButton } from "react-aria-components";
import { useSearchParams } from "react-router";

import type { MatchDetail, Postgame, YourNight } from "../../api/types";
import { Button, IconButton } from "../../components/Button";
import { Segmented } from "../../components/Navigation";
import { Panel } from "../../components/Layout";
import { Portrait } from "../../components/Portrait";
import { cn } from "../../lib/cn";
import { useMediaQuery } from "../../lib/useMediaQuery";
import { gameClock, heroArt } from "../shared/format";
import { killsBy, leadAt, leadText, moments, namesOf, playerBySlot, who } from "./model";
import { placeAll } from "./replayModel";

const SPEEDS = [10, 30, 60] as const;
type Speed = (typeof SPEEDS)[number];

/** The minimap, from the postgame document's own static asset (league/static/postgame/). */
export const MINIMAP_URL = "/static/postgame/minimap.png";

const TOGGLE =
  "flex h-11 cursor-pointer items-center rounded-full border-2 border-line-strong px-4 text-label font-extrabold text-foreground outline-none transition-state focus-visible:ring-3 focus-visible:ring-brand focus-visible:ring-offset-2 focus-visible:ring-offset-background data-selected:border-foreground data-selected:bg-foreground data-selected:text-background";

interface Props {
  detail: MatchDetail;
  doc: Postgame;
  you: YourNight | null;
}

export default function Replay({ detail, doc, you }: Props) {
  const [params] = useSearchParams();
  const asked = Number(params.get("t"));
  const duration = doc.duration_s;
  const [t, setT] = useState(() => (params.has("t") && Number.isFinite(asked) ? Math.max(0, Math.min(duration, asked)) : 0));
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState<Speed>(30);
  const [ringMe, setRingMe] = useState(true);
  const [showNames, setShowNames] = useState(false);
  const reduced = useMediaQuery("(prefers-reduced-motion: reduce)");
  const names = useMemo(() => namesOf(detail, doc), [detail, doc]);
  const slots = useMemo(() => playerBySlot(doc), [doc]);
  const marks = useMemo(() => moments(doc, names), [doc, names]);
  const last = useRef<number | null>(null);

  // The clock: while playing, game time moves `speed` times as fast as real time.
  useEffect(() => {
    if (!playing) return;
    let frame = 0;
    last.current = null;
    const tick = (now: number) => {
      const before = last.current ?? now;
      last.current = now;
      setT((old) => {
        const next = Math.min(duration, old + ((now - before) / 1000) * speed);
        if (next >= duration) setPlaying(false);
        return next;
      });
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, speed, duration]);

  const placed = placeAll(doc, t, !reduced);
  const kills = killsBy(doc, t);
  const recent = [
    ...doc.deaths
      .filter((death) => death.t <= t && death.t > t - 90)
      .map((death) => ({ t: death.t, text: `${who(death.killer !== null ? slots.get(death.killer) : undefined)} killed ${who(slots.get(death.victim), true)}` })),
    ...marks.filter((m) => m.kind !== "kill" && m.t <= t && m.t > t - 90).map((m) => ({ t: m.t, text: m.title })),
  ].sort((a, b) => b.t - a.t);
  const yourSlot = you?.slot ?? null;
  const seek = (next: number) => setT(Math.max(0, Math.min(duration, next)));

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <h2 className="text-title max-md:text-coin">Replay</h2>
        <p className="text-label text-muted">Every hero on the map every few seconds, in their team&apos;s ring. Greyed with an × while dead.</p>
      </div>
      <div className="flex flex-wrap items-start gap-5">
        <div className="relative aspect-square min-w-0 flex-1 basis-120 overflow-hidden rounded-panel border border-line bg-background">
          {/* The floor: the minimap as a mask filled with the line colour (C12). Without the image, a
              plain plane. */}
          <div
            aria-hidden="true"
            className="absolute inset-3 bg-line"
            style={{ maskImage: `url(${MINIMAP_URL})`, maskSize: "100% 100%", WebkitMaskImage: `url(${MINIMAP_URL})`, WebkitMaskSize: "100% 100%" }}
          />
          <div role="img" aria-label={`The map at ${gameClock(t)}: ${placed.filter((p) => p.dead).length} heroes dead.`} className="absolute inset-3">
            {placed.map((spot) => {
              const line = slots.get(spot.slot);
              if (!line) return null;
              const isYou = ringMe && spot.slot === yourSlot;
              return (
                <span
                  key={spot.slot}
                  aria-hidden="true"
                  className={cn("absolute flex -translate-1/2 flex-col items-center gap-0.5", isYou ? "z-10" : "z-0")}
                  style={{ left: `${(spot.x * 100).toFixed(2)}%`, top: `${(spot.y * 100).toFixed(2)}%` }}
                >
                  <Portrait hero={line.hero} src={heroArt(line.hero_slug)} team={line.team} size={isYou ? "md" : "sm"} isYou={isYou} isDead={spot.dead} />
                  {showNames ? <span className="rounded-full bg-background px-1.5 text-micro font-bold whitespace-nowrap">{line.name}</span> : null}
                </span>
              );
            })}
          </div>
          <span className="absolute top-3 right-3 rounded-full bg-raised px-3 py-1 type-display text-body tabular-nums">{gameClock(t)}</span>
        </div>

        <div className="flex min-w-0 flex-1 basis-80 flex-col gap-4">
          <div className="grid grid-cols-2 gap-3">
            <Panel className="flex flex-col gap-1 p-4">
              <span className="text-micro font-bold text-muted">Kills</span>
              <b className="type-display text-stat tabular-nums">
                <span className="text-team-hk">{kills.hk}</span>
                <span className="text-faint"> – </span>
                <span className="text-team-am">{kills.am}</span>
              </b>
            </Panel>
            <Panel className="flex flex-col gap-1 p-4">
              <span className="text-micro font-bold text-muted">Soul lead</span>
              <b className="type-display text-card tabular-nums">{leadText(leadAt(doc, t, "souls"), names, "souls")}</b>
            </Panel>
          </div>
          <div role="group" aria-label="Map options" className="flex flex-wrap gap-2">
            {yourSlot !== null ? (
              <ToggleButton isSelected={ringMe} onChange={setRingMe} className={TOGGLE}>
                Ring me
              </ToggleButton>
            ) : null}
            <ToggleButton isSelected={showNames} onChange={setShowNames} className={TOGGLE}>
              Names
            </ToggleButton>
          </div>
          <Panel as="section" className="flex flex-col gap-2">
            <h3 className="text-body font-extrabold">Last 90 seconds</h3>
            {recent.length === 0 ? (
              <p className="text-label text-muted">Nothing yet. Press play or pick a moment below.</p>
            ) : (
              <ul className="flex flex-col gap-1">
                {recent.slice(0, 10).map((item, index) => (
                  <li key={index} className="text-label tabular-nums">
                    <span className="font-bold text-muted">{gameClock(item.t)}</span> {item.text}
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </div>
      </div>

      <Panel className="flex flex-col gap-3">
        <div className="relative h-3" aria-hidden="true">
          {marks.map((mark, index) => (
            <span
              key={index}
              className={cn("absolute top-0 size-3 -translate-x-1/2 rounded-full", mark.side === "hk" ? "bg-team-hk" : mark.side === "am" ? "bg-team-am" : "bg-muted")}
              style={{ left: `${((mark.t / Math.max(1, duration)) * 100).toFixed(2)}%` }}
            />
          ))}
        </div>
        <input
          type="range"
          min={0}
          max={duration}
          step={1}
          value={Math.round(t)}
          onChange={(event) => seek(Number(event.target.value))}
          aria-label="Time in the match"
          aria-valuetext={`${gameClock(t)} of ${gameClock(duration)}`}
          className="h-11 w-full cursor-pointer accent-foreground"
        />
        <div className="flex flex-wrap items-center gap-3">
          <IconButton icon="back" label="Back 10 seconds" onPress={() => seek(t - 10)} />
          <Button
            icon={playing ? "pause" : "play"}
            onPress={() => {
              if (!playing && t >= duration) setT(0);
              setPlaying(!playing);
            }}
          >
            {playing ? "Pause" : "Play"}
          </Button>
          <IconButton icon="next" label="Forward 10 seconds" onPress={() => seek(t + 10)} />
          <span className="type-display text-card tabular-nums">
            {gameClock(t)} <span className="text-muted">/ {gameClock(duration)}</span>
          </span>
          <span className="ml-auto">
            <Segmented
              label="Speed"
              value={String(speed)}
              onChange={(next) => setSpeed(Number(next) as Speed)}
              options={SPEEDS.map((s) => ({ id: String(s), label: `${s}×` }))}
            />
          </span>
        </div>
      </Panel>
    </div>
  );
}
