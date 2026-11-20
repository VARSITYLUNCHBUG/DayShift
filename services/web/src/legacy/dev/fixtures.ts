// The snapshot fixtures Django writes (tests/test_web_fixtures.py), for tests and the screen
// gallery. Never imported by the app itself, so they stay out of the build.
import type {
  Leaderboard,
  LeaderboardEntry,
  LiveSnap,
  MatchDetail,
  MatchList,
  MatchSnap,
  MeSnap,
  PlayerProfile,
  QueueSnap,
  RandomDraft,
  SearchPlayer,
  SeasonList,
  SubOutOptions,
} from "../../live/types";

const files = import.meta.glob<unknown>("../fixtures/*.json", { eager: true, import: "default" });

const byName = new Map(
  Object.entries(files).map(([path, data]) => [path.replace(/^.*\/(.+)\.json$/, "$1"), data]),
);

export type MatchView = "captain" | "player" | "spectator";

function load<T>(name: string): T {
  const data = byName.get(name);
  if (data === undefined) throw new Error(`No fixture called ${name}.json`);
  // A fresh copy each time, so a test can change one without touching the next.
  return structuredClone(data) as T;
}

export function has(name: string): boolean {
  return byName.has(name);
}

export const fixture = {
  match: (scenario: string, view: MatchView) => load<MatchSnap>(`${scenario}.${view}`),
  me: (scenario: string, view: MatchView) => load<MeSnap>(`${scenario}.me-${view}`),
  queue: (scenario: string) => load<QueueSnap>(`${scenario}.queue`),
  live: (scenario: string) => load<LiveSnap>(`${scenario}.live`),
};

/** Every scenario, in the order the match goes. */
export const SCENARIOS = [
  "ready_check",
  "voided_ready_check",
  "captain_phase",
  "player_draft",
  "player_draft_sub_open",
  "player_draft_sub_approval",
  "player_draft_sub_naming",
  "coinflip",
  "champion_draft",
  "lobby_code",
  "in_progress",
  "in_progress_sub_offered",
  "in_progress_early_leave",
  "awaiting_confirmation",
  "awaiting_confirmation_scoreboard",
  "disputed",
  "completed",
  "ready_check_refill",
  "scrim_captain_claim",
  "scrim_coinflip",
  "scrim_ready_to_draft",
  "scrim_champion_draft",
  "scrim_drafted",
] as const;

export const VIEWS: readonly MatchView[] = ["captain", "player", "spectator"];

/** The fixtures' clock: a ready check that opened at 19:00:00 has 2:41 left. */
export const FIXTURE_NOW = "2026-01-05T19:00:19.000Z";

/** A ready check that closed short: one player missed it and their seat is offered on. */
export function needSubMatch(): MatchSnap {
  const match = fixture.match("ready_check", "player");
  const missed = match.players.find((p) => p.id === "9");
  match.players = match.players
    .filter((p) => p !== missed)
    .map((p) => ({ ...p, is_ready: true }));
  match.on_hold = true;
  match.hold_until = "2026-01-05T19:02:07.000Z";
  match.subs = [
    {
      id: "1",
      status: "open",
      reason: "missed_ready",
      leaving_id: missed?.id ?? "9",
      leaving_name: missed?.name ?? "P9",
      team: null,
      requested_by_id: null,
      requested_by_name: null,
      is_self: false,
      deadline_at: "2026-01-05T19:02:07.000Z",
      name_until: null,
      offer: { player_id: "13", name: "P13", source: "queue", deadline_at: "2026-01-05T19:00:49.000Z" },
    },
  ];
  return match;
}

/** Not queued, but holding a place on the priority list for a while. */
export function placeHeldMe(): MeSnap {
  const me = fixture.me("completed", "player");
  me.queue = {
    in_queue: false,
    position: null,
    joined_at: null,
    place: { position: 2, total: 9, held_until: "2026-01-05T19:03:00.000Z" },
  };
  return me;
}

/** A captain vote where two players can't captain yet under the mode's rule. */
export function ineligibleVoteMatch(): MatchSnap {
  const match = fixture.match("captain_phase", "player");
  match.captain_min_games = 5;
  match.players = match.players.map((p) =>
    p.id === "5" ? { ...p, captain_ok: false, captain_note: "3/5 matches" } : p.id === "6" ? { ...p, captain_ok: false, captain_note: "3 strikes" } : p,
  );
  return match;
}

