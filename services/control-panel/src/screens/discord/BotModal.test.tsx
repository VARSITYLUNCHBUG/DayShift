/** @vitest-environment jsdom */
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { sim } from "../../api";
import { SimModal } from "../../api/schemas";
import { BotModal } from "./BotModal";

vi.mock("../../api", async (importOriginal) => {
  const real = await importOriginal<typeof import("../../api")>();
  return { ...real, sim: { uploadAttachment: vi.fn(), submitModal: vi.fn() } };
});

// The bot's report modal (bot/handlers/results.py), as the simulator hands it over.
const REPORT = SimModal.parse({
  custom_id: "report-1",
  title: "Report the result",
  components: [
    { type: 18, label: "Winning team", component: { type: 3, custom_id: "w", placeholder: "Who won?", options: [{ label: "Team Ash", value: "A" }, { label: "Team Bo", value: "B" }] } },
    { type: 18, label: "Scoreboard screenshot", component: { type: 19, custom_id: "shot", min_values: 1, max_values: 1, required: true } },
    { type: 18, label: "Deadlock match ID", component: { type: 4, custom_id: "dl", style: 1, required: false, max_length: 18 } },
  ],
});

const submitted = { interactionId: "9", modal: null, replies: ["Report received."] };

function open(onSubmitted = vi.fn(), onClose = vi.fn()) {
  render(<BotModal userId="21" userName="Dev 1" modal={REPORT} onClose={onClose} onSubmitted={onSubmitted} />);
  return { onSubmitted, onClose };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("BotModal", () => {
  it("fills in the bot's form, uploads the screenshot and submits it as the user", async () => {
    vi.mocked(sim.uploadAttachment).mockResolvedValue({ id: "555", filename: "board.png" });
    vi.mocked(sim.submitModal).mockResolvedValue(submitted);
    const user = userEvent.setup();
    const { onSubmitted, onClose } = open();

    expect(screen.getByRole("heading", { name: "Report the result" })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: /Winning team/ }));
    await user.click(await screen.findByRole("option", { name: "Team Bo" }));
    await user.type(screen.getByRole("textbox", { name: "Deadlock match ID" }), "123456");
    const file = new File(["png"], "board.png", { type: "image/png" });
    await user.upload(screen.getByLabelText(/Scoreboard screenshot/), file);
    await user.click(screen.getByRole("button", { name: "Submit as Dev 1" }));

    await waitFor(() => { expect(onSubmitted).toHaveBeenCalledWith(submitted); });
    expect(sim.uploadAttachment).toHaveBeenCalledWith(file, "board.png");
    expect(sim.submitModal).toHaveBeenCalledWith({
      user_id: "21",
      custom_id: "report-1",
      values: { w: ["B"], dl: "123456" },
      attachments: { shot: ["555"] },
    });
    expect(onClose).toHaveBeenCalled();
  });

  it("won't send without a required answer", async () => {
    const user = userEvent.setup();
    open();
    await user.click(screen.getByRole("button", { name: "Submit as Dev 1" }));
    expect(sim.submitModal).not.toHaveBeenCalled();
  });

  it("sends a placeholder for a required upload left empty, and keeps the form open on a refusal", async () => {
    vi.mocked(sim.submitModal).mockRejectedValue(new Error("You already reported this match."));
    const user = userEvent.setup();
    const { onSubmitted, onClose } = open();

    await user.click(screen.getByRole("button", { name: /Winning team/ }));
    await user.click(await screen.findByRole("option", { name: "Team Ash" }));
    await user.click(screen.getByRole("button", { name: "Submit as Dev 1" }));

    expect((await screen.findByRole("alert")).textContent).toContain("already reported");
    expect(sim.uploadAttachment).not.toHaveBeenCalled();
    expect(vi.mocked(sim.submitModal).mock.calls[0]?.[0].attachments).toEqual({ shot: [{ filename: "screenshot.png" }] });
    expect(onSubmitted).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });
});
