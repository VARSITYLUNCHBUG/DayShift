/** Typed calls to the Django dev control API under `/_control/api/` (devtools/README.md). */
import { z } from "zod";

import { JsonClient, type FetchLike } from "./http";
import { AnyJson, ControlState, PlayerList, ScenarioList, ScenarioRun, type PlayerPicks, type ScenarioStep } from "./schemas";

export type RatingInput = number | { min: number; max: number };

export interface CreatePlayersInput {
  count: number;
  rating?: RatingInput;
  name_prefix?: string;
  join_queue?: boolean;
  dm_open?: boolean;
}

export interface UpdatePlayerInput {
  rating?: number;
  name?: string;
  dm_open?: boolean;
}

/** `PUT matches/{id}/script`: every key optional; the script replaces the previous one. */
export interface MatchScript {
  draft?: number[];
  champions?: { step: number; slug: string; team?: "A" | "B" }[];
  captain_votes?: Record<string, number[]>;
  coinflip?: string;
  lobby_code?: string;
  winner?: "A" | "B";
}

/** The ranked coinflip winner picks a side; the Hidden King bans and picks first. */
export const COINFLIP_CHOICES = ["hidden_king", "archmother"] as const;

export type Via = "discord" | "service";

/** Whether deadlock-api makes lobbies ("create") or refuses them, so the host enters a code. */
export type LobbyMode = "create" | "fail";

export interface AdvanceInput {
  until?: string;
  via?: Via;
}

/** The `action` values `matches/{id}/act` takes, in the order a match needs them. */
export const ACTIONS = [
  "ready",
  "vote",
  "checkin",
  "pick",
  "ban",
  "coinflip",
  "teams_ready",
  "swap",
  "accept_swap",
  "decline_swap",
  "api_lobby",
  "lobby_code",
  "start_match",
  "report",
  "confirm",
  "dispute",
  "resolve",
  "void",
  "request_sub",
  "approve_sub",
  "cancel_sub",
  "invite_sub",
  "offer_queue",
  "accept_sub",
  "decline_sub",
] as const;
export type Action = (typeof ACTIONS)[number];

/** A player id, or a selector such as `captain:A`, `acting`, `host`, `participant:3`. */
export type PlayerRef = number | string;

export interface ActInput {
  player_id?: PlayerRef;
  action: Action;
  args?: Record<string, unknown>;
  via?: Via;
}

/** What `advance` did: the statuses it went between. The match itself comes with the next poll. */
const AdvanceResult = z
  .looseObject({ from: z.string().nullish(), to: z.string().nullish(), actions: z.array(z.unknown()).nullish() })
  .transform((r) => ({ from: r.from ?? null, to: r.to ?? null, actions: r.actions?.length ?? 0 }));
export type AdvanceResult = z.output<typeof AdvanceResult>;

export function createControlApi(base = "/_control/api", fetcher?: FetchLike) {
  const http = new JsonClient(base, fetcher);
  const post = (path: string, body: unknown = {}) => http.call(AnyJson, path, { method: "POST", body });
  return {
    state: (signal?: AbortSignal) => http.call(ControlState, "state", signal ? { signal } : {}),
    reset: (fixture?: string) => post("reset", fixture ? { fixture } : {}),

    players: (signal?: AbortSignal) => http.call(PlayerList, "players", signal ? { signal } : {}),
    createPlayers: (input: CreatePlayersInput) => post("players", input),
    updatePlayer: (id: number, input: UpdatePlayerInput) =>
      http.call(AnyJson, `players/${id}`, { method: "PATCH", body: input }),
    deletePlayer: (id: number) => http.call(AnyJson, `players/${id}`, { method: "DELETE" }),
    setPicks: (id: number, picks: PlayerPicks) =>
      http.call(AnyJson, `players/${id}/picks`, { method: "PUT", body: picks }),

    joinQueue: (input: { player_ids: number[] } | { count: number }) => post("queue/join", input),
    leaveQueue: (playerIds: number[]) => post("queue/leave", { player_ids: playerIds }),
    fillQueue: (rating?: RatingInput) => post("queue/fill", rating === undefined ? {} : { rating }),

    setScript: (matchId: number, script: MatchScript) =>
      http.call(AnyJson, `matches/${matchId}/script`, { method: "PUT", body: script }),
    advance: (matchId: number, input: AdvanceInput = {}) =>
      http.call(AdvanceResult, `matches/${matchId}/advance`, { method: "POST", body: input }),
    fire: (matchId: number) => post(`matches/${matchId}/fire`),
    pause: (matchId: number) => post(`matches/${matchId}/pause`),
    resume: (matchId: number) => post(`matches/${matchId}/resume`),
    act: (matchId: number, input: ActInput) => post(`matches/${matchId}/act`, input),
    setLobbies: (mode: LobbyMode) => http.call(AnyJson, "lobbies", { method: "PUT", body: { lobby: mode } }),
    pauseTimers: () => post("timers/pause"),
    resumeTimers: () => post("timers/resume"),

    scenarios: () => http.call(ScenarioList, "scenarios"),
    /** Run steps on the server; `from`/`count` pick a slice (the step-through mode runs one). */
    runSteps: (steps: ScenarioStep[], from?: number, count?: number) =>
      http.call(ScenarioRun, "scenarios/run", {
        method: "POST",
        body: { steps, ...(from === undefined ? {} : { from }), ...(count === undefined ? {} : { count }) },
      }),
  };
}
