// The postgame summary (R07, E02, R11, M09): who won and how, your night when you played, six
// awards and both scoreboards. With no postgame yet, the record's result and the reason why.
import { Link } from "react-router";

import type { MatchDetail, PlayerLine, Postgame, PostgameBody, ResultPlayer, Side, YourNight } from "../../api/types";
import { ButtonLink } from "../../components/Button";
import { ScoreLine } from "../../components/Data";
import { Icon } from "../../components/Icon";
import { Panel, Section } from "../../components/Layout";
import { LeadChart } from "../../components/LeadChart";
import { Portrait } from "../../components/Portrait";
import { Sticker } from "../../components/Sticker";
import { TEAM_CLASS } from "../../components/team";
import { cn } from "../../lib/cn";
import { number, signed } from "../../lib/format";
import { useIsPhone } from "../../lib/useMediaQuery";
import { compact, gameClock, heroArt, moveWords, SIDE_NAME } from "../shared/format";
import type { Names } from "./model";
import { AWARD_NAME, awardLine, namesOf, PENDING, playerBySlot, storyBeats, storyLine, winningSide } from "./model";

const LEAGUE_AWARD = { mvp: "League MVP", key: "Key player" } as const;

function Move({ delta, label }: { delta: number; label: string }) {
  return (
    <span className="inline-flex items-center gap-1 font-extrabold tabular-nums">
      <span aria-hidden="true">{delta > 0 ? "▲" : delta < 0 ? "▼" : ""}</span>
      <span aria-hidden="true">{signed(delta)}</span>
      <span className="sr-only">
        {label} {moveWords(delta)}
      </span>
    </span>
  );
}

function Result({ detail, doc, names, winner }: { detail: MatchDetail; doc: Postgame | null; names: Names; winner: Side | null }) {
  const patron = doc?.beats.find((beat) => beat.type === "patron");
  const voided = detail.status === "voided";
  return (
    <div className="flex min-w-0 flex-col gap-4">
      <span className="flex flex-wrap items-center gap-3">
        {winner ? (
          <Sticker tone={winner} className="text-sheet type-display">
            GG
          </Sticker>
        ) : null}
        <span className={cn("text-label font-extrabold", winner ? TEAM_CLASS[winner].text : "text-muted")}>
          {voided ? "Cancelled" : winner ? SIDE_NAME[winner] : "No result yet"}
          {patron ? ` · Patron down at ${gameClock(patron.t)}` : null}
        </span>
      </span>
      <p className={cn("type-display text-poster max-md:text-title", winner ? TEAM_CLASS[winner].text : "text-foreground")}>
        {voided ? "No result: cancelled" : winner ? `${names.side[winner]} win` : "Waiting for the result"}
      </p>
      <p className="max-w-lead text-lead text-muted">
        {doc
          ? storyLine(doc, names)
          : detail.duration_s
            ? `${gameClock(detail.duration_s)} on the scoreboard. The story of the game comes with the match data.`
            : "The story of the game comes with the match data."}
      </p>
      {doc ? (
        <div className="flex flex-wrap gap-x-12 gap-y-3">
          <ScoreLine label="Kills" hk={doc.teams.hk.kills} am={doc.teams.am.kills} />
          <ScoreLine label="Souls" hk={compact(doc.teams.hk.souls)} am={compact(doc.teams.am.souls)} />
          <ScoreLine label="Objectives" hk={doc.teams.hk.objectives} am={doc.teams.am.objectives} />
        </div>
      ) : null}
    </div>
  );
}

