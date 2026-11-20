// The tab's one websocket to /ws/. Everything live goes through here: subscriptions, snapshots,
// actions and the server clock. React reaches it through LiveProvider and the hooks in hooks.ts.
import { ActionRefused, ConnectionLost } from "./actions";
import type { ActionArgs, ActionName } from "./actions";
import type { ClientMessage } from "./protocol.gen";
import { MAX_TOPICS } from "./types";
import type { AckMessage, AnySnap, Topic } from "./types";

export type ConnectionState = "connecting" | "open" | "reconnecting" | "closed";

/** What LiveSocket needs from a WebSocket; FakeServer implements it for tests. */
export interface SocketLike {
  send(data: string): void;
  close(code?: number, reason?: string): void;
  onopen: ((event: Event) => void) | null;
  onmessage: ((event: MessageEvent) => void) | null;
  onclose: ((event: CloseEvent) => void) | null;
  onerror: ((event: Event) => void) | null;
}

export interface TopicSnapshot {
  readonly data: AnySnap | undefined;
  readonly gone: boolean;
}

export interface LiveSocketOptions {
  url: string;
  createSocket?: (url: string) => SocketLike;
  /** Called on close code 4401 / 4403: the session is gone, so sign in again. */
  onSignedOut?: () => void;
  random?: () => number;
  log?: Pick<Console, "warn" | "error">;
}

export const PING_EVERY_MS = 20_000;
/** Two pings without any answer: the connection is dead even if the browser hasn't noticed. */
export const SILENCE_LIMIT_MS = 45_000;
export const ACK_TIMEOUT_MS = 30_000;
export const BACKOFF_BASE_MS = 500;
export const BACKOFF_CAP_MS = 30_000;
/** A topic nobody watches is kept this long, so moving between pages doesn't resubscribe. */
export const UNSUB_DELAY_MS = 2_000;

const SIGNED_OUT_CODES = new Set([4401, 4403]);
const LOGGED_CODES = new Set([4409, 4429]);
const EMPTY: TopicSnapshot = Object.freeze({ data: undefined, gone: false });

interface TopicEntry {
  snapshot: TopicSnapshot;
  listeners: Set<() => void>;
  unsubTimer: ReturnType<typeof setTimeout> | null;
}

interface Pending {
  resolve: (ack: AckMessage) => void;
  reject: (error: Error) => void;
  timer: ReturnType<typeof setTimeout>;
}

export class LiveSocket {
  private readonly url: string;
  private readonly createSocket: (url: string) => SocketLike;
  private onSignedOut: () => void;
  private readonly random: () => number;
  private readonly log: Pick<Console, "warn" | "error">;

  private ws: SocketLike | null = null;
  private started = false;
  private everOpened = false;
  private attempts = 0;
  private state: ConnectionState = "closed";
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private pingTimer: ReturnType<typeof setInterval> | null = null;
  private pingSentAt: number | null = null;
  private lastHeard = 0;
  private offsetMs = 0;
  private playerId: string | null = null;
  private seq = 0;

  private readonly topics = new Map<Topic, TopicEntry>();
  /** The last rev applied per topic, for this connection only: per-process revs restart. */
  private revs = new Map<string, number>();
  private readonly pending = new Map<string, Pending>();
  private readonly stateListeners = new Set<() => void>();

  constructor(options: LiveSocketOptions) {
    this.url = options.url;
    this.createSocket = options.createSocket ?? ((url) => new WebSocket(url));
    this.onSignedOut = options.onSignedOut ?? (() => {});
    this.random = options.random ?? Math.random;
    this.log = options.log ?? console;
  }

  // --- Lifecycle ------------------------------------------------------------------------------

  setSignedOutHandler(handler: () => void): void {
    this.onSignedOut = handler;
  }

  start(): void {
    if (this.started) return;
    this.started = true;
    window.addEventListener("online", this.reconnectNow);
    this.connect();
  }

  stop(): void {
    this.started = false;
    window.removeEventListener("online", this.reconnectNow);
    this.clearReconnect();
    const ws = this.ws;
    this.detach();
    ws?.close(1000, "bye");
    this.setState("closed");
  }

