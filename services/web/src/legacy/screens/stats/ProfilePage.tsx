import { Button, Card, Chip, ProgressBar, Skeleton, Label } from "@heroui/react";
import { useState } from "react";
import { Link, useParams } from "react-router";

import { useSession } from "../../../api/session";

import { isNotFound, usePlayerProfile, useUnlinkSteam } from "../../../api/matches";
import { ActionDialog } from "../../components/ActionDialog";
import { AppShell } from "../../components/AppShell";
import { ButtonLink } from "../../components/ButtonLink";
import { EmptyState } from "../../components/EmptyState";
import { HeroArt } from "../../components/HeroCard";
import { DiscordMark, SteamMark } from "../../components/icons";
import { PlayerAvatar } from "../../components/PlayerAvatar";
import { SeasonPicker, useSeasonParam } from "../../components/SeasonPicker";
import { StatTile } from "../../components/StatTile";
import { TierChip } from "../../components/TierChip";
import { number, plural, record, shortDate, signed, winRate } from "../../lib/format";
import { useTopic } from "../../../live/hooks";
import type { CaptainStatus, ChampionRef, MePlayer, Outcome, PlayerProfile, RecentMatch } from "../../../live/types";
import { deltaClass } from "../matches/MatchRecord";

const PLAYER_ID = /^[1-9][0-9]{0,18}$/;

/** 5.4 Profile: a player's season (the open one unless `?season=` says otherwise): rating and
 * tier, record, awards, recent matches; and, now, their strikes and whether they can captain.
 * Your own adds your linked accounts. */
export function ProfilePage() {
  const { id = "" } = useParams();
  return <ProfileById id={id} />;
}

/** /me: your own profile. Profiles are private, so this is the only one you can open. */
export function MyProfilePage() {
  const session = useSession();
  return <ProfileById id={session.data?.player?.id ?? ""} />;
}

function ProfileById({ id }: { id: string }) {
  if (!PLAYER_ID.test(id)) return <PlayerNotFound />;
  return <Profile key={id} id={id} />;
}

function Profile({ id }: { id: string }) {
  const season = useSeasonParam();
  const { data, error, isError, refetch } = usePlayerProfile(id, season);
  const { data: me } = useTopic("me");
  if (isNotFound(error)) return <PlayerNotFound />;
  return (
    <AppShell>
      {data ? (
        <ProfileView profile={data} me={data.is_you ? (me?.player ?? null) : null} />
      ) : isError ? (
        <EmptyState
          title="Couldn't load the profile"
          description="Check your connection and try again."
          action={
            <Button variant="secondary" onPress={() => void refetch()}>
              Try again
            </Button>
          }
        />
      ) : (
        <Skeleton className="h-120 w-full rounded-3xl" />
      )}
    </AppShell>
  );
}

function PlayerNotFound() {
  return (
    <AppShell>
      <EmptyState
        title="Player not found"
        action={
          <ButtonLink to="/ladder" variant="secondary">
            Back to the leaderboard
          </ButtonLink>
        }
      />
    </AppShell>
  );
}

/** One decimal: "8.2". */
function tenths(value: number): string {
  return value.toLocaleString("en-GB", { maximumFractionDigits: 1, minimumFractionDigits: 1 });
}

/** "38k" */
function thousands(value: number): string {
  return value >= 1000 ? `${Math.round(value / 1000)}k` : String(Math.round(value));
}

function strikesHint(profile: PlayerProfile): string {
  const { count, games_to_next, next_decay_at } = profile.strikes;
  if (count === 0) return "None";
  if (games_to_next !== null) return `Next off in ${plural(games_to_next, "clean match", "clean matches")}`;
  if (next_decay_at) return `Next off ${shortDate(next_decay_at)}`;
  return plural(count, "strike");
}

function CaptainChip({ captain }: { captain: CaptainStatus }) {
  if (captain.eligible) {
    return (
      <Chip size="sm" variant="soft" color="success" className="font-semibold">
        Can captain
      </Chip>
    );
  }
  const barred = captain.reason === "barred by staff";
  return (
    <Chip size="sm" variant="soft" color={barred ? "danger" : "default"} className="font-semibold">
      {barred ? "Barred from captaining" : `Can't captain yet · ${captain.reason}`}
    </Chip>
  );
}

