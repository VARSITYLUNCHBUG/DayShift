// /me (E04, E10): your private profile. Rating, tier and rank, record, strikes and how they come
// off, your rating history, recent matches (each opening its postgame), top heroes, and your
// accounts. Nobody else's profile exists: only you see this page.
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";

import { useMe } from "../../api/live";
import { queries } from "../../api/queries";
import { useSignOut } from "../../api/session";
import type { MyProfile, SteamRow } from "../../api/types";
import { Avatar } from "../../components/Avatar";
import { Button, ButtonLink } from "../../components/Button";
import { LineChart } from "../../components/charts/LineChart";
import { StatTile } from "../../components/Data";
import { Icon } from "../../components/Icon";
import { Panel } from "../../components/Layout";
import { Portrait } from "../../components/Portrait";
import { EmptyState, ErrorState, Skeleton } from "../../components/States";
import { Sticker } from "../../components/Sticker";
import { errorText, notify } from "../../components/toast";
import { useServerNow } from "../../live/hooks";
import { cn } from "../../lib/cn";
import { clockTime, number, plural, record, shortDate, signed, winRate } from "../../lib/format";
import { matchNo, SIDE_NAME } from "../shared/format";
import { Progress, StrikeDots } from "../shared/parts";
import { SeasonSwitch, useSeasonParam } from "../shared/SeasonSwitch";
import { SteamStatus } from "./LinkSteam";
import { UnlinkDialog } from "./UnlinkDialog";

const RESULT = { win: "Won", loss: "Lost", void: "Void" } as const;

function Tiles({ profile }: { profile: MyProfile }) {
  const lastMove = profile.recent.find((m) => m.delta !== null);
  const games = profile.wins + profile.losses;
  const toGo = profile.strikes.games_to_next;
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <StatTile
        label={profile.rating_label}
        value={number(profile.rating)}
        line={lastMove && lastMove.delta !== null ? `${signed(lastMove.delta)} after ${matchNo(lastMove.match_id)}` : "No matches yet"}
      />
      <StatTile
        label="Tier"
        value={profile.tier ?? (profile.placement ? "Unranked" : "–")}
        line={
          profile.rank
            ? `#${profile.rank} of ${profile.ranked} on the ladder`
            : profile.placement
              ? `${profile.placement.played} of ${profile.placement.total} placement matches`
              : "Not on the ladder yet"
        }
      />
      <StatTile label="Record" value={record(profile.wins, profile.losses)} line={`${winRate(profile.wins, games)} won · ${plural(profile.games, "match", "matches")}`} />
      <StatTile
        label="Strikes"
        value={profile.strikes.count}
        line={profile.strikes.count === 0 ? "None: you're clean" : toGo !== null ? `${plural(toGo, "more clean match", "more clean matches")} take one off` : "Comes off with time"}
      />
    </div>
  );
}

