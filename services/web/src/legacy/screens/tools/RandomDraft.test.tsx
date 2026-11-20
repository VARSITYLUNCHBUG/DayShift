// 5.5 Random draft: POST with the CSRF token, then each side's bans and picks.
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { notify } from "../../components/toast";
import { fixture, http } from "../../dev/fixtures";
import { renderPage } from "../../../test/render";
import { json, serveHttp } from "../../../test/http";
import { draftText, RandomDraftPage } from "./RandomDraftPage";

const URL = "/api/tools/random-draft/";

beforeEach(() => {
  document.cookie = "csrftoken=token-123";
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function open() {
  const me = fixture.me("completed", "player");
  return renderPage(<RandomDraftPage />, { snaps: { me }, playerId: me.player.id, route: "/tools/random-draft" });
}

describe("Random draft", () => {
  it("rolls on press and shows each side's bans and picks", async () => {
    const draft = http.randomDraft();
    const fetch = serveHttp({ [URL]: draft });
    open();
    expect(screen.getByText("No draft yet")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Roll" }));
    const bans = await screen.findByRole("region", { name: "The Hidden King bans" });
    for (const hero of draft.hk.bans) expect(within(bans).getByText(hero.name)).toBeInTheDocument();
    const picks = screen.getByRole("region", { name: "The Archmother picks" });
    expect(within(picks).getAllByRole("listitem")).toHaveLength(draft.am.picks.length);
    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe(URL);
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>)["X-CSRFToken"]).toBe("token-123");

    await userEvent.click(screen.getByRole("button", { name: "Again" }));
    await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
  });

  it("says when the roll fails", async () => {
    const error = vi.spyOn(notify, "error").mockImplementation(() => "");
    serveHttp({ [URL]: () => json({ error: "signed-out" }, 401) });
    open();
    await userEvent.click(screen.getByRole("button", { name: "Roll" }));
    await vi.waitFor(() => expect(error).toHaveBeenCalled());
    expect((error.mock.calls[0]![0] as Error).message).toBe("You're signed out. Sign in again to carry on.");
  });

  it("copies as plain text", () => {
    const text = draftText(http.randomDraft());
    expect(text.split("\n")).toHaveLength(2);
    expect(text).toMatch(/^The Hidden King: bans Drifter, Mo & Krill, Rem; picks /);
  });
});
