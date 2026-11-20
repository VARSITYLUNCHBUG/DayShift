// A typed client for the dev control API, /_control/api/ (devtools/README.md). The browser plays
// one player; this sets the stage and plays everyone else, through league.services, the same calls
// the Discord buttons make. It sends no Origin header, so devtools' cross-origin guard lets it in.
import { expect, request as playwrightRequest } from "@playwright/test";
import type { APIRequestContext, APIResponse } from "@playwright/test";

export type Team = "A" | "B";
export type Via = "service" | "discord";

export interface ControlPlayer {
  id: number;
  discord_user_id: string;
  name: string;
  rating: number | null;
  games: number;
  queued: boolean;
  queue_position: number | null;
  match_id: number | null;
}

export type MatchStatus =
  | "ready_check"
  | "captain_phase"
  | "captain_checkin"
  | "player_draft"
  | "coinflip"
  | "champion_draft"
  | "lobby_code"
  | "in_progress"
  | "awaiting_confirmation"
  | "disputed"
  | "completed"
  | "voided"
  | (string & {});

export interface MatchPlayer {
  id: number;
  name: string;
  team: Team | "";
  is_captain: boolean;
  ready: boolean;
  checked_in: boolean;
  active: boolean;
}

export interface ControlMatch {
  id: number;
  status: MatchStatus;
  kind: string;
  version: number;
  step_index: number;
  frozen: boolean;
  on_hold: boolean;
  turn: { action: string | null; team: Team | "" | null; player_ids: number[]; step: number | null } | null;
  captains: Partial<Record<Team, number>>;
  teams: Partial<Record<Team, number[]>>;
  players: MatchPlayer[];
  coinflip_winner: Team | "";
  hidden_king_team: Team | "";
  lobby_code: string;
  winner: Team | "";
  swap_open: boolean;
  sub_requests: { id: number; status: string; leaving: number; offers: { id: number; player_id: number; status: string }[] }[];
  swaps: { id: number; status: string; give: number; take: number }[];
}

export interface QueueEntry {
  position: number;
  player: ControlPlayer;
}

export interface ControlState {
  community: { id: number; name: string; settings: Record<string, unknown> } | null;
  season: { id: number; number: number } | null;
  lobby_size: number;
  queue: QueueEntry[];
  matches: ControlMatch[];
  timers: { paused_all: boolean; frozen_matches: number[] };
  lobbies: "create" | "fail";
}

export interface MatchScript {
  draft?: number[];
  champions?: { step: number; team?: Team; slug: string }[];
  captain_votes?: Record<string, number[]>;
  coinflip?: "hidden_king" | "archmother";
  lobby_code?: string;
  winner?: Team;
}

/** A player id, or a selector such as `captain:A`, `acting`, `other_captain` or `non_captain:2`. */
export type PlayerRef = number | string;

export class ControlError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

type MatchRef = number | "latest";

export class Control {
  private constructor(private readonly http: APIRequestContext) {}

  static async open(baseURL: string): Promise<Control> {
    const http = await playwrightRequest.newContext({
      baseURL: `${baseURL.replace(/\/$/, "")}/_control/api/`,
      // An advance through every phase acts for twelve players.
      timeout: 60_000,
    });
    return new Control(http);
  }

  async dispose(): Promise<void> {
    await this.http.dispose();
  }

  private async call<T>(method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE", path: string, body?: unknown): Promise<T> {
    const response: APIResponse = await this.http.fetch(path, {
      method,
      ...(body === undefined ? {} : { data: body }),
    });
    const text = await response.text();
    if (!response.ok()) {
      let code = "http_error";
      let message = text.slice(0, 2000);
      try {
        const parsed = JSON.parse(text) as { error?: { code?: string; message?: string } };
        code = parsed.error?.code ?? code;
        message = parsed.error?.message ?? message;
      } catch {
        // Not JSON: keep the text.
      }
      throw new ControlError(response.status(), code, `${method} ${path}: ${response.status()} ${code}: ${message}`);
    }
    return (text ? JSON.parse(text) : undefined) as T;
  }

  // --- The league --------------------------------------------------------------------------------

  state(): Promise<ControlState> {
    return this.call("GET", "state");
  }

  /** Back to the dev fixtures: every player, match and queue entry made since is gone. */
  async reset(fixture: "dev_default" | "none" = "dev_default"): Promise<void> {
    await this.call("POST", "reset", { fixture });
  }

