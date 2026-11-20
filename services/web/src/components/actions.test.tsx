import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { renderPage } from "../test/render";
import { Button, buttonClass, ButtonLink, IconButton } from "./Button";

describe("Button", () => {
  it("is a pill on HeroUI's variants, cream on ink by default", async () => {
    const onPress = vi.fn();
    renderPage(<Button onPress={onPress}>Queue up</Button>, { live: false });
    const button = screen.getByRole("button", { name: "Queue up" });
    expect(button).toHaveClass("button", "button--primary", "button--md");
    await userEvent.click(button);
    expect(onPress).toHaveBeenCalledOnce();
  });

  it("maps the wireframe's kinds onto HeroUI's variants", () => {
    expect(buttonClass({ kind: "ghost" })).toContain("button--outline");
    expect(buttonClass({ kind: "quiet" })).toContain("button--ghost");
    expect(buttonClass({ kind: "danger" })).toContain("button--danger-soft");
    expect(buttonClass({ kind: "danger-solid" })).toContain("button--danger");
    expect(buttonClass({ kind: "secondary", size: "lg" })).toContain("button--lg");
  });

  it("takes the acting team's fill for a turn, and only as the primary action", () => {
    expect(buttonClass({ team: "hk" })).toContain("button--team-hk");
    expect(buttonClass({ team: "am" })).toContain("button--team-am");
    expect(buttonClass({ kind: "ghost", team: "hk" })).not.toContain("button--team-hk");
  });

  it("says what it's doing while pending, and can't be pressed twice", async () => {
    const onPress = vi.fn();
    renderPage(
      <Button isPending pendingLabel="Locking in Ivy…" onPress={onPress}>
        Lock in Ivy
      </Button>,
      { live: false },
    );
    const button = screen.getByRole("button", { name: /Locking in Ivy/ });
    expect(button).toHaveAttribute("data-pending", "true");
    await userEvent.click(button);
    expect(onPress).not.toHaveBeenCalled();
  });
});

describe("IconButton", () => {
  it("carries its name for screen readers", () => {
    renderPage(<IconButton icon="copy" label="Copy the lobby code" />, { live: false });
    expect(screen.getByRole("button", { name: "Copy the lobby code" })).toHaveClass("button--icon-only");
  });
});

describe("ButtonLink", () => {
  it("routes inside the app, and loads Django's pages in full", () => {
    renderPage(
      <>
        <ButtonLink to="/matches">Matches</ButtonLink>
        <ButtonLink to="/auth/discord/" external kind="ghost">
          Sign in with Discord
        </ButtonLink>
      </>,
      { live: false },
    );
    expect(screen.getByRole("link", { name: "Matches" })).toHaveAttribute("href", "/matches");
    expect(screen.getByRole("link", { name: "Sign in with Discord" })).toHaveClass("button--outline");
  });
});
