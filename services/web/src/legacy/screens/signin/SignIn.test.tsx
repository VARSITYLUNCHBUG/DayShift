import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderPage, SIGNED_IN } from "../../../test/render";
import { REFUSALS } from "./refusals";
import { DISCORD_APP, safeNext, SignInPage, SignInView } from "./SignIn";

// The codes league/web/auth/errors.py sends (its CODES set).
const DJANGO_CODES = [
  "not-member",
  "discord-denied",
  "discord-failed",
  "state",
  "steam-denied",
  "steam-invalid",
  "steam-failed",
  "steam-unproven",
  "steam-taken",
  "signed-out",
];

describe("Sign in", () => {
  it("starts Discord and Steam sign-in on Django, coming back to where the player was", () => {
    renderPage(<SignInView error={null} next="/matches/4" devLogin={false} />, { live: false });
    expect(screen.getByRole("link", { name: "Sign in with Discord" })).toHaveAttribute(
      "href",
      "/auth/discord/?next=%2Fmatches%2F4",
    );
    expect(screen.getByRole("link", { name: "Sign in with Steam" })).toHaveAttribute(
      "href",
      "/auth/steam/?next=%2Fmatches%2F4&intent=login",
    );
    expect(screen.queryByRole("link", { name: "Dev login" })).not.toBeInTheDocument();
  });

  it("offers the dev login when the server allows it", () => {
    renderPage(<SignInView error={null} next="/" devLogin />, { live: false });
    expect(screen.getByRole("link", { name: "Dev login" })).toHaveAttribute("href", "/auth/dev/?next=%2F");
  });

  it("has copy for every refusal code Django sends", () => {
    expect(Object.keys(REFUSALS).sort()).toEqual([...DJANGO_CODES].sort());
  });

  it("asks a non-member to join the server first", () => {
    renderPage(<SignInView error="not-member" next="/" devLogin={false} />, { live: false });
    expect(screen.getByText("Join the Discord server first")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open Discord" })).toHaveAttribute("href", DISCORD_APP);
    expect(screen.getByRole("link", { name: "Try again" })).toHaveAttribute("href", "/signin");
  });

  it("sends a non-member to the server's invite when there is one", () => {
    renderPage(<SignInView error="not-member" next="/" devLogin={false} inviteUrl="https://discord.gg/inhouse" />, {
      live: false,
    });
    expect(screen.getByRole("link", { name: "Open Discord" })).toHaveAttribute("href", "https://discord.gg/inhouse");
  });

  it("sends an unlinked Steam account to Discord", () => {
    renderPage(<SignInView error="steam-unproven" next="/" devLogin={false} />, { live: false });
    expect(screen.getByText("This Steam account isn't linked")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sign in with Discord" })).toBeInTheDocument();
  });

  it("still says something for a code it doesn't know", () => {
    renderPage(<SignInView error="something-new" next="/" devLogin={false} />, { live: false });
    expect(screen.getByText("Sign-in didn't work")).toBeInTheDocument();
  });

  it("sends a signed-in player on, unless there's a refusal to show", async () => {
    renderPage(<SignInPage />, { live: false, route: "/signin?next=/leaderboard", path: "/signin", session: SIGNED_IN });
    expect(screen.queryByText("Sign in with Discord")).not.toBeInTheDocument();

    renderPage(<SignInPage />, { live: false, route: "/signin?error=steam-taken", path: "/signin", session: SIGNED_IN });
    expect(await screen.findByText("Another player has this Steam account")).toBeInTheDocument();
  });

  it("only goes on to paths on this site", () => {
    expect(safeNext("/matches/2")).toBe("/matches/2");
    expect(safeNext("//evil.test")).toBe("/");
    expect(safeNext("https://evil.test")).toBe("/");
    expect(safeNext(null)).toBe("/");
  });
});