function YourNightCard({ you, line, doc, side }: { you: YourNight; line: PlayerLine | undefined; doc: Postgame | null; side: Side | null }) {
  const awards = doc && line ? doc.awards.filter((award) => award.slot === line.slot) : [];
  return (
    <section aria-labelledby="your-night" className={cn("flex gap-5 rounded-panel border-2 bg-surface p-5", side ? TEAM_CLASS[side].line : "border-line")}>
      {line ? <Portrait hero={line.hero} src={heroArt(line.hero_slug)} team={side} size="lg" className="size-28 max-md:size-16" /> : null}
      <div className="flex min-w-0 flex-col gap-1.5">
        <span id="your-night" className="text-label font-bold text-muted">
          Your night
        </span>
        {line ? (
          <>
            <b className="type-display text-coin">{line.hero}</b>
            <b className="type-display text-title tabular-nums" aria-label={`${line.kills} kills, ${line.deaths} deaths, ${line.assists} assists`}>
              {line.kills} / {line.deaths} / {line.assists}
            </b>
            <span className="text-body text-muted tabular-nums">
              {compact(line.souls)} souls · {compact(line.damage)} hero damage
            </span>
          </>
        ) : (
          <span className="text-body text-muted">Your numbers come with the match data.</span>
        )}
        {you.rating_before !== null && you.rating_after !== null && you.delta !== null ? (
          <span className="flex flex-wrap items-center gap-2.5 text-body font-extrabold tabular-nums">
            {number(you.rating_before)} → {number(you.rating_after)}
            <Sticker tone="cream" size="sm" tilt="slight">
              <Move delta={you.delta} label={you.rating_label} />
            </Sticker>
          </span>
        ) : null}
        <span className="flex flex-wrap gap-2">
          {awards.map((award) => (
            <Sticker key={award.kind} tone="raised" size="sm">
              {AWARD_NAME[award.kind]}
            </Sticker>
          ))}
          {you.award ? (
            <Sticker tone="raised" size="sm">
              {LEAGUE_AWARD[you.award]}
            </Sticker>
          ) : null}
        </span>
      </div>
    </section>
  );
}

function HowItWent({ detail, doc, names }: { detail: MatchDetail; doc: Postgame; names: Names }) {
  const points = doc.timeline.t.map((t, i) => ({ t, lead: doc.timeline.souls[i] ?? 0 }));
  const beats = storyBeats(doc, names).slice(0, 3);
  return (
    <Section
      title="How it went"
      aside={
        <ButtonLink to={`/matches/${detail.id}/timeline`} kind="ghost" size="sm">
          Open the timeline
        </ButtonLink>
      }
    >
      <div className="relative rounded-card border border-line bg-surface p-3">
        <span className="absolute top-2 left-3 text-micro font-extrabold text-team-hk">{names.side.hk} ahead</span>
        <LeadChart
          points={points}
          label={`Soul lead over the match. ${storyLine(doc, names)}`}
          className="h-30"
        />
        <span className="absolute bottom-2 left-3 text-micro font-extrabold text-team-am">{names.side.am} ahead</span>
      </div>
      {beats.length ? (
        <ul className="grid grid-cols-1 gap-3 md:grid-cols-3">
          {beats.map((beat) => (
            <li key={`${beat.t}-${beat.title}`}>
              <Link
                to={`/matches/${detail.id}/timeline?t=${beat.t}`}
                className="flex h-full flex-col gap-1 rounded-card border border-line bg-surface p-4 hover:border-line-strong"
              >
                <span className="text-caption font-bold text-muted tabular-nums">{gameClock(beat.t)}</span>
                <b className="text-body font-extrabold">{beat.title}</b>
                <span className="text-label text-muted">{beat.text}</span>
              </Link>
            </li>
          ))}
        </ul>
      ) : null}
    </Section>
  );
}