/** `me` is the viewer's own `me` player, on their own profile: it has their Steam name. */
export function ProfileView({ profile, me }: { profile: PlayerProfile; me: MePlayer | null }) {
  const placement = profile.placement;
  return (
    <div className="flex flex-col gap-6">
      <section aria-label="Player" className="flex flex-wrap items-center gap-5">
        <PlayerAvatar name={profile.player.name} url={profile.player.avatar_url} size="lg" className="size-18 rounded-2xl text-2xl" />
        <div className="flex min-w-0 flex-1 basis-75 flex-col gap-2">
          <h1 className="truncate text-3xl font-bold tracking-tight">{profile.player.name}</h1>
          <div className="flex flex-wrap gap-2">
            {profile.steam.linked ? (
              <Chip size="sm" variant="soft" color={profile.steam.verified ? "success" : "default"} className="font-semibold">
                {profile.steam.verified ? "Steam verified" : "Steam linked"}
              </Chip>
            ) : null}
            <Chip size="sm" variant="soft" className="font-semibold">
              {placement ? `Placement · ${placement.played} / ${placement.total}` : "Placed"}
            </Chip>
            <CaptainChip captain={profile.captain} />
            <Chip size="sm" variant="secondary">
              {profile.season}
            </Chip>
          </div>
        </div>
        <SeasonPicker value={profile.season_id} />
      </section>

      <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
        <StatTile
          label="Rating"
          value={number(profile.rating)}
          hint={
            <>
              <TierChip tier={profile.tier} />
              <span>{profile.rank ? `#${profile.rank}` : "Unranked"}</span>
            </>
          }
        />
        <StatTile label="Record" value={record(profile.wins, profile.losses)} hint={winRate(profile.wins, profile.games)} />
        <StatTile label="MVP · Key" value={`${profile.mvps} · ${profile.keys}`} />
        <StatTile label="Strikes" value={profile.strikes.count} hint={strikesHint(profile)} />
      </div>

      {placement ? (
        <ProgressBar value={placement.played} maxValue={placement.total} className="w-full max-w-md">
          <Label>Placement matches</Label>
          <ProgressBar.Output>{`${placement.played} of ${placement.total}`}</ProgressBar.Output>
          <ProgressBar.Track>
            <ProgressBar.Fill />
          </ProgressBar.Track>
        </ProgressBar>
      ) : null}

      <div className="flex flex-wrap items-start gap-6">
        <RatingTrend recent={profile.recent} />
        {profile.scoreboards > 0 && profile.avg_kills !== null ? (
          <Card aria-labelledby="averages" className="min-w-0 flex-1 basis-75 gap-2 border border-border p-6">
            <h2 id="averages" className="text-lg font-bold">
              Per game
            </h2>
            <span className="text-3xl font-bold tabular-nums">
              {tenths(profile.avg_kills)} / {tenths(profile.avg_deaths ?? 0)} / {tenths(profile.avg_assists ?? 0)}
            </span>
            <span className="text-sm text-muted">
              Kills / deaths / assists
              {profile.avg_damage !== null ? ` · ${thousands(profile.avg_damage)} damage` : ""} · from{" "}
              {plural(profile.scoreboards, "scoreboard")}
            </span>
          </Card>
        ) : null}
        {me ? <Accounts me={me} /> : null}
      </div>

      <MostPlayed recent={profile.recent} />
      <RecentMatches recent={profile.recent} />
    </div>
  );
}

const W = 640;
const H = 180;
const PAD = 12;

/** The rating after each of the recent matches, oldest first. */
function RatingTrend({ recent }: { recent: RecentMatch[] }) {
  const values = [...recent].reverse().map((m) => m.rating_after);
  if (values.length < 2) return null;
  const low = Math.min(...values);
  const high = Math.max(...values);
  const span = high - low || 1;
  const x = (i: number) => (i / (values.length - 1)) * W;
  const y = (v: number) => H - PAD - ((v - low) / span) * (H - PAD * 2);
  const points = values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const first = values[0] ?? 0;
  const last = values.at(-1) ?? 0;
  const label = `Rating went from ${number(first)} to ${number(last)} over the last ${plural(values.length, "match", "matches")}`;
  return (
    <Card aria-labelledby="trend" className="min-w-0 flex-999 basis-140 gap-3.5 border border-border p-6">
      <div className="flex items-baseline justify-between gap-3">
        <h2 id="trend" className="text-lg font-bold">
          Rating
        </h2>
        <span className="text-sm text-muted tabular-nums">
          {number(low)}–{number(high)}
        </span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img" aria-label={label} preserveAspectRatio="none">
        {[0.25, 0.5, 0.75].map((f) => (
          <line key={f} x1={0} x2={W} y1={H * f} y2={H * f} className="stroke-border" strokeWidth={1} vectorEffect="non-scaling-stroke" />
        ))}
        <polyline
          points={points}
          fill="none"
          className="stroke-accent"
          strokeWidth={3}
          strokeLinejoin="round"
          strokeLinecap="round"
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      <div className="flex justify-between text-xs text-muted">
        <span>{plural(values.length, "match", "matches")} ago</span>
        <span>Now</span>
      </div>
    </Card>
  );
}

