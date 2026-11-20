import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ThemeSwitch } from "../components/shell/TopBar";
import { fixture } from "../legacy/dev/fixtures";
import { renderPage } from "../test/render";
import { ThemeProvider } from "../theme/ThemeContext";
import { AppRoutes } from "./routes";

// Each route loads its page lazily on first use; give it time under a full parallel run.
const LAZY = { timeout: 10_000 };

describe("Routes", () => {
  it("draws a missing page inside the app shell, with the way back", async () => {
    const me = fixture.me("completed", "player");
    renderPage(<AppRoutes />, { route: "/nowhere", snaps: { me }, playerId: me.player.id });
    expect(await screen.findByText("There's nothing here", {}, LAZY)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to Play" })).toHaveAttribute("href", "/");
    expect(within(screen.getByRole("navigation", { name: "Main" })).getByRole("link", { name: "Play" })).toBeInTheDocument();
  });

  it("keeps profiles private: there's no page for someone else's", async () => {
    const me = fixture.me("completed", "player");
    renderPage(<AppRoutes />, { route: "/players/7", snaps: { me }, playerId: me.player.id });
    expect(await screen.findByText("There's nothing here", {}, LAZY)).toBeInTheDocument();
  });

  it("gives the postgame tabs their own pages in the room shell", async () => {
    const me = fixture.me("completed", "player");
    renderPage(<AppRoutes />, { route: "/matches/413/timeline", snaps: { me }, playerId: me.player.id });
    expect(await screen.findByText("The timeline isn't in yet", {}, LAZY)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Timeline" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("main")).toHaveAttribute("id", "stage");
  });

  it("sends a signed-out player to sign in", async () => {
    renderPage(<AppRoutes />, {
      route: "/ladder",
      live: false,
      session: { signed_in: false, player: null, dev_login: false, invite_url: null },
    });
    expect(await screen.findByRole("link", { name: /Sign in with Discord/ }, LAZY)).toBeInTheDocument();
  });
});

describe("Theme", () => {
  it("is dark by default and switches to light on the html element", async () => {
    renderPage(
      <ThemeProvider>
        <ThemeSwitch />
      </ThemeProvider>,
      { live: false },
    );
    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
    await userEvent.click(screen.getByRole("button", { name: "Switch to the light theme" }));
    expect(document.documentElement).toHaveAttribute("data-theme", "light");
    expect(localStorage.getItem("heroui-theme")).toBe("light");
    await userEvent.click(screen.getByRole("button", { name: "Switch to the dark theme" }));
    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
  });
});