/** Auto Captain on: the server skips the vote, so this only shows if a vote ever slips through. */
export function autoCaptainMe(): MeSnap {
  const me = fixture.me("captain_phase", "player");
  me.flags = { ...me.flags, auto_captain: true };
  return me;
}

/** The hero draft from the other captain's side (P2, Team A): P1 is banning. */
export function waitingDraft(): { match: MatchSnap; me: MeSnap } {
  const match = fixture.match("champion_draft", "captain");
  match.viewer = { ...match.viewer, team: "A", is_acting: false };
  const me = fixture.me("champion_draft", "captain");
  me.player = { ...me.player, id: "2", name: "P2", avatar_url: null };
  me.match = me.match ? { ...me.match, team: "A" } : null;
  return { match, me };
}

/** A bot-hosted lobby (auto lobby) that no captain has started yet. */
export function apiLobbyMatch(view: "captain" | "player" | "spectator"): MatchSnap {
  const match = fixture.match("in_progress", view);
  match.lobby = {
    auto_lobby: true,
    api_lobby: true,
    api_started: false,
    api_leaves_at: "2026-01-05T19:15:00.000Z",
  };
  return match;
}

/** What `subs.options` answers for this viewer: themself, plus their team's other players if
 * they captain. Before the game it's a dodge, once it's on it's leaving a game. */
export function subOptions(match: MatchSnap, myId: string): SubOutOptions {
  const me = match.players.find((p) => p.id === myId);
  const teammates = me?.is_captain ? match.players.filter((p) => p.team === me.team && !p.is_captain) : [];
  const gameOn = match.status === "in_progress";
  return {
    choices: [
      { player_id: myId, name: me?.name ?? "You", is_self: true },
      ...teammates.map((p) => ({ player_id: p.id, name: p.name, is_self: false })),
    ],
    game_on: gameOn,
    dodge: !gameOn && match.status !== "ready_check",
    strikes: match.status === "ready_check" ? 0 : 2,
  };
}

/** `GET /api/players/search/?q=p1`, as the naming dialog would get it. */
export const SEARCH_RESULTS: SearchPlayer[] = [
  { id: "13", name: "P13", avatar_url: null, in_match: false, on_cooldown: false, in_queue: true, rating: 1250 },
  { id: "14", name: "P14", avatar_url: null, in_match: false, on_cooldown: false, in_queue: false, rating: 1305 },
  { id: "15", name: "P15", avatar_url: null, in_match: true, on_cooldown: false, in_queue: false, rating: 1199 },
  { id: "16", name: "P16", avatar_url: null, in_match: false, on_cooldown: true, in_queue: false, rating: 1180 },
];

/** In a live match: Play shows the match, not the queue. */
export function inMatchMe(): MeSnap {
  return fixture.me("player_draft", "player");
}

/** What the HTTP API answers about the finished match (completed.http-*.json), as its player
 * (P3, team A) asks. */
export const http = {
  match: () => load<MatchDetail>("completed.http-match"),
  matches: () => load<MatchList>("completed.http-matches"),
  leaderboard: () => load<Leaderboard>("completed.http-leaderboard"),
  profile: () => load<PlayerProfile>("completed.http-profile"),
  randomDraft: () => load<RandomDraft>("completed.http-random-draft"),
  seasons: () => load<SeasonList>("completed.http-seasons"),
};

/** The open season and one before it. */
export function twoSeasons(): SeasonList {
  const [open] = http.seasons().seasons;
  return { seasons: [open!, { id: "7", name: "Preseason", is_open: false }] };
}

const KDA = ["14/3/9", "11/5/6", "4/6/12", "7/7/8", "6/4/7", "2/5/18"];

/** The finished match's record with what a real one carries: awards, stat lines, ratings, the
 * length, deadlock's match ID, and a forecast that made B's win an upset. */
export function recordedMatch(): MatchDetail {
  const detail = http.match();
  detail.duration_s = 1912;
  detail.deadlock_match_id = "38204912";
  detail.win_chance_a = 0.63;
  const awards: Record<string, "mvp" | "key"> = { "1": "mvp", "4": "key", "2": "key" };
  detail.teams = detail.teams.map((team, t) => ({
    ...team,
    average_rating: 1240 + t * 12,
    players: team.players.map((p, i) => {
      const before = 1180 + i * 37 + t * 11;
      const delta = team.team === detail.winner ? 24 + i : -(19 + i);
      return {
        ...p,
        rating_before: before,
        rating_after: before + delta,
        delta,
        award: awards[p.id] ?? null,
        stat_line: `${team.picks[i]?.name ?? "Hero"} ${KDA[i]}, ${31 - i * 3}k damage`,
      };
    }),
  }));
  return detail;
}

