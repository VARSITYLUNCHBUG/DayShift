import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import me from "../fixtures/ready_check.me-player.json";
import match from "../fixtures/ready_check.player.json";
import queue from "../fixtures/ready_check.queue.json";
import { ActionRefused, ConnectionLost } from "./actions";
import { FakeServer } from "./FakeServer";
import { BACKOFF_BASE_MS, PING_EVERY_MS, SILENCE_LIMIT_MS } from "./LiveSocket";
import type { MatchSnap, MeSnap, QueueSnap } from "./types";

const meSnap = me as MeSnap;
const matchSnap = match as MatchSnap;
const queueSnap = queue as QueueSnap;

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-01-05T19:00:00.000Z"));
});

afterEach(() => {
  vi.useRealTimers();
});

function connected(options: ConstructorParameters<typeof FakeServer>[0] = {}) {
  const server = new FakeServer(options);
  const signedOut = vi.fn();
  const log = { warn: vi.fn(), error: vi.fn() };
  const live = server.socket({ onSignedOut: signedOut, log });
  live.start();
  server.current.open();
  return { server, live, signedOut, log };
}

describe("LiveSocket", () => {
  it("subscribes, applies snapshots and tells listeners", () => {
    const { server, live } = connected();
    const seen = vi.fn();
    live.subscribe("me", seen);
    expect(server.received).toContainEqual({ t: "sub", topics: ["me"] });

    server.snap("me", meSnap);
    expect(seen).toHaveBeenCalledTimes(1);
    expect(live.getTopic("me").data).toEqual(meSnap);
  });

  it("subscribes topics asked for before the socket opened, in one message", () => {
    const server = new FakeServer();
    const live = server.socket();
    live.subscribe("me", () => {});
    live.subscribe("queue", () => {});
    live.start();
    server.current.open();
    expect(server.current.sent).toEqual([{ t: "sub", topics: ["me", "queue"] }]);
  });

  it("ignores a snapshot older than the one it has", () => {
    const { server, live } = connected();
    live.subscribe("match:1", () => {});
    server.snap("match:1", { ...matchSnap, mode_name: "new" }, 57);
    server.snap("match:1", { ...matchSnap, mode_name: "old" }, 56);
    expect((live.getTopic("match:1").data as MatchSnap).mode_name).toBe("new");
    server.snap("match:1", { ...matchSnap, mode_name: "newer" }, 58);
    expect((live.getTopic("match:1").data as MatchSnap).mode_name).toBe("newer");
  });

  it("marks a topic gone", () => {
    const { server, live } = connected();
    live.subscribe("match:9", () => {});
    server.gone("match:9");
    expect(live.getTopic("match:9").gone).toBe(true);
  });

  it("unsubscribes a topic once nobody has watched it for a moment", () => {
    const { server, live } = connected();
    const stop = live.subscribe("queue", () => {});
    stop();
    expect(server.received).not.toContainEqual({ t: "unsub", topics: ["queue"] });
    vi.advanceTimersByTime(2_000);
    expect(server.received).toContainEqual({ t: "unsub", topics: ["queue"] });
  });

  it("reconnects with backoff and resubscribes everything", () => {
    const { server, live } = connected();
    live.subscribe("me", () => {});
    live.subscribe("queue", () => {});
    server.snap("queue", queueSnap, 40);

    server.current.drop(1006);
    expect(live.getState()).toBe("reconnecting");
    expect(server.sockets).toHaveLength(1);
    // random() is 0.5 in FakeServer sockets: half the ceiling plus a quarter.
    vi.advanceTimersByTime(BACKOFF_BASE_MS * 0.75);
    expect(server.sockets).toHaveLength(2);

    server.current.open();
    expect(live.getState()).toBe("open");
    expect(server.current.sent).toEqual([{ t: "sub", topics: ["me", "queue"] }]);
    // The old data stays until the fresh snapshot arrives, and revs restart per connection.
    expect(live.getTopic("queue").data).toEqual(queueSnap);
    server.snap("queue", { ...queueSnap, count: 2 }, 1);
    expect((live.getTopic("queue").data as QueueSnap).count).toBe(2);
  });

  it("backs off further after each failed attempt", () => {
    const { server } = connected();
    server.current.drop(1006);
    vi.advanceTimersByTime(375);
    expect(server.sockets).toHaveLength(2);
    server.current.drop(1006);
    vi.advanceTimersByTime(700);
    expect(server.sockets).toHaveLength(2);
    vi.advanceTimersByTime(100);
    expect(server.sockets).toHaveLength(3);
  });

  it("goes to sign-in on 4401 and doesn't reconnect", () => {
    const { server, live, signedOut } = connected();
    server.current.drop(4401);
    expect(signedOut).toHaveBeenCalledTimes(1);
    expect(live.getState()).toBe("closed");
    vi.advanceTimersByTime(60_000);
    expect(server.sockets).toHaveLength(1);
  });

  it("reconnects after the server's ping timeout (4408)", () => {
    const { server, signedOut } = connected();
    server.current.drop(4408);
    vi.advanceTimersByTime(1_000);
    expect(server.sockets).toHaveLength(2);
    expect(signedOut).not.toHaveBeenCalled();
  });

  it("logs topic and action limits (4409, 4429)", () => {
    const { server, log } = connected();
    server.current.drop(4429);
    expect(log.warn).toHaveBeenCalledWith(expect.stringContaining("4429"));
  });

  it("pings every 20 seconds and corrects its clock from the answer", () => {
    const { server, live } = connected();
    server.hello(server.current, "2026-01-05T19:00:05.000Z");
    expect(live.getOffsetMs()).toBe(5_000);
    expect(live.getPlayerId()).toBe("1");

    vi.advanceTimersByTime(PING_EVERY_MS);
    expect(server.received.filter((m) => m.t === "ping")).toHaveLength(1);
    vi.advanceTimersByTime(200);
    server.current.deliver({ t: "pong", server_time: "2026-01-05T19:00:28.100Z" });
    // Sent at 19:00:20.000, answered at 20.200: the server read its clock at about 20.100.
    expect(live.getOffsetMs()).toBe(8_000);
  });

  it("drops a connection that has gone silent", () => {
    const { server } = connected();
    vi.advanceTimersByTime(SILENCE_LIMIT_MS + PING_EVERY_MS);
    expect(server.sockets[0]?.isClosed).toBe(true);
  });

  it("settles an action with its ack", async () => {
    const { server, live } = connected();
    const done = live.act("lobby.ready", { match_id: "1" });
    const sent = server.lastAct();
    expect(sent).toMatchObject({ t: "act", name: "lobby.ready", args: { match_id: "1" } });
    server.ack(sent!.id);
    await expect(done).resolves.toMatchObject({ ok: true });
  });

  it("rejects a refused action with the server's text", async () => {
    const { server, live } = connected();
    const done = live.act("queue.join", {});
    server.ack(server.lastAct()!.id, { ok: false, error: "You're on a cooldown." });
    await expect(done).rejects.toEqual(new ActionRefused("You're on a cooldown."));
  });

  it("rejects actions in flight when the connection drops, and never re-sends them", async () => {
    const { server, live } = connected();
    const done = live.act("queue.leave", {});
    server.current.drop(1006);
    await expect(done).rejects.toBeInstanceOf(ConnectionLost);

    vi.advanceTimersByTime(1_000);
    server.current.open();
    expect(server.current.sent.some((m) => m.t === "act")).toBe(false);
  });

  it("refuses to act while not connected", async () => {
    const server = new FakeServer();
    const live = server.socket();
    live.start();
    await expect(live.act("queue.join", {})).rejects.toBeInstanceOf(ConnectionLost);
  });

  it("closes for good on stop", () => {
    const { server, live } = connected();
    live.stop();
    expect(server.current.isClosed).toBe(true);
    expect(live.getState()).toBe("closed");
    vi.advanceTimersByTime(60_000);
    expect(server.sockets).toHaveLength(1);
  });
});
