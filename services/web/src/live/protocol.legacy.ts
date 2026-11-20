/* PLACEHOLDER: the old branch's generated protocol (web-asgi-groundwork), kept so the old screens
 * and the live client compile until they move to protocol.gen.ts (generated from BE-LIVE's
 * protocol.schema.json by `npm run gen`). Do not edit; delete it when nothing imports it.
 */

/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "ClientMessage".
 */
export type ClientMessage = Subscribe | Unsubscribe | Ping | Act;
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "ServerMessage".
 */
export type ServerMessage =
  Hello | MeSnapMessage | QueueSnapMessage | LiveSnapMessage | MatchSnapMessage | Gone | Pong | Ack;
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "Id".
 */
export type Id = string;
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "PenaltyKind".
 */
export type PenaltyKind = "missed_ready" | "dodge" | "leaver" | "false_report" | "manual";
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "MatchStatus".
 */
export type MatchStatus =
  | "ready_check"
  | "captain_phase"
  | "player_draft"
  | "coinflip"
  | "champion_draft"
  | "lobby_code"
  | "in_progress"
  | "awaiting_confirmation"
  | "disputed"
  | "completed"
  | "voided"
  | "captain_claim"
  | "ready_to_draft"
  | "drafted";
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "MatchKind".
 */
export type MatchKind = "ranked" | "scrim";
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "Team".
 */
export type Team = "A" | "B";
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "OfferSource".
 */
export type OfferSource = "invite" | "prio" | "queue";
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "OfferEndStatus".
 */
export type OfferEndStatus = "accepted" | "declined" | "expired" | "failed" | "withdrawn";
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "ScoreOcr".
 */
export type ScoreOcr = "off" | "shadow" | "on";
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "Side".
 */
export type Side = "hk" | "am";
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "DraftActionKind".
 */
export type DraftActionKind = "player_pick" | "ban" | "pick";
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "ChampionAction".
 */
export type ChampionAction = "ban" | "pick";
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "CoinflipChoice".
 */
export type CoinflipChoice =
  | "hk_pick1"
  | "hk_pick2"
  | "am_pick1"
  | "am_pick2"
  | "first_pick"
  | "last_pick"
  | "hidden_king"
  | "archmother";
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "Verdict".
 */
export type Verdict = "report" | "confirm" | "dispute";
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "SubStatus".
 */
export type SubStatus = "approval" | "open";
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "SubReason".
 */
export type SubReason = "sub_out" | "missed_ready" | "restart";
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "SubDoneStatus".
 */
export type SubDoneStatus = "filled" | "cancelled" | "rejected" | "expired";
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "ActionResult".
 */
export type ActionResult = RandomChampion | SubRequested | SubOutOptions;
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "ErrorCode".
 */
export type ErrorCode = "signed-out" | "not-found" | "bad-request" | "not-set-up";
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "Award".
 */
export type Award = "mvp" | "key";
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "Outcome".
 */
export type Outcome = "win" | "loss" | "void";

/**
 * Messages on the player web UI's websocket, /ws/, and the HTTP API's responses, /api/.
 */
