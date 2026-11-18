/** @vitest-environment jsdom */
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { control, type ScenarioStep } from "../api";
import { ScenariosScreen } from "./ScenariosScreen";

vi.mock("../api", async (importOriginal) => {
  const real = await importOriginal<typeof import("../api")>();
  return { ...real, control: { scenarios: vi.fn(), runSteps: vi.fn() } };
});

const STEPS: ScenarioStep[] = [
  { title: "Fill the queue", method: "POST", path: "queue/fill" },
  { title: "To the coinflip", method: "POST", path: "matches/latest/advance", body: { until: "coinflip" } },
  { title: "Fire", method: "POST", path: "matches/latest/fire" },
];

// What the server did at each step: the advance stops a phase short.
const ANSWERS = [
  { status: 200, response: { match_id: 1 } },
  { status: 200, response: { from: "ready_check", to: "player_draft", match: { status: "player_draft" } } },
  { status: 200, response: { fired: true } },
];

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("ScenariosScreen runbook", () => {
  it("pauses at a breakpoint, resumes, and stops where actual differs from expected", async () => {
    vi.mocked(control.scenarios).mockResolvedValue([{ name: "demo", description: "", steps: STEPS }]);
    vi.mocked(control.runSteps).mockImplementation((_steps, from = 0) => {
      const answer = ANSWERS[from] ?? { status: 500, response: null };
      return Promise.resolve({ ok: answer.status < 400, ran: [{ index: from, seconds: 0.1, ...answer }], next: from + 1, total: 3 });
    });
    const user = userEvent.setup();
    render(<ScenariosScreen onChanged={vi.fn()} />);

    await user.click(await screen.findByRole("button", { name: /demo/ }));
    await user.click(screen.getByRole("button", { name: "Pause before step 2" }));
    await user.click(screen.getByRole("button", { name: /^Run/ }));

    expect((await screen.findByRole("status")).textContent).toBe("Breakpoint: paused before step 2.");
    expect(control.runSteps).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: /^Resume/ }));
    await waitFor(() => {
      expect(screen.getByRole("status").textContent).toBe(
        "Step 2: expected success, match coinflip, got HTTP 200, match player_draft.",
      );
    });
    expect(control.runSteps).toHaveBeenCalledTimes(2);
    expect(screen.getByText("HTTP 200, match player_draft")).toBeTruthy();
    expect(screen.getByText("different")).toBeTruthy();
  });
it("fails a step the server's answer has no result for", async () => {
    vi.mocked(control.scenarios).mockResolvedValue([{ name: "demo", description: "", steps: STEPS }]);
    vi.mocked(control.runSteps).mockResolvedValue({ ok: true, ran: [], next: 1, total: 3 });
    const user = userEvent.setup();
    render(<ScenariosScreen onChanged={vi.fn()} />);

    await user.click(await screen.findByRole("button", { name: /demo/ }));
    await user.click(screen.getByRole("button", { name: /^Run/ }));

    expect((await screen.findByRole("status")).textContent).toBe("Step 1: the server's answer has no result for it.");
    expect(control.runSteps).toHaveBeenCalledTimes(1);
    expect(screen.getByText("error")).toBeTruthy();
  });

  it("honours a breakpoint set while the run is going", async () => {
    vi.mocked(control.scenarios).mockResolvedValue([{ name: "demo", description: "", steps: STEPS }]);
    let release: () => void = () => undefined;
    vi.mocked(control.runSteps).mockImplementation((_steps, from = 0) => {
      const answer = { ok: true, ran: [{ index: from, seconds: 0.1, status: 200, response: { match: { status: "coinflip" } } }], next: from + 1, total: 3 };
      // The first step hangs until the test lets it go, so the run is under way meanwhile.
      return from === 0 ? new Promise((resolve) => { release = () => { resolve(answer); }; }) : Promise.resolve(answer);
    });
    const user = userEvent.setup();
    render(<ScenariosScreen onChanged={vi.fn()} />);

    await user.click(await screen.findByRole("button", { name: /demo/ }));
    await user.click(screen.getByRole("button", { name: /^Run/ }));
    await user.click(screen.getByRole("button", { name: "Pause before step 3" }));
    release();

    expect((await screen.findByRole("status")).textContent).toBe("Breakpoint: paused before step 3.");
    expect(control.runSteps).toHaveBeenCalledTimes(2);
  });
});
