// The pages that aren't live, over the HTTP API (league/web/api/views.py): matches, a match and
// its postgame, the ladder, seasons, your own profile and the tools. Each read is a query-options
// factory, so a page and a hover prefetch share one cache entry.
import { infiniteQueryOptions, queryOptions, useMutation, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";

import { getJson, HttpError, postJson } from "./http";
import { SESSION_KEY } from "./session";
import type { Ladder, MatchDetail, MatchList, MyProfile, PostgameBody, RandomDraft, SeasonList, SteamUnlinked } from "./types";

/** The path with these query parameters, leaving out the null ones. */
export function withQuery(path: string, params: Record<string, string | null | undefined>): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) if (value !== null && value !== undefined) query.set(key, value);
  const text = query.toString();
  return text ? `${path}?${text}` : path;
}

/** A 404 (or a bad link) won't change on a second try; anything else gets one more. */
export function retryUnlessMissing(failures: number, error: Error): boolean {
  if (error instanceof HttpError && [400, 401, 403, 404].includes(error.status)) return false;
  return failures < 1;
}

export function isNotFound(error: unknown): boolean {
  return error instanceof HttpError && (error.status === 404 || error.code === "not-found");
}

export function isSignedOut(error: unknown): boolean {
  return error instanceof HttpError && error.status === 401;
}

const MINUTE = 60_000;

const ignore = () => undefined;

/** "live", "recent" (this season's finished), optionally only the viewer's. */
export type MatchFilter = "live" | "recent";

export const queries = {
  matches: (status: MatchFilter, mine: boolean) =>
    infiniteQueryOptions({
      queryKey: ["matches", "list", status, mine],
      queryFn: ({ pageParam }) =>
        getJson<MatchList>(withQuery("/api/matches/", { status, mine: mine ? "1" : null, cursor: pageParam })),
      initialPageParam: null as string | null,
      getNextPageParam: (last) => last.next_cursor,
      retry: retryUnlessMissing,
      // Live matches move on their own (the live topic says when); finished ones barely change.
      staleTime: status === "live" ? 10_000 : MINUTE,
    }),

  match: (id: string) =>
    queryOptions({
      queryKey: ["matches", id],
      queryFn: () => getJson<MatchDetail>(`/api/matches/${id}/`),
      retry: retryUnlessMissing,
      // Awards and corrections can come later, but not by the second.
      staleTime: 30_000,
    }),

  postgame: (id: string) =>
    queryOptions({
      queryKey: ["matches", id, "postgame"],
      queryFn: () => getJson<PostgameBody>(`/api/matches/${id}/postgame/`),
      retry: retryUnlessMissing,
      staleTime: 5 * MINUTE,
      // deadlock-api's data can still arrive: look again every minute while it may.
      refetchInterval: (query) => {
        const body = query.state.data;
        return body?.status === "pending" && body.reason === "later" ? MINUTE : false;
      },
    }),

  seasons: () =>
    queryOptions({
      queryKey: ["seasons"],
      queryFn: () => getJson<SeasonList>("/api/seasons/"),
      staleTime: 10 * MINUTE,
    }),

  /** A season's table (the open one for null), a page at a time. */
  ladder: (season: string | null) =>
    infiniteQueryOptions({
      queryKey: ["ladder", season],
      queryFn: ({ pageParam }) => getJson<Ladder>(withQuery("/api/ladder/", { season, offset: pageParam ? String(pageParam) : null })),
      initialPageParam: 0,
      getNextPageParam: (last) => last.next_offset,
      retry: retryUnlessMissing,
      staleTime: MINUTE,
    }),

  /** Your own profile (the open season for null). Nobody else's exists. */
  me: (season: string | null = null) =>
    queryOptions({
      queryKey: ["me", season],
      queryFn: () => getJson<MyProfile>(withQuery("/api/me/", { season })),
      retry: retryUnlessMissing,
      staleTime: 30_000,
    }),
};

/** GET /api/me/share.png with these parts on the card. No-store on the server, so the URL is the
 * whole cache key. */
export interface ShareParts {
  rating: boolean;
  place: boolean;
  award: boolean;
}

export function shareCardUrl(parts: ShareParts): string {
  const bit = (on: boolean) => (on ? "1" : "0");
  return withQuery("/api/me/share.png", { rating: bit(parts.rating), place: bit(parts.place), award: bit(parts.award) });
}

/** POST /api/me/steam/<id>/unlink/: one of your own Steam links. The session, your profile and
 * the live `me` all say so afterwards. */
export function useUnlinkSteam() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => postJson<SteamUnlinked>(`/api/me/steam/${id}/unlink/`),
    onSuccess: (body) => {
      client.setQueriesData<MyProfile>({ queryKey: ["me"] }, (old) =>
        old ? { ...old, accounts: { ...old.accounts, steam: body.steam } } : old,
      );
      void client.invalidateQueries({ queryKey: SESSION_KEY });
      void client.invalidateQueries({ queryKey: ["me"] });
    },
  });
}

/** POST /api/tools/random-draft/: every ban and pick at random. Nothing is recorded. */
export function useRandomDraft() {
  return useMutation({
    mutationFn: () => postJson<RandomDraft>("/api/tools/random-draft/"),
  });
}

/** Warms the data a page needs before it's opened (hover or focus on its link). Quietly does
 * nothing for paths it doesn't know. */
export function prefetchPath(client: QueryClient, path: string): void {
  const match = /^\/matches\/(\d+)(?:\/(summary|timeline|replay|advanced))?\/?$/.exec(path);
  if (match?.[1]) {
    void client.query(queries.match(match[1])).catch(ignore);
    if (match[2]) void client.query(queries.postgame(match[1])).catch(ignore);
    return;
  }
  if (path === "/matches") void client.infiniteQuery(queries.matches("recent", false)).catch(ignore);
  else if (path === "/ladder") void client.infiniteQuery(queries.ladder(null)).catch(ignore);
  else if (path === "/me" || path === "/" || path === "/link-steam") void client.query(queries.me(null)).catch(ignore);
}
