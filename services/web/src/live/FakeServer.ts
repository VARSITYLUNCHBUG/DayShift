// A scripted stand-in for /ws/, for tests and the dev screen gallery. It hands LiveSocket fake
// sockets and either answers by itself (`auto`) or waits for the test to drive it.
import type { LiveSocketOptions, SocketLike } from "./LiveSocket";
import { LiveSocket } from "./LiveSocket";
import type { ClientMessage, ServerMessage } from "./protocol.legacy";
import type { AnySnap, Topic } from "./types";

export interface AckScript {
  ok: boolean;
  error?: string | null;
  result?: unknown;
}

export interface FakeServerOptions {
  /** Open sockets, say hello, answer subs from `snaps`, pings and acts, all by itself. */
  auto?: boolean;
  playerId?: string;
  /** What the server's clock says at hello; defaults to the real time. */
  serverTime?: string;
  snaps?: Partial<Record<Topic, AnySnap>>;
  answer?: (name: string, args: Record<string, unknown>) => AckScript;
}

export class FakeSocket implements SocketLike {
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  readonly sent: ClientMessage[] = [];
  isOpen = false;
  isClosed = false;

  constructor(
    private readonly server: FakeServer,
    readonly url: string,
  ) {}

  send(data: string): void {
    if (this.isClosed) throw new Error("send on a closed socket");
    const message = JSON.parse(data) as ClientMessage;
    this.sent.push(message);
    this.server.handle(this, message);
  }

  close(code = 1000): void {
    if (this.isClosed) return;
    this.isClosed = true;
    this.isOpen = false;
    this.onclose?.({ code } as CloseEvent);
  }

  // --- Driven by the server -------------------------------------------------------------------

  open(): void {
    this.isOpen = true;
    this.onopen?.(new Event("open"));
  }

  deliver(message: ServerMessage | Record<string, unknown>): void {
    if (this.isClosed) return;
    this.onmessage?.({ data: JSON.stringify(message) } as MessageEvent);
  }

  /** The server hangs up with this code. */
  drop(code: number): void {
    this.close(code);
  }
}

export class FakeServer {
  readonly sockets: FakeSocket[] = [];
  private readonly options: FakeServerOptions;
  private readonly revs = new Map<string, number>();
  /** How far the fake server's clock is from the real one. */
  private readonly clockOffsetMs: number;
  snaps: Partial<Record<Topic, AnySnap>>;

  constructor(options: FakeServerOptions = {}) {
    this.options = options;
    this.snaps = { ...(options.snaps ?? {}) };
    this.clockOffsetMs = options.serverTime ? Date.parse(options.serverTime) - Date.now() : 0;
  }

  /** The fake server's clock, as an ISO string. */
  now(): string {
    return new Date(Date.now() + this.clockOffsetMs).toISOString();
  }

  /** A LiveSocket wired to this server. */
  socket(options: Partial<LiveSocketOptions> = {}): LiveSocket {
    return new LiveSocket({
      url: "ws://fake/ws/",
      random: () => 0.5,
      ...options,
      createSocket: (url) => this.connect(url),
    });
  }

  connect(url: string): FakeSocket {
    const socket = new FakeSocket(this, url);
    this.sockets.push(socket);
    if (this.options.auto) {
      queueMicrotask(() => {
        socket.open();
        this.hello(socket);
      });
    }
    return socket;
  }

  get current(): FakeSocket {
    const socket = this.sockets.at(-1);
    if (!socket) throw new Error("No socket has connected yet.");
    return socket;
  }

  /** Every message the client has sent, on every socket. */
  get received(): ClientMessage[] {
    return this.sockets.flatMap((socket) => socket.sent);
  }

  lastAct(): Extract<ClientMessage, { t: "act" }> | undefined {
    return this.received.filter((m) => m.t === "act").at(-1);
  }

  // --- Scripting ------------------------------------------------------------------------------

  hello(socket: FakeSocket = this.current, serverTime?: string): void {
    socket.deliver({
      t: "hello",
      server_time: serverTime ?? this.now(),
      player_id: this.options.playerId ?? "1",
    });
  }

  /** Send a snapshot to the current socket. The rev goes up by one each time unless given. */
  snap(topic: Topic, data: AnySnap, rev?: number): void {
    const next = rev ?? (this.revs.get(topic) ?? 0) + 1;
    this.revs.set(topic, next);
    this.snaps[topic] = data;
    this.current.deliver({ t: "snap", topic, rev: next, data });
  }

  gone(topic: Topic): void {
    this.current.deliver({ t: "gone", topic, reason: "not_found" });
  }

  ack(id: string, script: AckScript = { ok: true }): void {
    this.current.deliver({ t: "ack", id, ok: script.ok, error: script.error ?? null, ...extra(script) });
  }

  handle(socket: FakeSocket, message: ClientMessage): void {
    if (!this.options.auto) return;
    queueMicrotask(() => {
      switch (message.t) {
        case "sub":
          for (const topic of message.topics as Topic[]) {
            const data = this.snaps[topic];
            if (data === undefined) socket.deliver({ t: "gone", topic, reason: "not_found" });
            else {
              const rev = (this.revs.get(topic) ?? 0) + 1;
              this.revs.set(topic, rev);
              socket.deliver({ t: "snap", topic, rev, data });
            }
          }
          break;
        case "ping":
          socket.deliver({ t: "pong", server_time: this.now() });
          break;
        case "act": {
          const script = this.options.answer?.(message.name, message.args ?? {}) ?? { ok: true };
          socket.deliver({
            t: "ack",
            id: message.id,
            ok: script.ok,
            error: script.error ?? null,
            ...extra(script),
          });
          break;
        }
        default:
          break;
      }
    });
  }
}

function extra(script: AckScript): Record<string, unknown> {
  return script.result === undefined ? {} : { result: script.result };
}
