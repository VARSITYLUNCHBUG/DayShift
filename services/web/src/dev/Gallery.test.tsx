import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderPage } from "../test/render";
import Gallery from "./Gallery";

describe("Component gallery", () => {
  it("shows every component in dark and light side by side", async () => {
    renderPage(<Gallery />, { route: "/dev/screens", path: "/dev/screens/*", live: false });
    expect(await screen.findByRole("heading", { level: 1, name: "Dark" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "Light" }).parentElement).toHaveAttribute("data-theme", "light");
    expect(screen.getAllByRole("heading", { name: "Buttons" })).toHaveLength(2);
    expect(screen.getAllByRole("listbox", { name: "Heroes" })).toHaveLength(2);
  });

  it("previews the room shell", async () => {
    renderPage(<Gallery />, { route: "/dev/screens/room", path: "/dev/screens/*", live: false });
    expect(await screen.findByRole("list", { name: "Match phases" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Lock in Ivy" }).length).toBeGreaterThan(0);
  });
});
