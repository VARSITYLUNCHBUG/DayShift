import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router";
import { describe, expect, it } from "vitest";

import { MatchRoute } from "../match/MatchRoute";
import { http, httpAnswers, PAGES_NOW } from "../fixtures";
import { serveHttp } from "../../test/http";
import { renderPage, SIGNED_IN } from "../../test/render";
import type { Session } from "../../api/session";
import { awardLine, fightScore, moments, namesOf, PENDING, storyLine, winningSide } from "./model";
import { itemName } from "./Advanced";
import { PostgamePage } from "./PostgamePage";

const ID = http.match().id;
const PLAYER: Session = { ...SIGNED_IN, player: { id: "3", name: "P3", avatar: null, steam: [] } };
const WATCHER: Session = { ...SIGNED_IN, player: { id: "99", name: "Onlooker", avatar: null, steam: [] } };

function open(tab: string, options: { session?: Session; answers?: Record<string, unknown> } = {}) {
  serveHttp(options.answers ?? httpAnswers());
  return renderPage(<PostgamePage />, {
    route: `/matches/${ID}/${tab}`,
    path: "/matches/:id/:tab",
    session: options.session ?? PLAYER,
    serverTime: PAGES_NOW,
  });
}

describe("the postgame's words", () => {
  const detail = http.match();
  const doc = http.postgame().data;
  const names = namesOf(detail, doc);

  it("names each side by its team", () => {
    const hk = detail.teams.find((team) => team.side === "hk");
    expect(names.side.hk).toBe(hk?.name);
    expect(winningSide(detail, doc)).toBe(doc.winner);
  });

  it("puts a fight's winner first", () => {
    expect(fightScore({ hk: 2, am: 3 }, "am")).toBe("3–2");
    expect(fightScore({ hk: 6, am: 1 }, "hk")).toBe("6–1");
  });

  it("writes every award from its stats", () => {
    const mvp = doc.awards.find((award) => award.kind === "mvp");
    expect(mvp && awardLine(mvp, doc)).toMatch(/^\d+ kills, [\d.]+k souls, [\d.]+k hero damage$/);
    for (const award of doc.awards) expect(awardLine(award, doc)).not.toContain("undefined");
  });

  it("tells the story and every moment in words", () => {
    expect(storyLine(doc, names)).toContain("Patron down at");
    const all = moments(doc, names);
    expect(all).toHaveLength(doc.events.length);
    expect(all[0]?.title).toBe("First blood");
  });
});