  private connect(): void {
    this.clearReconnect();
    this.setState(this.everOpened ? "reconnecting" : "connecting");
    const ws = this.createSocket(this.url);
    this.ws = ws;
    ws.onopen = () => {
      if (ws === this.ws) this.opened();
    };
    ws.onmessage = (event) => {
      if (ws === this.ws) this.received(event.data);
    };
    ws.onclose = (event) => {
      if (ws === this.ws) this.closed(event.code);
    };
    ws.onerror = () => {
      // A close event always follows; that's where reconnecting happens.
    };
  }

  private opened(): void {
    this.everOpened = true;
    this.attempts = 0;
    this.revs = new Map();
    this.lastHeard = Date.now();
    this.setState("open");
    const topics = this.wanted();
    if (topics.length > 0) this.send({ t: "sub", topics });
    this.pingTimer = setInterval(this.ping, PING_EVERY_MS);
  }

  private closed(code: number): void {
    this.detach();
    if (SIGNED_OUT_CODES.has(code)) {
      this.started = false;
      this.setState("closed");
      this.onSignedOut();
      return;
    }
    if (LOGGED_CODES.has(code)) {
      this.log.warn(`Live connection closed by the server (${code}).`);
    }
    if (this.started) this.scheduleReconnect();
    else this.setState("closed");
  }

  /** Forget the current socket: stop pinging and fail every action still waiting for its ack. */
  private detach(): void {
    const ws = this.ws;
    this.ws = null;
    if (ws) {
      ws.onopen = ws.onmessage = ws.onclose = ws.onerror = null;
    }
    if (this.pingTimer !== null) clearInterval(this.pingTimer);
    this.pingTimer = null;
    this.pingSentAt = null;
    for (const [id, waiting] of this.pending) {
      clearTimeout(waiting.timer);
      waiting.reject(new ConnectionLost());
      this.pending.delete(id);
    }
  }

