// The pages that aren't live: finished matches, one match's record, the leaderboard, profiles
// and the random draft (league/web/api/views.py). Live state comes over the websocket instead.
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type {
  Leaderboard,
  MatchDetail,
  MatchList,
  PlayerProfile,
  RandomDraft,
  SeasonList,
  SteamUnlinked,
} from "../live/types";
import { getJson, HttpError, postJson } from "./http";
import { SESSION_KEY } from "./session";

/** The path with these query parameters, leaving out the null ones. */
function withQuery(path: string, params: Record<string, string | null>): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) if (value !== null) query.set(key, value);
  const text = query.toString();
  return text ? `${path}?${text}` : path;
}

/** A 404 won't change on a second try; anything else gets one more. */
function retryUnlessMissing(failures: number, error: Error): boolean {
  return !(error instanceof HttpError && error.status === 404) && failures < 1;
}

export function isNotFound(error: unknown): boolean {
  return error instanceof HttpError && error.status === 404;
}

/** GET /api/matches/<id>/: a match's record, rating changes and awards included. Pass null to
 * ask nothing (a live match the snapshot already covers). */
export function useMatchDetail(id: string | null) {
  return useQuery({
    queryKey: ["matches", id],
    queryFn: () => getJson<MatchDetail>(`/api/matches/${id}/`),
    enabled: id !== null,
    retry: retryUnlessMissing,
    // Awards and corrections can come later, but not by the second.
    staleTime: 30_000,
  });
}

/** GET /api/matches/?status=recent: this season's finished matches, newest first, a page at a
 * time. `mine`: only the viewer's. */
export function useRecentMatches(mine: boolean) {
  return useInfiniteQuery({
    queryKey: ["matches", "recent", mine],
    queryFn: ({ pageParam }) => {
      const query = new URLSearchParams({ status: "recent" });
      if (mine) query.set("mine", "1");
      if (pageParam) query.set("cursor", pageParam);
      return getJson<MatchList>(`/api/matches/?${query.toString()}`);
    },
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    staleTime: 30_000,
  });
}

/** GET /api/seasons/: the server's seasons, newest first. */
export function useSeasons() {
  return useQuery({
    queryKey: ["seasons"],
    queryFn: () => getJson<SeasonList>("/api/seasons/"),
    staleTime: 5 * 60_000,
  });
}

/** GET /api/leaderboard/: a season's table (the open one for null), a page at a time, with the
 * viewer's own row on every page. */
export function useLeaderboard(season: string | null) {
  return useInfiniteQuery({
    queryKey: ["leaderboard", season],
    queryFn: ({ pageParam }) =>
      getJson<Leaderboard>(withQuery("/api/leaderboard/", { season, offset: pageParam ? String(pageParam) : null })),
    initialPageParam: 0,
    getNextPageParam: (last) => last.next_offset,
    retry: retryUnlessMissing,
    staleTime: 30_000,
  });
}

/** GET /api/players/<id>/: their season (the open one for null). */
export function usePlayerProfile(id: string, season: string | null) {
  return useQuery({
    queryKey: ["players", id, season],
    queryFn: () => getJson<PlayerProfile>(withQuery(`/api/players/${id}/`, { season })),
    retry: retryUnlessMissing,
    staleTime: 30_000,
  });
}

/** POST /api/steam/unlink/: the web's /unlink. The session and profiles say so afterwards. */
export function useUnlinkSteam() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => postJson<SteamUnlinked>("/api/steam/unlink/"),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: SESSION_KEY });
      void client.invalidateQueries({ queryKey: ["players"] });
    },
  });
}

/** POST /api/tools/random-draft/: every ban and pick at random. Nothing is recorded. */
export function useRandomDraft() {
  return useMutation({
    mutationFn: () => postJson<RandomDraft>("/api/tools/random-draft/"),
  });
}
