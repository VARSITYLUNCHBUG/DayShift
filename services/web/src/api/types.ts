// The HTTP API's bodies (league/web/api/schema.py), from the generated protocol. Pages import
// them from here so they never depend on the old protocol's names.
export type {
  ApiError,
  Award,
  Beat,
  ChampionRef,
  Death,
  DraftPick,
  DraftSide,
  Event as MatchEvent,
  Fight,
  HeroGames,
  Ladder,
  LadderRow,
  LeagueAward,
  MatchDetail,
  MatchList,
  MatchRow,
  MatchStatus,
  MyProfile,
  Objective,
  Outcome,
  PendingReason,
  PlayerLine,
  Postgame,
  PostgamePending,
  PostgameReady,
  RandomDraft,
  RatingPoint,
  RecentMatch,
  ResultPlayer,
  SeasonList,
  SeasonRef,
  Side,
  SteamRow,
  SteamUnlinked,
  StrikeEntry,
  Strikes,
  Structure,
  Team,
  TeamResult,
  YourNight,
} from "../live/protocol.gen";

import type { PostgamePending, PostgameReady } from "../live/protocol.gen";

/** GET /api/matches/<id>/postgame/. */
export type PostgameBody = PostgameReady | PostgamePending;
