/** @vitest-environment jsdom */
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { control } from "../../api";
import { Match } from "../../api/schemas";
import type { Run } from "../../hooks/useAction";
import { ActModal } from "./ActModal";

vi.mock("../../api", async (importOriginal) => {
  const real = await importOriginal<typeof import("../../api")>();
  return { ...real, control: { act: vi.fn() } };
});

const run: Run = async (_label, call) => call();

// Team A won the coinflip and is choosing a side; swaps are open.
const COINFLIP_RAW = {
  id: 4,
  status: "coinflip",
  turn: { action: "coinflip", team: "A", player_ids: [1] },
  players: [
    { id: 1, name: "Ash", team: "A", is_captain: true },
    { id: 2, name: "Cy", team: "A" },
    { id: 7, name: "Bo", team: "B", is_captain: true },
    { id: 8, name: "Dee", team: "B" },
  ],
};
const COINFLIP = Match.parse(COINFLIP_RAW);

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("ActModal", () => {
  it("offers only what the phase allows, the awaited action first", () => {
    render(<ActModal match={COINFLIP} run={run} via="service" onClose={vi.fn()} />);
    const radios = screen.getAllByRole("radio").map((r) => r.closest("label")?.textContent ?? "");
    expect(radios.map((t) => t.replace(/waiting for this/, "").trim())).toEqual([
      "Choose a side (coinflip)coinflip",
      "Offer a player swapswap",
      "Ask to sub outrequest_sub",
      "Void the match (staff)void",
    ]);
    expect(screen.getAllByRole<HTMLInputElement>("radio")[0]?.checked).toBe(true);
    expect(screen.getByRole<HTMLTextAreaElement>("textbox", { name: "Args (JSON)" }).value).toContain('"choice": "hidden_king"');
  });

  it("fills in the swap and sends it as the captain", async () => {
    vi.mocked(control.act).mockResolvedValue({ match: {}, actions: [] });
    const user = userEvent.setup();
    render(<ActModal match={COINFLIP} run={run} via="discord" onClose={vi.fn()} />);

    await user.click(screen.getByRole("radio", { name: /Offer a player swap/ }));
    const args = screen.getByRole<HTMLTextAreaElement>("textbox", { name: "Args (JSON)" });
    expect(JSON.parse(args.value)).toEqual({ give: 2, take: 8 });
    await user.click(screen.getByRole("button", { name: "Send action" }));

    await waitFor(() => {
      expect(control.act).toHaveBeenCalledWith(4, { action: "swap", args: { give: 2, take: 8 }, via: "discord", player_id: 1 });
    });
  });

it("won't send an action the match no longer allows once it moves on", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<ActModal match={COINFLIP} run={run} via="service" onClose={vi.fn()} />);
    expect(screen.getAllByRole<HTMLInputElement>("radio")[0]?.checked).toBe(true); // coinflip

    // The poll brings the champion draft: there is no coinflip to choose any more.
    const drafting = Match.parse({ ...COINFLIP_RAW, status: "champion_draft", turn: { action: "ban", team: "A", player_ids: [1] } });
    rerender(<ActModal match={drafting} run={run} via="service" onClose={vi.fn()} />);
    expect(screen.getByRole("alert").textContent).toContain("is now champion_draft");
    const send = screen.getByRole("button", { name: "Send action" });
    expect(send.getAttribute("disabled") !== null || send.getAttribute("data-disabled") === "true").toBe(true);
    await user.click(send);
    expect(control.act).not.toHaveBeenCalled();

    // Picking again clears it.
    await user.click(screen.getByRole("radio", { name: /Ban/ }));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("can lift the filter to send any action", async () => {
    const user = userEvent.setup();
    render(<ActModal match={COINFLIP} run={run} via="service" onClose={vi.fn()} />);
    await user.click(screen.getByRole("switch", { name: "Every action and player" }));
    expect(screen.getAllByRole("radio").length).toBeGreaterThan(20);
  });
});