function Awards({ doc }: { doc: Postgame }) {
  const slots = playerBySlot(doc);
  if (doc.awards.length === 0) return null;
  return (
    <Section title="Awards">
      <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {doc.awards.map((award) => {
          const line = slots.get(award.slot);
          return (
            <li key={award.kind} className="flex items-center gap-4 rounded-card border border-line bg-surface p-4">
              {line ? <Portrait hero={line.hero} src={heroArt(line.hero_slug)} team={line.team} size="lg" /> : null}
              <span className="flex min-w-0 flex-col gap-1">
                <Sticker tone={award.kind === "mvp" ? "brand" : "cream"} size="sm" className="self-start">
                  {AWARD_NAME[award.kind]}
                </Sticker>
                <b className="truncate text-body font-extrabold">{line?.name ?? "Someone"}</b>
                <span className="text-caption text-muted">{awardLine(award, doc)}</span>
              </span>
            </li>
          );
        })}
      </ul>
    </Section>
  );
}

interface Row {
  id: string;
  name: string;
  hero: string | null;
  heroSlug: string | null;
  line: PlayerLine | undefined;
  result: ResultPlayer;
  isYou: boolean;
}

function Scoreboard({
  side,
  title,
  won,
  rows,
  detail,
  rated,
}: {
  side: Side | null;
  title: string;
  won: boolean;
  rows: Row[];
  detail: MatchDetail;
  rated: boolean;
}) {
  const hasStats = rows.some((row) => row.line);
  return (
    <section aria-label={`${title} scoreboard`} className={cn("flex flex-col gap-2 rounded-panel border bg-surface p-4", side ? TEAM_CLASS[side].line : "border-line")}>
      <h3 className="flex flex-wrap items-baseline gap-2.5">
        <span className={cn("type-display text-sheet", side ? TEAM_CLASS[side].text : "text-foreground")}>{title}</span>
        <span className={cn("text-label font-bold", side ? TEAM_CLASS[side].text : "text-muted")}>
          {[side ? SIDE_NAME[side] : null, won ? "won" : null].filter(Boolean).join(" · ")}
        </span>
      </h3>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-label font-semibold">
          <caption className="sr-only">{title}: each player&apos;s numbers. Pick a player for all of them.</caption>
          <thead>
            <tr className="text-micro font-extrabold text-faint">
              <th scope="col" className="px-2 py-1.5 text-left">
                Player
              </th>
              {hasStats ? (
                <>
                  <th scope="col" className="px-2 py-1.5 text-right">
                    K/D/A
                  </th>
                  <th scope="col" className="px-2 py-1.5 text-right">
                    Souls
                  </th>
                  <th scope="col" className="px-2 py-1.5 text-right max-sm:hidden">
                    Damage
                  </th>
                </>
              ) : (
                <th scope="col" className="px-2 py-1.5 text-left">
                  Line
                </th>
              )}
              {rated ? (
                <th scope="col" className="px-2 py-1.5 text-right">
                  {detail.rating_label}
                </th>
              ) : null}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const art = heroArt(row.heroSlug);
              const name = (
                <span className="flex min-w-0 items-center gap-3">
                  <Portrait hero={row.hero ?? row.name} src={art} team={side} size="md" />
                  <span className="flex min-w-0 flex-col">
                    <b className="truncate text-body font-extrabold">{row.name}</b>
                    <span className="text-caption text-muted">
                      {[row.hero, row.isYou ? "you" : null].filter(Boolean).join(" · ")}
                    </span>
                  </span>
                </span>
              );
              return (
                <tr key={row.id} className={cn(row.isYou && (side ? TEAM_CLASS[side].soft : "bg-raised"))}>
                  <th scope="row" className="px-2 py-2 text-left font-normal">
                    {row.line ? (
                      <Link to={`/matches/${detail.id}/advanced?slot=${row.line.slot}`} className="flex min-h-11 rounded-row" aria-label={`${row.name}: every number`}>
                        {name}
                      </Link>
                    ) : (
                      name
                    )}
                  </th>
                  {hasStats ? (
                    <>
                      <td className="px-2 py-2 text-right tabular-nums">{row.line ? `${row.line.kills}/${row.line.deaths}/${row.line.assists}` : "–"}</td>
                      <td className="px-2 py-2 text-right tabular-nums">{row.line ? compact(row.line.souls) : "–"}</td>
                      <td className="px-2 py-2 text-right tabular-nums max-sm:hidden">{row.line ? compact(row.line.damage) : "–"}</td>
                    </>
                  ) : (
                    <td className="px-2 py-2 text-caption text-muted">{row.result.stat_line ?? "–"}</td>
                  )}
                  {rated ? (
                    <td className="px-2 py-2 text-right">
                      <Move delta={row.result.delta} label={detail.rating_label} />
                    </td>
                  ) : null}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Scoreboards({ detail, doc, names, winner, you }: { detail: MatchDetail; doc: Postgame | null; names: Names; winner: Side | null; you: YourNight | null }) {
  const byPlayer = new Map<number, PlayerLine>();
  for (const line of doc?.players ?? []) if (line.player_id !== null) byPlayer.set(line.player_id, line);
  const yourSlot = you?.slot ?? null;
  // The Hidden King's team first.
  const teams = [...detail.teams].sort((a, b) => (a.side === "hk" ? -1 : b.side === "hk" ? 1 : 0));
  return (
    <Section title={teams.length > 1 ? "Scoreboards" : "Scoreboard"} aside={doc ? <span className="text-label font-semibold text-muted">Pick a player for their full numbers</span> : undefined}>
      <div className="flex flex-col gap-4">
        {teams.map((team) => {
          const side = team.side;
          const rows: Row[] = team.players.map((player) => {
            const line = byPlayer.get(Number(player.id));
            return {
              id: player.id,
              name: player.name,
              hero: line?.hero ?? player.hero?.name ?? null,
              heroSlug: line?.hero_slug ?? player.hero?.slug ?? null,
              line,
              result: player,
              isYou: line ? line.slot === yourSlot : false,
            };
          });
          if (doc) rows.sort((a, b) => (b.line?.souls ?? 0) - (a.line?.souls ?? 0));
          return (
            <Scoreboard
              key={team.team}
              side={side}
              title={side ? names.side[side] : (team.name ?? `Team ${team.team}`)}
              won={side !== null && side === winner}
              rows={rows}
              detail={detail}
              rated={detail.rated}
            />
          );
        })}
      </div>
    </Section>
  );
}

function Rail({ detail, names, played }: { detail: MatchDetail; names: Names; played: boolean }) {
  const bans = [...detail.teams]
    .filter((team) => team.bans.length > 0)
    .sort((a, b) => (a.side === "hk" ? -1 : b.side === "hk" ? 1 : 0));
  return (
    <>
      <Panel as="section" className="flex flex-col gap-1.5">
        <h2 className="text-card">Result</h2>
        <p className="text-label text-muted">
          {detail.status === "voided"
            ? "Staff cancelled this match: nothing was rated."
            : detail.rated
              ? `Both captains' result stands. ${detail.rating_label === "Points" ? "Points" : "Ratings"} applied from it; the stats only change what the postgame can show.`
              : detail.status === "completed"
                ? "This match wasn't rated."
                : "The result isn't settled yet."}
        </p>
      </Panel>
      {bans.length ? (
        <Panel as="section" className="flex flex-col gap-1.5">
          <h2 className="text-card">The draft</h2>
          {bans.map((team) => (
            <p key={team.team} className="text-label text-muted">
              <b className={cn("font-extrabold", team.side ? TEAM_CLASS[team.side].text : "text-foreground")}>{team.side ? names.side[team.side] : team.name}</b> banned{" "}
              {team.bans.map((ban) => ban.name).join(", ")}
            </p>
          ))}
        </Panel>
      ) : null}
      {played ? (
        <Panel as="section" className="flex flex-col gap-3">
          <h2 className="text-card">Share your night</h2>
          <p className="text-label text-muted">A card with your rating, ladder place and last award, as a PNG you choose to post.</p>
          <ButtonLink to="/me/share" kind="ghost" icon="share" className="self-start">
            Make the card
          </ButtonLink>
        </Panel>
      ) : (
        <section className="flex flex-col gap-1.5 rounded-panel border border-dashed border-line-strong p-5">
          <h2 className="text-card">Watching, not playing</h2>
          <p className="text-label text-muted">
            This is the match as anyone who wasn&apos;t in it sees it: no Your night and no share card. The twelve players get those on their own
            summary.
          </p>
        </section>
      )}
    </>
  );
}

function Pending({ reason }: { reason: keyof typeof PENDING }) {
  const words = PENDING[reason];
  return (
    <section role="status" className="flex items-start gap-3 rounded-panel border-2 border-line-strong bg-raised px-5 py-4">
      <span className="pt-0.5 text-muted">
        <Icon name="clock" size={20} />
      </span>
      <span className="flex flex-col gap-1">
        <b className="text-body font-extrabold">{words.title}</b>
        <span className="text-label text-muted">{words.text}</span>
      </span>
    </section>
  );
}

function DigIn({ id }: { id: string }) {
  const items = [
    { to: "timeline", title: "Timeline", line: "The lead, and every moment on it" },
    { to: "replay", title: "Replay", line: "Scrub the overview map" },
    { to: "advanced", title: "Advanced", line: "Every number, every player" },
  ];
  return (
    <Section title="Dig in">
      <ul className="flex flex-col gap-2">
        {items.map((item) => (
          <li key={item.to}>
            <Link to={`/matches/${id}/${item.to}`} className="flex items-center justify-between gap-3 rounded-card border border-line bg-surface px-4 py-3">
              <span className="flex flex-col">
                <b className="text-body font-extrabold">{item.title}</b>
                <span className="text-caption text-muted">{item.line}</span>
              </span>
              <Icon name="next" size={18} />
            </Link>
          </li>
        ))}
      </ul>
    </Section>
  );
}

export function Summary({ detail, body, played }: { detail: MatchDetail; body: PostgameBody; played: boolean }) {
  const phone = useIsPhone();
  const doc = body.status === "ready" ? body.data : null;
  const you = body.status === "ready" ? body.you : null;
  const names = namesOf(detail, doc);
  const winner = winningSide(detail, doc);
  const yourLine = doc && you?.slot !== null && you?.slot !== undefined ? playerBySlot(doc).get(you.slot) : undefined;
  const yourSide = you?.side ?? yourLine?.team ?? null;

  return (
    <div className="flex flex-col gap-8">
      <div className={cn("flex flex-wrap items-start gap-6 rounded-panel", !played && cn("border-2 p-7 max-md:p-5", winner ? TEAM_CLASS[winner].line : "border-line"))}>
        <div className="min-w-0 flex-999 basis-140">
          <Result detail={detail} doc={doc} names={names} winner={winner} />
        </div>
        {you ? (
          <div className="min-w-0 flex-1 basis-90">
            <YourNightCard you={you} line={yourLine} doc={doc} side={yourSide} />
          </div>
        ) : null}
      </div>
      <div className="flex flex-wrap items-start gap-x-8 gap-y-7">
        <div className="flex min-w-0 flex-999 basis-160 flex-col gap-8">
          {body.status === "pending" ? <Pending reason={body.reason} /> : null}
          {doc ? phone ? <DigIn id={detail.id} /> : <HowItWent detail={detail} doc={doc} names={names} /> : null}
          {doc ? <Awards doc={doc} /> : null}
          <Scoreboards detail={detail} doc={doc} names={names} winner={winner} you={you} />
          {!doc ? <p className="text-label text-muted">No awards or story yet: they need the match data too.</p> : null}
        </div>
        <aside aria-label="About this match" className="flex min-w-0 flex-1 basis-80 flex-col gap-4">
          <Rail detail={detail} names={names} played={played} />
        </aside>
      </div>
    </div>
  );
}