/** A finished list with more in it: the match above, then three made-up older ones (one
 * cancelled, one a scrim; their IDs are only for the list), and a next page. */
export function matchList(): MatchList {
  const list = http.matches();
  const first = list.matches[0]!;
  const older = [
    { ...first, id: "17", draft_name: "Quiet Heron", winner: "A" as const, your_team: null, ended_at: "2026-01-05T15:10:00.000Z" },
    { ...first, id: "16", draft_name: "Pale Comet", status: "voided" as const, winner: null, ended_at: "2026-01-04T21:40:00.000Z" },
    {
      ...first,
      id: "15",
      kind: "scrim" as const,
      status: "drafted" as const,
      draft_name: "Low Tide",
      winner: null,
      your_team: null,
      ended_at: "2025-12-30T20:00:00.000Z",
    },
  ];
  return { matches: [...list.matches, ...older], next_cursor: "15" };
}

const BOARD_NAMES = ["Pike", "Vesper", "Mothball", "Juniper", "Delta", "P3", "Tikka", "Azimuth", "Orrin", "Lumen"];
const TIERS_BY_RATING: [number, string, number][] = [
  [1400, "Diamond", 4],
  [1300, "Platinum", 3],
  [1200, "Gold", 2],
  [1100, "Silver", 1],
  [0, "Bronze", 0],
];

function tierOf(rating: number): { tier: string; tier_level: number } {
  const [, tier, level] = TIERS_BY_RATING.find(([floor]) => rating >= floor)!;
  return { tier, tier_level: level };
}

/** A season well under way, the viewer (P3) sixth. `pinned`: they're short of the minimum, so
 * the list leaves them out and their own row is added at the foot. */
export function seasonLeaderboard(pinned = false): Leaderboard {
  const board = http.leaderboard();
  const rows: LeaderboardEntry[] = BOARD_NAMES.map((name, i) => {
    const rating = 1452 - i * 41;
    const wins = 41 - i * 3;
    const losses = 22 + (i % 3);
    return {
      rank: i + 1,
      player: { id: name === "P3" ? "3" : String(100 + i), name, avatar_url: null },
      rating,
      games: wins + losses,
      wins,
      losses,
      ...tierOf(rating),
    };
  });
  if (!pinned) {
    board.rows = rows;
    board.me = rows.find((r) => r.player.id === "3")!;
    return board;
  }
  board.rows = rows.filter((r) => r.player.id !== "3");
  board.me = { rank: null, player: { id: "3", name: "P3", avatar_url: null }, rating: 1188, games: 6, wins: 4, losses: 2, ...tierOf(1188) };
  return board;
}

/** P3's season: placed, a strike coming off, scoreboard averages, and recent matches with
 * heroes. `placing`: still in their placement matches instead. */
export function seasonProfile(placing = false): PlayerProfile {
  const profile = http.profile();
  const heroes = recordedMatch().teams.flatMap((t) => t.picks);
  const results = ["win", "win", "loss", "win", "loss", "void", "win", "loss", "win", "win"] as const;
  let rating = 1284;
  profile.recent = results.map((result, i) => {
    const delta = result === "win" ? 27 - i : result === "loss" ? -(22 - i) : 0;
    const entry = { match_id: String(40 - i), result, hero: heroes[i % 4] ?? null, delta, rating_after: rating };
    rating -= delta;
    return entry;
  });
  Object.assign(profile, {
    rating: 1284,
    games: 46,
    wins: 27,
    losses: 19,
    rank: 6,
    tier: "Gold",
    tier_level: 2,
    placement: placing ? { played: 3, total: 10 } : null,
    strikes: { count: 1, games_to_next: 2, next_decay_at: null },
    mvps: 6,
    keys: 11,
    scoreboards: 31,
    avg_kills: 8.24,
    avg_deaths: 5.1,
    avg_assists: 9.93,
    avg_damage: 28_400,
    steam: { linked: true, verified: true },
  });
  return profile;
}