  private scheduleReconnect(): void {
    this.setState("reconnecting");
    const ceiling = Math.min(BACKOFF_CAP_MS, BACKOFF_BASE_MS * 2 ** this.attempts);
    const delay = ceiling / 2 + (this.random() * ceiling) / 2;
    this.attempts += 1;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      if (this.started) this.connect();
    }, delay);
  }

  /** The browser came back online: don't wait out the backoff. */
  private readonly reconnectNow = (): void => {
    if (this.started && this.reconnectTimer !== null) this.connect();
  };

  private clearReconnect(): void {
    if (this.reconnectTimer !== null) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
  }

  private readonly ping = (): void => {
    if (Date.now() - this.lastHeard > SILENCE_LIMIT_MS) {
      const ws = this.ws;
      this.closed(4000);
      ws?.close(4000, "silent");
      return;
    }
    this.pingSentAt = Date.now();
    this.send({ t: "ping" });
  };

  // --- Messages -------------------------------------------------------------------------------

  private send(message: ClientMessage): void {
    this.ws?.send(JSON.stringify(message));
  }

  private received(raw: unknown): void {
    this.lastHeard = Date.now();
    let message: unknown;
    try {
      message = JSON.parse(String(raw));
    } catch {
      this.log.error("Live message wasn't JSON.");
      return;
    }
    if (typeof message !== "object" || message === null || !("t" in message)) return;
    const m = message as { t: string } & Record<string, unknown>;
    switch (m.t) {
      case "hello":
        this.playerId = String(m.player_id);
        this.setOffset(String(m.server_time), Date.now());
        this.notifyState();
        break;
      case "pong":
        if (this.pingSentAt !== null) {
          // The server read its clock about halfway through the round trip.
          const midpoint = (this.pingSentAt + Date.now()) / 2;
          this.setOffset(String(m.server_time), midpoint);
          this.pingSentAt = null;
        }
        break;
      case "snap":
        this.applySnap(m.topic as Topic, Number(m.rev), m.data as AnySnap);
        break;
      case "gone":
        this.setTopic(m.topic as Topic, { data: undefined, gone: true });
        break;
      case "ack":
        this.applyAck(m as unknown as AckMessage);
        break;
      default:
        break;
    }
  }

  private setOffset(serverTime: string, localMs: number): void {
    const server = Date.parse(serverTime);
    if (!Number.isNaN(server)) this.offsetMs = server - localMs;
  }

  private applySnap(topic: Topic, rev: number, data: AnySnap): void {
    if (!this.topics.has(topic)) return;
    const last = this.revs.get(topic);
    // Snapshots are whole states, so an older one arriving late is simply dropped.
    if (last !== undefined && rev < last) return;
    this.revs.set(topic, rev);
    this.setTopic(topic, { data, gone: false });
  }

  private applyAck(ack: AckMessage): void {
    const waiting = this.pending.get(ack.id);
    if (!waiting) return;
    clearTimeout(waiting.timer);
    this.pending.delete(ack.id);
    if (ack.ok) waiting.resolve(ack);
    else waiting.reject(new ActionRefused(ack.error ?? "That didn't work. Try again."));
  }

  // --- Topics ---------------------------------------------------------------------------------

  private wanted(): Topic[] {
    const topics = [...this.topics.keys()];
    if (topics.length > MAX_TOPICS) {
      this.log.error(`Watching ${topics.length} topics; the server allows ${MAX_TOPICS}.`);
      return topics.slice(0, MAX_TOPICS);
    }
    return topics;
  }

  subscribe(topic: Topic, listener: () => void): () => void {
    let entry = this.topics.get(topic);
    if (!entry) {
      entry = { snapshot: EMPTY, listeners: new Set(), unsubTimer: null };
      this.topics.set(topic, entry);
      if (this.state === "open") {
        if (this.topics.size > MAX_TOPICS) {
          this.log.error(`Not watching ${topic}: the server allows ${MAX_TOPICS} topics.`);
        } else {
          this.send({ t: "sub", topics: [topic] });
        }
      }
    }
    if (entry.unsubTimer !== null) {
      clearTimeout(entry.unsubTimer);
      entry.unsubTimer = null;
    }
    const kept = entry;
    kept.listeners.add(listener);
    return () => {
      kept.listeners.delete(listener);
      if (kept.listeners.size > 0 || kept.unsubTimer !== null) return;
      kept.unsubTimer = setTimeout(() => {
        kept.unsubTimer = null;
        if (kept.listeners.size > 0 || this.topics.get(topic) !== kept) return;
        this.topics.delete(topic);
        this.revs.delete(topic);
        if (this.state === "open") this.send({ t: "unsub", topics: [topic] });
      }, UNSUB_DELAY_MS);
    };
  }

  getTopic(topic: Topic): TopicSnapshot {
    return this.topics.get(topic)?.snapshot ?? EMPTY;
  }

  private setTopic(topic: Topic, snapshot: TopicSnapshot): void {
    const entry = this.topics.get(topic);
    if (!entry) return;
    entry.snapshot = snapshot;
    for (const listener of [...entry.listeners]) listener();
  }

  // --- Actions --------------------------------------------------------------------------------

  /** Settles with the ack: resolves when ok, rejects with ActionRefused or ConnectionLost. An
   * action is sent once; if the socket drops first it is never re-sent. */
  act<N extends ActionName>(name: N, args: ActionArgs[N]): Promise<AckMessage> {
    if (this.state !== "open" || this.ws === null) {
      return Promise.reject(new ConnectionLost("Not connected. Try again in a moment."));
    }
    this.seq += 1;
    const id = `c-${this.seq}`;
    return new Promise<AckMessage>((resolve, reject) => {
      const timer = setTimeout(() => {
        if (this.pending.delete(id)) {
          reject(new ConnectionLost("No answer from the server. Check the page and try again."));
        }
      }, ACK_TIMEOUT_MS);
      this.pending.set(id, { resolve, reject, timer });
      this.send({ t: "act", id, name, args: { ...args } });
    });
  }

  // --- State and clock ------------------------------------------------------------------------

  getState = (): ConnectionState => this.state;

  subscribeState = (listener: () => void): (() => void) => {
    this.stateListeners.add(listener);
    return () => {
      this.stateListeners.delete(listener);
    };
  };

  private setState(state: ConnectionState): void {
    if (this.state === state) return;
    this.state = state;
    this.notifyState();
  }

  private notifyState(): void {
    for (const listener of [...this.stateListeners]) listener();
  }

  /** The signed-in player's id, from `hello`. */
  getPlayerId = (): string | null => this.playerId;

  /** Server time now, in ms since the epoch: local time corrected by the offset from hello/pong. */
  serverNow(): number {
    return Date.now() + this.offsetMs;
  }

  getOffsetMs(): number {
    return this.offsetMs;
  }
}

export function liveUrl(location: Pick<Location, "protocol" | "host"> = window.location): string {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${location.host}/ws/`;
}
