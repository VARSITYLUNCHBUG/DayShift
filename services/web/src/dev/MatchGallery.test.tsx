import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderPage } from "../test/render";
import MatchGallery from "./MatchGallery";

describe("Match room gallery", () => {
  it("lists every scene", () => {
    renderPage(<MatchGallery />, { route: "/dev/screens/match", path: "/dev/screens/match/*", live: false });
    expect(screen.getAllByRole("link", { name: "captain" }).length).toBeGreaterThan(5);
    expect(screen.getAllByRole("rowheader").length).toBeGreaterThan(20);
  });

  it("renders a scene on its own fake server", async () => {
    renderPage(<MatchGallery />, {
      route: "/dev/screens/match/champion_draft/captain",
      path: "/dev/screens/match/*",
      live: false,
    });
    expect(await screen.findByRole("listbox", { name: "Heroes: choose one" })).toBeInTheDocument();
  });
});
