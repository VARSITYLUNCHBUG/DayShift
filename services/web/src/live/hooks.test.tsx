import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";

import queueFixture from "../fixtures/ready_check.queue.json";
import { FIXTURE_NOW } from "../match/fixtures";
import type { QueueSnap } from "./types";
import { ActionRefused, ConnectionLost } from "./actions";
import { FakeServer } from "./FakeServer";
import { useAction, useCountdown, useTopic } from "./hooks";
import { LiveProvider } from "./LiveProvider";

function setup(server: FakeServer) {
  const socket = server.socket();
  const wrapper = ({ children }: { children: ReactNode }) => <LiveProvider socket={socket}>{children}</LiveProvider>;
  return { socket, wrapper };
}

describe("useTopic", () => {
  it("goes from loading to live, stale while disconnected, and gone", async () => {
    const queue = structuredClone(queueFixture) as QueueSnap;
    const server = new FakeServer();
    const { wrapper } = setup(server);
    const { result } = renderHook(() => useTopic("queue"), { wrapper });
    expect(result.current).toEqual({ data: undefined, state: "loading" });

    act(() => server.current.open());
    act(() => server.snap("queue", queue));
    expect(result.current).toEqual({ data: queue, state: "live" });

    act(() => server.current.drop(1006));
    expect(result.current.state).toBe("stale");
    expect(result.current.data).toEqual(queue);

    const match = renderHook(() => useTopic("match:404"), { wrapper });
    await waitFor(() => expect(server.sockets).toHaveLength(2));
    act(() => server.current.open());
    act(() => server.gone("match:404"));
    expect(match.result.current.state).toBe("gone");
  });

  it("watches nothing for a null topic", () => {
    const { wrapper } = setup(new FakeServer());
    const { result } = renderHook(() => useTopic(null), { wrapper });
    expect(result.current.state).toBe("idle");
  });
});

describe("useAction", () => {
  it("is pending until the ack, and keeps the refusal text", async () => {
    const server = new FakeServer();
    const { wrapper } = setup(server);
    const { result } = renderHook(() => useAction(), { wrapper });
    act(() => server.current.open());

    let done!: Promise<unknown>;
    act(() => {
      done = result.current.run("queue.join", {}).catch((e: unknown) => e);
    });
    expect(result.current.pending).toBe(true);
    expect(server.lastAct()).toMatchObject({ name: "queue.join", args: {} });

    await act(async () => {
      server.ack(server.lastAct()!.id, { ok: false, error: "You're on a queue cooldown." });
      await done;
    });
    expect(await done).toBeInstanceOf(ActionRefused);
    expect(result.current.pending).toBe(false);
    expect(result.current.error).toBe("You're on a queue cooldown.");
  });

  it("fails with ConnectionLost when not connected", async () => {
    const { wrapper } = setup(new FakeServer());
    const { result } = renderHook(() => useAction(), { wrapper });
    let failure: unknown;
    await act(async () => {
      failure = await result.current.run("lobby.ready", { match_id: "1" }).catch((e: unknown) => e);
    });
    expect(failure).toBeInstanceOf(ConnectionLost);
  });
});

describe("useCountdown", () => {
  it("counts down by the server's clock and waits past zero", async () => {
    const server = new FakeServer({ auto: true, serverTime: FIXTURE_NOW });
    const { wrapper } = setup(server);
    const { result } = renderHook(
      ({ deadline }: { deadline: string | null }) => useCountdown(deadline),
      { wrapper, initialProps: { deadline: "2026-01-05T19:03:00.000Z" } },
    );
    await waitFor(() => expect(result.current?.label).toMatch(/^2:4[01]$/));
    expect(result.current?.waiting).toBe(false);
  });

  it("is waiting once the deadline has passed", async () => {
    const server = new FakeServer({ auto: true, serverTime: FIXTURE_NOW });
    const { wrapper } = setup(server);
    const { result } = renderHook(() => useCountdown("2026-01-05T19:00:00.000Z"), { wrapper });
    await waitFor(() => expect(result.current).toMatchObject({ waiting: true, label: "0:00" }));
  });

  it("is null without a deadline", () => {
    const { wrapper } = setup(new FakeServer());
    const { result } = renderHook(() => useCountdown(null), { wrapper });
    expect(result.current).toBeNull();
  });
});
