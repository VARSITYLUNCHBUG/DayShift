import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ActionRefused } from "../live/actions";
import { renderPage } from "../test/render";
import { Banner } from "./Banner";
import { Dialog } from "./Dialog";
import { InlineAlert } from "./InlineAlert";
import { NoticeSheet } from "./NoticeSheet";
import { errorText, notify, TOAST_MS } from "./toast";
import ToastRegion from "./ToastRegion";

describe("Banner and InlineAlert", () => {
  it("states the app's state politely, and refusals at once", () => {
    render(
      <>
        <Banner kind="warn">Reconnecting. Your place and picks are safe.</Banner>
        <InlineAlert title="That code didn't work">Check the code in the game and try again.</InlineAlert>
      </>,
    );
    expect(screen.getByRole("status")).toHaveTextContent("Reconnecting.");
    expect(screen.getByRole("alert")).toHaveTextContent("That code didn't work");
  });
});

describe("Dialog", () => {
  it("must be answered: focus lands on the main action and Esc does nothing", async () => {
    const onOpenChange = vi.fn();
    renderPage(
      <Dialog
        isOpen
        mustAnswer
        onOpenChange={onOpenChange}
        title="Doors open"
        eyebrow="No. 413"
        actions={
          <button type="button" autoFocus>
            I&apos;m ready
          </button>
        }
      >
        Twelve in.
      </Dialog>,
      { live: false },
    );
    const dialog = await screen.findByRole("dialog", { name: "Doors open" });
    expect(dialog).toHaveTextContent("Twelve in.");
    await waitFor(() => expect(screen.getByRole("button", { name: "I'm ready" })).toHaveFocus());
    await userEvent.keyboard("{Escape}");
    expect(onOpenChange).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("lets a confirm dialog go back with Esc", async () => {
    const onOpenChange = vi.fn();
    renderPage(
      <Dialog isOpen onOpenChange={onOpenChange} title="Dispute No. 413's result?" actions={<button type="button">Go back</button>} />,
      { live: false },
    );
    await screen.findByRole("dialog");
    await userEvent.keyboard("{Escape}");
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});

describe("NoticeSheet", () => {
  it("isn't modal: focus moves to its heading and Tab can leave", async () => {
    const onDismiss = vi.fn();
    renderPage(
      <>
        <button type="button">Elsewhere</button>
        <NoticeSheet isOpen title="A spot's open in No. 413" eyebrow="Spot offered" onDismiss={onDismiss} actions={<button type="button">Take the spot</button>} />
      </>,
      { live: false },
    );
    const sheet = screen.getByRole("dialog", { name: "A spot's open in No. 413" });
    expect(sheet).toHaveAttribute("aria-modal", "false");
    expect(screen.getByRole("heading", { name: "A spot's open in No. 413" })).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    expect(onDismiss).toHaveBeenCalledOnce();
  });

  it("draws nothing while closed", () => {
    const { container } = render(<NoticeSheet isOpen={false} title="x" actions={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("Toasts", () => {
  afterEach(() => {
    act(() => {
      for (const toast of document.querySelectorAll("[data-slot=toast]")) toast.remove();
    });
  });

  it("show bottom-left and say what happened", async () => {
    renderPage(<ToastRegion />, { live: false });
    act(() => {
      notify.info("You're in", "8 of 12 in the queue");
    });
    expect(await screen.findByText("You're in")).toBeInTheDocument();
    expect(screen.getByText("8 of 12 in the queue")).toBeInTheDocument();
    expect(TOAST_MS).toBe(8_000);
  });

  it("show the server's refusal as-is, and never a bare 'Something went wrong'", () => {
    expect(errorText(new ActionRefused("Only captains can report the result."))).toBe("Only captains can report the result.");
    expect(errorText("??")).not.toMatch(/^Something went wrong/);
  });
});