function History({ profile }: { profile: MyProfile }) {
  const points = profile.history.map((point, index) => ({ x: index, y: point.rating_after }));
  const first = profile.history[0];
  const last = profile.history.at(-1);
  return (
    <Panel as="section" aria-labelledby="history-heading" className="flex flex-col gap-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="history-heading" className="text-section">
          {profile.rating_label} history
        </h2>
        <span className="text-caption font-semibold text-muted">
          {profile.season} · {plural(profile.history.length, "change")}
        </span>
      </div>
      {points.length < 2 || !first || !last ? (
        <p className="text-label text-muted">Your history draws itself as you play: one point per rated match.</p>
      ) : (
        <>
          <LineChart
            points={points}
            label={`${profile.rating_label} from ${number(first.rating_after)} to ${number(last.rating_after)} over ${plural(points.length, "change")} this season.`}
            start={first.at ? shortDate(first.at) : null}
            end={last.match_id ? matchNo(last.match_id) : null}
          />
          <details className="text-label">
            <summary className="inline-flex min-h-11 cursor-pointer items-center font-extrabold underline underline-offset-2">Show the numbers</summary>
            <div className="max-h-72 overflow-y-auto">
              <table className="w-full border-collapse tabular-nums">
                <caption className="sr-only">Every change to your {profile.rating_label.toLowerCase()} this season, oldest first</caption>
                <thead>
                  <tr className="text-micro font-extrabold text-faint">
                    <th scope="col" className="px-2 py-1 text-left">
                      When
                    </th>
                    <th scope="col" className="px-2 py-1 text-left">
                      Match
                    </th>
                    <th scope="col" className="px-2 py-1 text-right">
                      Change
                    </th>
                    <th scope="col" className="px-2 py-1 text-right">
                      After
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {profile.history.map((point, index) => (
                    <tr key={index} className="border-t border-line">
                      <td className="px-2 py-1">{point.at ? shortDate(point.at) : "–"}</td>
                      <td className="px-2 py-1">{point.match_id ? matchNo(point.match_id) : "Staff"}</td>
                      <td className="px-2 py-1 text-right">{signed(point.delta)}</td>
                      <td className="px-2 py-1 text-right">{number(point.rating_after)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </>
      )}
    </Panel>
  );
}

function Recent({ profile }: { profile: MyProfile }) {
  return (
    <Panel as="section" aria-labelledby="recent-heading" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="recent-heading" className="text-section">
          Recent matches
        </h2>
        <span className="text-caption font-semibold text-muted">Each opens its postgame</span>
      </div>
      {profile.recent.length === 0 ? (
        <p className="text-label text-muted">Your matches land here after your first one, each with its postgame.</p>
      ) : (
        <ul className="flex flex-col">
          {profile.recent.map((match) => (
            <li key={match.match_id} className="border-b border-line last:border-b-0">
              <Link to={`/matches/${match.match_id}/summary`} className="flex min-h-14 items-center gap-4 py-2 hover:bg-raised">
                <b className="w-20 shrink-0 type-display text-card tabular-nums">{matchNo(match.match_id)}</b>
                <span
                  className={cn(
                    "w-12 shrink-0 text-label font-extrabold",
                    match.result === "win" && match.side ? (match.side === "hk" ? "text-team-hk" : "text-team-am") : "text-muted",
                  )}
                >
                  {match.result ? RESULT[match.result] : "–"}
                </span>
                {match.hero ? <Portrait hero={match.hero.name} src={match.hero.icon_url} team={match.side} size="sm" /> : null}
                <span className="min-w-0 flex-1 truncate text-label text-muted">
                  {[match.hero?.name, match.side ? SIDE_NAME[match.side] : null, match.result === "void" ? "staff voided it" : null].filter(Boolean).join(" · ")}
                </span>
                {match.award ? (
                  <Sticker tone="raised" size="sm">
                    {match.award === "mvp" ? "MVP" : "Key player"}
                  </Sticker>
                ) : null}
                <b className="w-12 shrink-0 text-right text-body font-extrabold tabular-nums">{match.delta !== null ? signed(match.delta) : "–"}</b>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function Heroes({ profile }: { profile: MyProfile }) {
  if (profile.heroes.length === 0) return null;
  return (
    <Panel as="section" aria-labelledby="heroes-heading" className="flex flex-col gap-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="heroes-heading" className="text-section">
          Your heroes
        </h2>
        <span className="text-caption font-semibold text-muted">Most played this season</span>
      </div>
      <ul className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
        {profile.heroes.map((hero) => (
          <li key={hero.hero.id} className="flex flex-col gap-2">
            <span className="flex aspect-square items-center justify-center overflow-hidden rounded-card border border-line bg-background">
              {hero.hero.icon_url ? <img src={hero.hero.icon_url} alt="" loading="lazy" className="size-full object-cover object-top" /> : null}
            </span>
            <span className="flex flex-col">
              <b className="text-label font-extrabold">{hero.hero.name}</b>
              <span className="text-caption text-muted">{plural(hero.games, "match", "matches")}</span>
            </span>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

function StrikesPanel({ profile }: { profile: MyProfile }) {
  const live = useMe().data;
  const now = useServerNow(5_000);
  const cooldown = live?.cooldown && Date.parse(live.cooldown.until) > now ? live.cooldown : null;
  const s = profile.strikes;
  return (
    <Panel as="section" aria-labelledby="strikes-heading" className="flex flex-col gap-3.5">
      <div className="flex flex-col gap-1">
        <h2 id="strikes-heading" className="text-section">
          Strikes and penalties
        </h2>
        <span className="text-caption font-semibold text-muted">{cooldown ? `Cooldown until ${clockTime(cooldown.until)}` : "No cooldown now"}</span>
      </div>
      <span className="flex items-center gap-3">
        <StrikeDots count={s.count} />
        <b className="text-body font-extrabold">{plural(s.count, "strike")}</b>
      </span>
      {s.count > 0 ? <Progress value={s.progress} max={s.games_per_strike} label={`${s.progress} of ${s.games_per_strike} clean matches to take one off`} /> : null}
      <p className="text-label text-muted">
        A strike comes from missing a ready check or leaving a match early. Each one makes the next cooldown longer; {s.games_per_strike} clean matches
        {s.next_decay_at ? `, or waiting until ${shortDate(s.next_decay_at)} without a new one,` : ""} take one off.
      </p>
      {s.log.length ? (
        <ul className="flex flex-col">
          {s.log.slice(0, 8).map((entry, index) => (
            <li key={index} className="flex gap-4 border-t border-line py-2.5">
              <span className="w-14 shrink-0 text-caption font-bold text-muted tabular-nums">{shortDate(entry.at)}</span>
              <span className="flex min-w-0 flex-col">
                <b className={cn("text-label font-extrabold", entry.waived && "line-through")}>
                  {entry.kind === "adjustment" ? entry.label : `Strike: ${entry.label.toLowerCase()}`}
                  {entry.match_id ? `, ${matchNo(entry.match_id)}` : ""}
                </b>
                <span className="text-caption text-muted">
                  {entry.waived ? "Staff lifted it: it doesn't count. " : ""}
                  {entry.reason}
                </span>
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </Panel>
  );
}

function Accounts({ profile, onUnlink }: { profile: MyProfile; onUnlink: (row: SteamRow) => void }) {
  const signOut = useSignOut();
  const navigate = useNavigate();
  return (
    <Panel as="section" aria-labelledby="accounts-heading" className="flex flex-col gap-3">
      <h2 id="accounts-heading" className="text-section">
        Accounts
      </h2>
      <div className="flex items-center gap-3 border-t border-line pt-3">
        <Icon name="discord" size={20} />
        <span className="flex min-w-0 flex-col">
          <b className="text-label font-extrabold">Discord</b>
          <span className="text-caption text-muted">{profile.accounts.discord_name} · signed in</span>
        </span>
      </div>
      {profile.accounts.steam.length === 0 ? (
        <div className="flex items-center gap-3 border-t border-line pt-3">
          <Icon name="steam" size={20} />
          <span className="flex min-w-0 flex-1 flex-col">
            <b className="text-label font-extrabold">Steam</b>
            <span className="text-caption text-muted">Not linked: your results can&apos;t find you yet</span>
          </span>
        </div>
      ) : (
        profile.accounts.steam.map((row) => (
          <div key={row.id} className="flex flex-wrap items-center gap-3 border-t border-line pt-3">
            <Icon name="steam" size={20} />
            <span className="flex min-w-0 flex-1 flex-col">
              <b className="text-label font-extrabold">Steam</b>
              <span className="truncate text-caption text-muted">{row.name || "Steam account"}</span>
            </span>
            <SteamStatus row={row} />
            <Button kind="danger" size="sm" onPress={() => onUnlink(row)} aria-label={`Unlink ${row.name || "this Steam account"}`}>
              Unlink
            </Button>
          </div>
        ))
      )}
      <div className="flex flex-wrap gap-2.5 pt-1">
        <ButtonLink to="/link-steam" kind="ghost" size="sm" icon="steam">
          {profile.accounts.steam.length ? "Manage Steam" : "Link Steam"}
        </ButtonLink>
        <Button
          kind="quiet"
          size="sm"
          icon="leave"
          isPending={signOut.isPending}
          pendingLabel="Signing out…"
          onPress={() =>
            signOut.mutate(undefined, {
              onSuccess: () => void navigate("/signin", { replace: true }),
              onError: (reason) => notify.error(errorText(reason)),
            })
          }
        >
          Sign out
        </Button>
      </div>
    </Panel>
  );
}

function ShareCardPanel() {
  return (
    <Panel as="section" aria-labelledby="share-heading" className="flex flex-col gap-3">
      <h2 id="share-heading" className="text-section">
        Share card
      </h2>
      <p className="text-label text-muted">Your profile stays private. The card is a PNG you choose to post.</p>
      <ButtonLink to="/me/share" icon="share" className="self-start">
        Make a share card
      </ButtonLink>
    </Panel>
  );
}

export function MePage() {
  const [, setParams] = useSearchParams();
  const season = useSeasonParam();
  const profile = useQuery(queries.me(season));
  const [unlinking, setUnlinking] = useState<SteamRow | null>(null);

  if (profile.isPending) return <Skeleton label="Loading your profile" lines={6} />;
  if (profile.isError) {
    return (
      <ErrorState
        headingLevel={1}
        title="We can't load your profile right now"
        action={
          <Button kind="ghost" onPress={() => void profile.refetch()}>
            Try again
          </Button>
        }
      >
        Nothing on it has changed. Try again in a moment.
      </ErrorState>
    );
  }
  const p = profile.data;
  const fresh = p.games === 0 && p.history.length === 0;
  return (
    <>
      <header className="flex flex-wrap items-center justify-between gap-6">
        <div className="flex items-center gap-6">
          <Avatar name={p.player.name} src={p.accounts.avatar_url} size="xl" className="max-md:hidden" />
          <div className="flex flex-col gap-2">
            <Sticker tone="cream" className="self-start">
              Only you see this
            </Sticker>
            <h1 className="text-poster max-md:text-title">{p.player.name}</h1>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2.5">
          <SeasonSwitch value={season} onChange={(id) => setParams(id ? { season: id } : {}, { replace: true })} />
          <ButtonLink to="/me/share" icon="share">
            Make a share card
          </ButtonLink>
        </div>
      </header>
      <p className="max-w-lead text-body text-muted">
        Other players see your name, tier and rating on the ladder and in matches. Everything else on this page is yours alone.
      </p>
      <Tiles profile={p} />
      <div className="flex flex-wrap items-start gap-6">
        <div className="flex min-w-0 flex-999 basis-160 flex-col gap-6">
          {fresh ? (
            <EmptyState
              title="Nothing to show yet"
              action={
                p.accounts.steam.length === 0 ? (
                  <ButtonLink to="/link-steam" kind="ghost" icon="steam">
                    Link Steam
                  </ButtonLink>
                ) : (
                  <ButtonLink to="/" kind="ghost">
                    Join the queue
                  </ButtonLink>
                )
              }
            >
              Your rating history, heroes and recent matches fill in as you play.
              {p.accounts.steam.length === 0 ? " Link Steam now so your first results find you." : null}
            </EmptyState>
          ) : (
            <>
              <History profile={p} />
              <Recent profile={p} />
              <Heroes profile={p} />
            </>
          )}
        </div>
        <aside aria-label="Strikes, accounts and your card" className="flex min-w-0 flex-1 basis-90 flex-col gap-6">
          <StrikesPanel profile={p} />
          <Accounts profile={p} onUnlink={setUnlinking} />
          <ShareCardPanel />
        </aside>
      </div>
      <UnlinkDialog account={unlinking} onClose={() => setUnlinking(null)} />
    </>
  );
}

export default MePage;