describe("summary", () => {
  it("shows the result, your night, six awards and both scoreboards", async () => {
    open("summary");
    const doc = http.postgame().data;
    const names = namesOf(http.match(), doc);
    expect(await screen.findByText(`${names.side[doc.winner ?? "am"]} win`)).toBeInTheDocument();
    expect(screen.getByText("Your night")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Awards" })).toBeInTheDocument();
    expect(within(screen.getByRole("heading", { name: "Awards" }).closest("section") as HTMLElement).getAllByRole("listitem")).toHaveLength(6);
    expect(screen.getAllByRole("table")).toHaveLength(2);
    // The room shell, for one of the twelve.
    expect(screen.getByRole("main")).toHaveAttribute("id", "stage");
    expect(screen.getByRole("link", { name: "Summary" })).toHaveAttribute("aria-current", "page");
  });

  it("opens a scoreboard row in Advanced, and links to nobody's profile", async () => {
    open("summary");
    const row = await screen.findByRole("link", { name: "P3: every number" });
    expect(row.getAttribute("href")).toMatch(new RegExp(`^/matches/${ID}/advanced\\?slot=\\d+$`));
    for (const link of screen.getAllByRole("link")) expect(link.getAttribute("href") ?? "").not.toMatch(/\/players\//);
  });

  it("is the same record without a personal block for someone who wasn't in it", async () => {
    const answers = httpAnswers();
    answers[`/api/matches/${ID}/postgame/`] = { ...http.postgame(), you: null };
    open("summary", { session: WATCHER, answers });
    expect(await screen.findByRole("heading", { name: "Watching, not playing" })).toBeInTheDocument();
    expect(screen.queryByText("Your night")).not.toBeInTheDocument();
    expect(screen.getByRole("main")).toHaveAttribute("id", "main");
  });

  it("explains why the stats aren't in, and keeps the result", async () => {
    const answers = httpAnswers();
    answers[`/api/matches/${ID}/postgame/`] = { status: "pending", reason: "no-match-id" };
    open("summary", { answers });
    expect(await screen.findByText(PENDING["no-match-id"].title)).toBeInTheDocument();
    expect(screen.getAllByRole("table")).toHaveLength(2);
  });

  it("says so for a match that doesn't exist", async () => {
    open("summary", { answers: {} });
    expect(await screen.findByRole("heading", { name: "We can't find that match" })).toBeInTheDocument();
  });
});

describe("the deep tabs", () => {
  it("timeline: picking a moment shows it beside the chart", async () => {
    open("timeline");
    const list = await screen.findByRole("heading", { name: "Every moment" }, { timeout: 5000 });
    const items = within(list.closest("section") as HTMLElement).getAllByRole("button");
    await userEvent.click(items[2] as HTMLElement);
    const aside = screen.getByRole("complementary", { name: "The moment you picked" });
    expect(within(aside).getByRole("heading", { level: 2 }).textContent).toBe(items[2]?.querySelector("b")?.textContent);
    expect(within(aside).getByRole("link", { name: "Watch from here" }).getAttribute("href")).toMatch(/replay\?t=\d+/);
    await userEvent.click(screen.getByText("Kill lead"));
    expect(screen.getByRole("img", { name: /^Kill lead over the match/ })).toBeInTheDocument();
  });

  it("replay: starts paused, and the scrubber moves the clock", async () => {
    open("replay");
    const slider = await screen.findByRole("slider", { name: "Time in the match" }, { timeout: 5000 });
    expect(screen.getByRole("button", { name: "Play" })).toBeInTheDocument();
    fireEvent.change(slider, { target: { value: "600" } });
    expect(screen.getByRole("img", { name: /^The map at 10:00/ })).toBeInTheDocument();
  });

  it("advanced: headers sort, and a player opens up", async () => {
    open("advanced");
    const header = await screen.findByRole("columnheader", { name: /Hero damage/ }, { timeout: 5000 });
    expect(header).toHaveAttribute("aria-sort", "descending");
    await userEvent.click(within(header).getByRole("button"));
    expect(header).toHaveAttribute("aria-sort", "ascending");
    const someone = http.postgame().data.players[0];
    await userEvent.click(screen.getByRole("button", { name: new RegExp(`^${someone?.name ?? ""}.*${someone?.hero ?? ""}.*open their numbers$`) }));
    expect(screen.getByRole("heading", { level: 3, name: someone?.name })).toBeInTheDocument();
    expect(screen.getByText("Where the souls came from")).toBeInTheDocument();
  });
});

describe("the room hands over", () => {
  it("opens the record of a match that isn't live", async () => {
    serveHttp({});
    renderPage(
      <Routes>
        <Route path="/matches/:id" element={<MatchRoute />} />
        <Route path="/matches/:id/:tab" element={<PostgamePage />} />
      </Routes>,
      { route: "/matches/999", session: PLAYER, serverTime: PAGES_NOW },
    );
    await waitFor(() => expect(screen.getByRole("heading", { name: "We can't find that match" })).toBeInTheDocument(), { timeout: 5000 });
  });
});

describe("item names", () => {
  it("names a bought item from the catalogue, and numbers one it doesn't know", () => {
    const doc = http.postgame().data;
    const bought = doc.players.flatMap((line) => line.build.map((buy) => buy.item_id));
    const known = bought.find((id) => doc.item_names[String(id)]);
    expect(known).toBeDefined();
    expect(itemName(doc, known ?? 0)).toBe(doc.item_names[String(known)]);
    expect(itemName(doc, 1)).toBe("Item 1");
  });
});