export interface LiveProtocol {
  client?: ClientMessage;
  server?: ServerMessage;
  http?: HttpApi;
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "Subscribe".
 */
export interface Subscribe {
  t: "sub";
  topics: string[];
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "Unsubscribe".
 */
export interface Unsubscribe {
  t: "unsub";
  topics: string[];
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "Ping".
 */
export interface Ping {
  t: "ping";
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "Act".
 */
export interface Act {
  t: "act";
  id: string;
  name: string;
  args?: {
    [k: string]: unknown | undefined;
  };
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "Hello".
 */
export interface Hello {
  t: "hello";
  server_time: string;
  player_id: Id;
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "MeSnapMessage".
 */
export interface MeSnapMessage {
  t: "snap";
  topic: "me";
  rev: number;
  data: MeSnap;
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "MeSnap".
 */
export interface MeSnap {
  player: MePlayer;
  queue: MeQueue;
  cooldown: Cooldown | null;
  match: MeMatch | null;
  scrim: MeMatch | null;
  offers: Offer[];
  last_offer: OfferEnd | null;
  strikes: number;
  flags: Flags;
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "MePlayer".
 */
export interface MePlayer {
  id: Id;
  name: string;
  avatar_url: string | null;
  steam: SteamState;
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "SteamState".
 */
export interface SteamState {
  linked: boolean;
  proven: boolean;
  verified: boolean;
  name: string;
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "MeQueue".
 */
export interface MeQueue {
  in_queue: boolean;
  position: number | null;
  joined_at: string | null;
  place: QueuePlace | null;
}
/**
 * The player's own place on the priority list. Nobody else's is ever sent.
 *
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "QueuePlace".
 */
export interface QueuePlace {
  position: number;
  total: number;
  held_until: string | null;
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "Cooldown".
 */
export interface Cooldown {
  until: string;
  text: string;
  kind: PenaltyKind;
  strikes: number;
  games_to_next: number | null;
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "MeMatch".
 */
export interface MeMatch {
  id: Id;
  status: MatchStatus;
  kind: MatchKind;
  team: Team | null;
  is_captain: boolean;
}
/**
 * A spot in someone else's match, offered to this player.
 *
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "Offer".
 */
export interface Offer {
  id: Id;
  match_id: Id;
  deadline_at: string;
  source: OfferSource;
  team: Team | null;
  team_name: string | null;
  leaving_name: string;
  invited_by_name: string | null;
  match_status: MatchStatus;
  started_at: string | null;
}
/**
 * The player's most recent offer that has ended, so the page can say how.
 *
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "OfferEnd".
 */
export interface OfferEnd {
  id: Id;
  match_id: Id;
  status: OfferEndStatus;
  team_name: string | null;
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "Flags".
 */
export interface Flags {
  auto_captain: boolean;
  auto_lobby: boolean;
  api_results: boolean;
  score_ocr: ScoreOcr;
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "QueueSnapMessage".
 */
export interface QueueSnapMessage {
  t: "snap";
  topic: "queue";
  rev: number;
  data: QueueSnap;
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "QueueSnap".
 */
export interface QueueSnap {
  size: number;
  count: number;
  players: PlayerRef[];
  mode_name: string;
  max_concurrent: number;
  live_matches: number;
  open: boolean;
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "PlayerRef".
 */
export interface PlayerRef {
  id: Id;
  name: string;
  avatar_url: string | null;
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "LiveSnapMessage".
 */
export interface LiveSnapMessage {
  t: "snap";
  topic: "live";
  rev: number;
  data: LiveSnap;
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "LiveSnap".
 */
export interface LiveSnap {
  matches: LiveMatch[];
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "LiveMatch".
 */
export interface LiveMatch {
  id: Id;
  status: MatchStatus;
  kind: MatchKind;
  mode_name: string;
  draft_name: string;
  captains: ByTeam;
  sides: Sides;
  started_at: string | null;
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "ByTeam".
 */
export interface ByTeam {
  A: string | null;
  B: string | null;
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "Sides".
 */
export interface Sides {
  A: Side | null;
  B: Side | null;
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "MatchSnapMessage".
 */
export interface MatchSnapMessage {
  t: "snap";
  topic: string;
  rev: number;
  data: MatchSnap;
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "MatchSnap".
 */
export interface MatchSnap {
  id: Id;
  status: MatchStatus;
  kind: MatchKind;
  mode_name: string;
  deadline_at: string | null;
  closes_at: string | null;
  started_at: string | null;
  players: MatchPlayer[];
  captains: ByTeam;
  team_names: ByTeam;
  sides: Sides;
  draft: DraftEntry[];
  turn: Turn | null;
  step_index: number;
  player_draft_order: PlayerDraftStep[];
  champion_steps: ChampionStep[];
  champion_step: number | null;
  champions: ChampionChoice[];
  coinflip: Coinflip | null;
  host: Host | null;
  lobby_code: string | null;
  result: Result;
  subs: SubEntry[];
  subs_done: SubDone[];
  on_hold: boolean;
  hold_until: string | null;
  early_leave: EarlyLeave;
  lobby: Lobby;
  win_chance_a: number | null;
  captain_min_games: number;
  votes_per_player: number;
  draft_name: string;
  gif_url: string | null;
  restarted_from: Id | null;
  scoreboard: Scoreboard | null;
  viewer: Viewer;
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "MatchPlayer".
 */
export interface MatchPlayer {
  id: Id;
  name: string;
  avatar_url: string | null;
  rating: number;
  team: Team | null;
  is_captain: boolean;
  is_ready: boolean;
  has_voted: boolean;
  captain_ok: boolean;
  captain_note: string;
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "DraftEntry".
 */
export interface DraftEntry {
  action: DraftActionKind;
  team: Team | null;
  label: string;
  auto: boolean;
  random: boolean;
  player_id: Id | null;
  champion: ChampionRef | null;
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "ChampionRef".
 */
export interface ChampionRef {
  id: Id;
  name: string;
  slug: string;
  icon_url: string | null;
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "Turn".
 */
export interface Turn {
  team: Team;
  captain_id: Id | null;
  captain_name: string;
  action: DraftActionKind;
  position: number;
  total: number;
  next_captain_name: string | null;
  next_action: DraftActionKind | null;
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "PlayerDraftStep".
 */
export interface PlayerDraftStep {
  step_index: number;
  team: Team;
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "ChampionStep".
 */
export interface ChampionStep {
  action: ChampionAction;
  side: Side;
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "ChampionChoice".
 */
export interface ChampionChoice {
  id: Id;
  name: string;
  slug: string;
  icon_url: string | null;
  taken: boolean;
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "Coinflip".
 */
export interface Coinflip {
  winner: Team | null;
  winner_choice: CoinflipChoice | null;
  loser_choice: CoinflipChoice | null;
  options: CoinflipChoice[];
  chooser_team: Team | null;
  chooser_id: Id | null;
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "Host".
 */
export interface Host {
  id: Id;
  name: string;
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "Result".
 */
export interface Result {
  winner: Team | null;
  reported_winner: Team | null;
  reported_by_id: Id | null;
  reported_by_name: string | null;
  deltas: {
    [k: string]: number | undefined;
  };
  responses: ResultResponse[];
  void_reason: string | null;
}
/**
 * One captain's answer: a report, or a confirm or dispute of the other captain's.
 *
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "ResultResponse".
 */
export interface ResultResponse {
  player_id: Id;
  name: string;
  verdict: Verdict;
  winner: Team | null;
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "SubEntry".
 */
export interface SubEntry {
  id: Id;
  status: SubStatus;
  reason: SubReason;
  leaving_id: Id | null;
  leaving_name: string;
  team: Team | null;
  requested_by_id: Id | null;
  requested_by_name: string | null;
  is_self: boolean;
  deadline_at: string;
  name_until: string | null;
  offer: SubOfferRef | null;
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "SubOfferRef".
 */
export interface SubOfferRef {
  player_id: Id;
  name: string;
  source: OfferSource;
  deadline_at: string | null;
}
/**
 * A sub request that has ended.
 *
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "SubDone".
 */
export interface SubDone {
  id: Id;
  status: SubDoneStatus;
  reason: SubReason;
  leaving_id: Id;
  leaving_name: string;
  team: Team | null;
  joined_id: Id | null;
  joined_name: string | null;
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "EarlyLeave".
 */
export interface EarlyLeave {
  open: boolean;
  minutes: number;
  pending: EarlyLeaveClaim | null;
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "EarlyLeaveClaim".
 */
export interface EarlyLeaveClaim {
  leaver_id: Id | null;
  leaver_name: string;
  by_id: Id | null;
  by_name: string;
  deadline_at: string;
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "Lobby".
 */
export interface Lobby {
  auto_lobby: boolean;
  api_lobby: boolean;
  api_started: boolean;
  api_leaves_at: string | null;
}
/**
 * Names on the latest scoreboard read that nobody has matched to a player yet. Only ever
 * sent to the match's captains, who can match them.
 *
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "Scoreboard".
 */
export interface Scoreboard {
  read_id: Id;
  rows: ScoreboardRow[];
  players: ScoreboardPlayer[];
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "ScoreboardRow".
 */
export interface ScoreboardRow {
  row: number;
  name: string;
  team: Team;
  hero: ChampionRef | null;
  hero_name: string;
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "ScoreboardPlayer".
 */
export interface ScoreboardPlayer {
  id: Id;
  name: string;
  team: Team;
}
/**
 * What the page needs to know about whoever is looking.
 *
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "Viewer".
 */
export interface Viewer {
  is_player: boolean;
  team: Team | null;
  is_captain: boolean;
  is_acting: boolean;
  has_voted: boolean;
  votes: Id[];
  can_request_sub: boolean;
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "Gone".
 */
export interface Gone {
  t: "gone";
  topic: string;
  reason: "not_found";
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "Pong".
 */
export interface Pong {
  t: "pong";
  server_time: string;
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "Ack".
 */
export interface Ack {
  t: "ack";
  id: string;
  ok: boolean;
  error: string | null;
  result: ActionResult | null;
}
/**
 * `draft.random_champion`: the hero it took.
 *
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "RandomChampion".
 */
export interface RandomChampion {
  champion_id: Id;
}
/**
 * `subs.request`: the request it opened.
 *
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "SubRequested".
 */
export interface SubRequested {
  request_id: Id;
}
/**
 * `subs.options`: who this player may ask to sub out, and what it would cost them.
 *
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "SubOutOptions".
 */
export interface SubOutOptions {
  choices: SubOutChoice[];
  game_on: boolean;
  dodge: boolean;
  strikes: number;
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "SubOutChoice".
 */
export interface SubOutChoice {
  player_id: Id;
  name: string;
  is_self: boolean;
}
/**
 * Each endpoint's response body, for the generated types. Never sent itself.
 *
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "HttpApi".
 */
export interface HttpApi {
  error: ApiError;
  refusal: Refusal;
  report: ReportDone;
  matches: MatchList;
  match: MatchDetail;
  leaderboard: Leaderboard;
  seasons: SeasonList;
  player: PlayerProfile;
  steam_unlinked: SteamUnlinked;
  player_search: PlayerSearch;
  random_draft: RandomDraft;
}
/**
 * Any refusal. `not-set-up`: the web's server has no league or no open season yet.
 *
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "ApiError".
 */
export interface ApiError {
  error: ErrorCode;
}
/**
 * The report wasn't taken. A plain sentence for the player, as the Discord bot says it.
 *
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "Refusal".
 */
export interface Refusal {
  error: string;
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "ReportDone".
 */
export interface ReportDone {
  status: MatchStatus;
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "MatchList".
 */
export interface MatchList {
  matches: MatchRow[];
  next_cursor: string | null;
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "MatchRow".
 */
export interface MatchRow {
  id: Id;
  status: MatchStatus;
  kind: MatchKind;
  mode_name: string;
  draft_name: string;
  captains: ByTeam;
  team_names: ByTeam;
  sides: Sides;
  winner: Team | null;
  started_at: string | null;
  ended_at: string | null;
  your_team: Team | null;
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "MatchDetail".
 */
export interface MatchDetail {
  id: Id;
  status: MatchStatus;
  kind: MatchKind;
  mode_name: string;
  winner: Team | null;
  started_at: string | null;
  ended_at: string | null;
  duration_s: number | null;
  teams: TeamResult[];
  draft: DraftPick[];
  win_chance_a: number | null;
  draft_name: string;
  gif_url: string | null;
  deadlock_match_id: Id | null;
  your_team: Team | null;
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "TeamResult".
 */
export interface TeamResult {
  team: Team;
  name: string | null;
  side: Side | null;
  average_rating: number | null;
  players: ResultPlayer[];
  picks: ChampionRef[];
  bans: ChampionRef[];
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "ResultPlayer".
 */
export interface ResultPlayer {
  id: Id;
  name: string;
  avatar_url: string | null;
  is_captain: boolean;
  rating_before: number;
  rating_after: number;
  delta: number;
  award: Award | null;
  stat_line: string | null;
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "DraftPick".
 */
export interface DraftPick {
  action: ChampionAction;
  team: Team;
  champion: ChampionRef;
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "Leaderboard".
 */
export interface Leaderboard {
  season: string;
  season_id: Id;
  min_games: number;
  tiers: string[];
  rows: LeaderboardEntry[];
  me: LeaderboardEntry | null;
  next_offset: number | null;
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "LeaderboardEntry".
 */
export interface LeaderboardEntry {
  rank: number | null;
  player: PlayerRef;
  rating: number;
  games: number;
  wins: number;
  losses: number;
  tier: string;
  tier_level: number;
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "SeasonList".
 */
export interface SeasonList {
  seasons: SeasonRef[];
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "SeasonRef".
 */
export interface SeasonRef {
  id: Id;
  name: string;
  is_open: boolean;
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "PlayerProfile".
 */
export interface PlayerProfile {
  player: PlayerRef;
  is_you: boolean;
  season: string;
  season_id: Id;
  rating: number;
  games: number;
  wins: number;
  losses: number;
  rank: number | null;
  tier: string;
  tier_level: number;
  tiers: string[];
  placement: Placement | null;
  strikes: Strikes;
  captain: CaptainStatus;
  mvps: number;
  keys: number;
  scoreboards: number;
  avg_kills: number | null;
  avg_deaths: number | null;
  avg_assists: number | null;
  avg_damage: number | null;
  steam: SteamBadge;
  recent: RecentMatch[];
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "Placement".
 */
export interface Placement {
  played: number;
  total: number;
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "Strikes".
 */
export interface Strikes {
  count: number;
  games_to_next: number | null;
  next_decay_at: string | null;
}
/**
 * Whether they can be a captain now, under the mode's rule. Not per season.
 *
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "CaptainStatus".
 */
export interface CaptainStatus {
  eligible: boolean;
  reason: string;
}
/**
 * Whether they've linked Steam. Never the account itself.
 *
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "SteamBadge".
 */
export interface SteamBadge {
  linked: boolean;
  verified: boolean;
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "RecentMatch".
 */
export interface RecentMatch {
  match_id: Id;
  result: Outcome | null;
  hero: ChampionRef | null;
  delta: number;
  rating_after: number;
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "SteamUnlinked".
 */
export interface SteamUnlinked {
  unlinked: boolean;
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "PlayerSearch".
 */
export interface PlayerSearch {
  players: SearchPlayer[];
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "SearchPlayer".
 */
export interface SearchPlayer {
  id: Id;
  name: string;
  avatar_url: string | null;
  in_match: boolean;
  on_cooldown: boolean;
  in_queue: boolean;
  rating: number;
}
/**
 * Every ban and pick in the mode's order, chosen at random. Nothing is recorded.
 *
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "RandomDraft".
 */
export interface RandomDraft {
  hk: DraftSide;
  am: DraftSide;
}
/**
 * This interface was referenced by `LiveProtocol`'s JSON-Schema
 * via the `definition` "DraftSide".
 */
export interface DraftSide {
  bans: ChampionRef[];
  picks: ChampionRef[];
}