  async setLobbies(lobby: "create" | "fail"): Promise<void> {
    await this.call("PUT", "lobbies", { lobby });
  }

  async pauseAll(): Promise<void> {
    await this.call("POST", "timers/pause");
  }

  // --- Players -----------------------------------------------------------------------------------

  /** New fake players, rated and (optionally) queued in order. A 12th in the queue pops a lobby. */
  createPlayers(
    count: number,
    options: { rating?: number | { min: number; max: number }; name_prefix?: string; join_queue?: boolean } = {},
  ): Promise<{ players: ControlPlayer[]; match_id: number | null }> {
    return this.call("POST", "players", { count, ...options });
  }

  async createPlayer(name: string, rating = 1200): Promise<ControlPlayer> {
    const { players } = await this.createPlayers(1, { name_prefix: name, rating });
    const [player] = players;
    if (!player) throw new Error("The control API made no player.");
    return player;
  }

  async players(): Promise<ControlPlayer[]> {
    return (await this.call<{ players: ControlPlayer[] }>("GET", "players")).players;
  }

  async player(id: number): Promise<ControlPlayer> {
    const found = (await this.players()).find((player) => player.id === id);
    if (!found) throw new Error(`No player ${id}.`);
    return found;
  }

  setPicks(id: number, picks: { prefer?: string[]; ban?: string[] }): Promise<ControlPlayer> {
    return this.call("PUT", `players/${id}/picks`, picks);
  }

  // --- The queue ---------------------------------------------------------------------------------

  joinQueue(playerIds: number[]): Promise<{ queue: QueueEntry[]; match_id: number | null }> {
    return this.call("POST", "queue/join", { player_ids: playerIds, via: "service" });
  }

  leaveQueue(playerIds: number[]): Promise<{ queue: QueueEntry[] }> {
    return this.call("POST", "queue/leave", { player_ids: playerIds, via: "service" });
  }

  /** New players until the queue holds a lobby: it pops, and the match id comes back. */
  async fillQueue(rating?: number): Promise<number> {
    const result = await this.call<{ match_id: number | null }>("POST", "queue/fill", rating === undefined ? {} : { rating });
    if (result.match_id === null) throw new Error("Filling the queue popped no lobby.");
    return result.match_id;
  }

  async queue(): Promise<QueueEntry[]> {
    return (await this.state()).queue;
  }

  // --- Matches -----------------------------------------------------------------------------------

  match(id: MatchRef = "latest"): Promise<ControlMatch> {
    return this.call("GET", `matches/${id}`);
  }

  script(id: MatchRef, script: MatchScript): Promise<ControlMatch> {
    return this.call("PUT", `matches/${id}/script`, script);
  }

  /** Every remaining player acts until the match reaches `until` (or, without it, the next phase). */
  async advance(id: MatchRef, until?: MatchStatus): Promise<ControlMatch> {
    const body = until === undefined ? { via: "service" } : { until, via: "service" };
    return (await this.call<{ match: ControlMatch }>("POST", `matches/${id}/advance`, body)).match;
  }

  /** One action as one player (or several, in turn). */
  async act(
    id: MatchRef,
    action: string,
    options: { player?: PlayerRef; players?: PlayerRef[]; args?: Record<string, unknown> } = {},
  ): Promise<ControlMatch> {
    const body: Record<string, unknown> = { action, args: options.args ?? {}, via: "service" };
    if (options.player !== undefined) body.player_id = options.player;
    if (options.players !== undefined) body.player_ids = options.players;
    return (await this.call<{ match: ControlMatch }>("POST", `matches/${id}/act`, body)).match;
  }

  async fire(id: MatchRef): Promise<ControlMatch> {
    return (await this.call<{ match: ControlMatch }>("POST", `matches/${id}/fire`)).match;
  }

  pause(id: MatchRef): Promise<ControlMatch> {
    return this.call("POST", `matches/${id}/pause`);
  }

  /** Poll the match until `check` holds (web-first waiting for server state, no fixed sleeps). */
  async waitForMatch(id: MatchRef, check: (match: ControlMatch) => boolean, what: string, timeout = 10_000): Promise<ControlMatch> {
    let last: ControlMatch | undefined;
    await expect
      .poll(
        async () => {
          last = await this.match(id);
          return check(last);
        },
        { message: `match ${String(id)}: ${what}`, timeout },
      )
      .toBe(true);
    if (!last) throw new Error("unreachable");
    return last;
  }
}