function Accounts({ me }: { me: MePlayer }) {
  const steam = me.steam;
  const unlink = useUnlinkSteam();
  const [confirming, setConfirming] = useState(false);
  return (
    <Card aria-labelledby="accounts" className="min-w-0 flex-1 basis-85 gap-3 border border-border p-6">
      <h2 id="accounts" className="text-lg font-bold">
        Accounts
      </h2>
      <div className="flex items-center gap-3 rounded-2xl border border-border bg-background p-3.5">
        <span className="flex size-10 items-center justify-center rounded-xl bg-discord text-discord-foreground">
          <DiscordMark width={20} height={20} />
        </span>
        <span className="flex min-w-0 flex-1 flex-col">
          <span className="text-sm font-semibold">Discord</span>
          <span className="truncate text-sm text-muted">{me.name}</span>
        </span>
      </div>
      <div className="flex items-center gap-3 rounded-2xl border border-border bg-background p-3.5">
        <span className="flex size-10 items-center justify-center rounded-xl border border-default bg-steam text-steam-foreground">
          <SteamMark width={20} height={20} />
        </span>
        <span className="flex min-w-0 flex-1 flex-col">
          <span className="text-sm font-semibold">Steam</span>
          <span className="truncate text-sm text-muted">{steam.linked ? steam.name || "Linked" : "Not linked"}</span>
        </span>
        {steam.linked ? (
          <Chip size="sm" variant="soft" color={steam.verified || steam.proven ? "success" : "default"} className="font-semibold">
            {steam.verified ? "Verified" : steam.proven ? "Linked" : "Not proven"}
          </Chip>
        ) : null}
      </div>
      <ButtonLink to="/link-steam" variant={steam.linked ? "outline" : "primary"} className="h-11 font-semibold">
        {steam.linked ? "Link another Steam account" : "Link Steam"}
      </ButtonLink>
      {steam.linked ? (
        <>
          <Button variant="danger-soft" onPress={() => setConfirming(true)} className="h-11 font-semibold">
            Unlink Steam
          </Button>
          <ActionDialog
            isOpen={confirming}
            onOpenChange={setConfirming}
            title="Unlink Steam?"
            confirmLabel="Unlink"
            tone="danger"
            onConfirm={() => unlink.mutateAsync()}
          >
            {steam.name || "Your Steam account"} comes off your profile, and signing in with Steam
            stops working until you link it again.
          </ActionDialog>
        </>
      ) : null}
    </Card>
  );
}

interface Played {
  hero: ChampionRef;
  games: number;
  wins: number;
}

function mostPlayed(recent: RecentMatch[]): Played[] {
  const byHero = new Map<string, Played>();
  for (const match of recent) {
    if (!match.hero) continue;
    const entry = byHero.get(match.hero.id) ?? { hero: match.hero, games: 0, wins: 0 };
    entry.games += 1;
    if (match.result === "win") entry.wins += 1;
    byHero.set(match.hero.id, entry);
  }
  return [...byHero.values()].sort((a, b) => b.games - a.games || a.hero.name.localeCompare(b.hero.name)).slice(0, 4);
}

function MostPlayed({ recent }: { recent: RecentMatch[] }) {
  const heroes = mostPlayed(recent);
  if (heroes.length === 0) return null;
  return (
    <Card aria-labelledby="most-played" className="gap-3.5 border border-border p-6">
      <h2 id="most-played" className="text-lg font-bold">
        Most played
      </h2>
      <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {heroes.map(({ hero, games, wins }) => (
          <li key={hero.id} className="flex items-center gap-3 rounded-2xl border border-border bg-background p-3">
            <HeroArt champion={hero} className="size-11 shrink-0 overflow-hidden rounded-xl" textClass="text-sm" />
            <span className="flex flex-col">
              <span className="text-sm font-semibold">{hero.name}</span>
              <span className="text-sm text-muted tabular-nums">
                {plural(games, "game")} · {winRate(wins, games)}
              </span>
            </span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

const OUTCOME: Record<Outcome, { label: string; color: "success" | "danger" | "default" }> = {
  win: { label: "Win", color: "success" },
  loss: { label: "Loss", color: "danger" },
  void: { label: "Cancelled", color: "default" },
};

function RecentMatches({ recent }: { recent: RecentMatch[] }) {
  return (
    <Card aria-labelledby="recent" className="gap-3.5 border border-border p-6">
      <h2 id="recent" className="text-lg font-bold">
        Recent matches
      </h2>
      {recent.length === 0 ? (
        <p className="text-sm text-muted">No matches this season yet.</p>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {recent.map((match) => {
            const outcome = match.result ? OUTCOME[match.result] : null;
            return (
              <li key={match.match_id} className="flex items-center gap-3 rounded-xl bg-background px-3 py-2 text-sm">
                {match.hero ? (
                  <HeroArt champion={match.hero} className="size-9 shrink-0 overflow-hidden rounded-lg" textClass="text-xs" />
                ) : (
                  <span className="size-9 shrink-0 rounded-lg bg-surface-secondary" aria-hidden="true" />
                )}
                <span className="flex min-w-0 flex-1 flex-col">
                  <Link to={`/matches/${match.match_id}`} className="font-semibold hover:underline">
                    Match {match.match_id}
                  </Link>
                  <span className="truncate text-xs text-muted">{match.hero?.name ?? "Hero not known"}</span>
                </span>
                {outcome ? (
                  <Chip size="sm" variant="soft" color={outcome.color} className="font-semibold">
                    {outcome.label}
                  </Chip>
                ) : (
                  <Chip size="sm" variant="soft">
                    Pending
                  </Chip>
                )}
                <span className="flex w-16 flex-col items-end tabular-nums">
                  <span className={`font-semibold ${deltaClass(match.delta)}`}>{signed(match.delta)}</span>
                  <span className="text-xs text-muted">{number(match.rating_after)}</span>
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
