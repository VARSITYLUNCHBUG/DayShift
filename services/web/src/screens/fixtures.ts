// What Django answers about the finished match (completed.http-*.json, written by
// tests/test_web_fixtures.py) and the live snapshots around it, typed, for the pages' tests and the
// screen gallery. The app itself never imports this file.
import type { LiveSnap, MeSnap, QueueSnap } from "../api/live";
import type { Ladder, MatchDetail, MatchList, MyProfile, PostgameReady, RandomDraft, SeasonList } from "../api/types";
import ladder from "../fixtures/completed.http-ladder.json";
import match from "../fixtures/completed.http-match.json";
import matches from "../fixtures/completed.http-matches.json";
import me from "../fixtures/completed.http-me.json";
import postgame from "../fixtures/completed.http-postgame.json";
import randomDraft from "../fixtures/completed.http-random-draft.json";
import seasons from "../fixtures/completed.http-seasons.json";
import liveInProgress from "../fixtures/in_progress.live.json";
import meQueued from "../fixtures/in_progress.me-spectator.json";
import meReady from "../fixtures/ready_check.me-player.json";
import queueInProgress from "../fixtures/in_progress.queue.json";
import meCooldown from "../fixtures/voided_ready_check.me-spectator.json";

const copy = (data: unknown): unknown => structuredClone(data);

/** The finished match's record ended at 19:30; this is a few minutes later. */
export const PAGES_NOW = "2026-01-05T19:35:00.000Z";

export const http = {
  match: () => copy(match) as MatchDetail,
  postgame: () => copy(postgame) as PostgameReady,
  matches: () => copy(matches) as MatchList,
  ladder: () => copy(ladder) as Ladder,
  me: () => copy(me) as MyProfile,
  seasons: () => copy(seasons) as SeasonList,
  randomDraft: () => copy(randomDraft) as RandomDraft,
};

export const live = {
  /** In the queue, waiting (the onlooker while No. 1 is in game). */
  meQueued: () => copy(meQueued) as MeSnap,
  /** On a match's roster, in its ready check. */
  meReady: () => copy(meReady) as MeSnap,
  /** On a queue cooldown after missing a ready check. */
  meCooldown: () => copy(meCooldown) as MeSnap,
  queue: () => copy(queueInProgress) as QueueSnap,
  live: () => copy(liveInProgress) as LiveSnap,
};

/** The player the HTTP fixtures were written for (`http.me().player`). */
export const HTTP_VIEWER = { id: "3", name: "P3" } as const;

/** The JSON answers, by URL, for `serveHttp`. */
export function httpAnswers(): Record<string, unknown> {
  const id = http.match().id;
  return {
    "/api/matches/?status=recent": http.matches(),
    "/api/matches/?status=recent&mine=1": http.matches(),
    "/api/matches/?status=live": { matches: [], next_cursor: null },
    "/api/matches/?status=live&mine=1": { matches: [], next_cursor: null },
    [`/api/matches/${id}/`]: http.match(),
    [`/api/matches/${id}/postgame/`]: http.postgame(),
    "/api/ladder/": http.ladder(),
    "/api/seasons/": http.seasons(),
    "/api/me/": http.me(),
    "/api/tools/random-draft/": http.randomDraft(),
  };
}
