// M6 screens, from the fixtures: who sees what, and that each action sends the right name and
// arguments.
import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { notify } from "../../components/toast";
import {
  apiLobbyMatch,
  autoCaptainMe,
  fixture,
  ineligibleVoteMatch,
  waitingDraft,
} from "../../dev/fixtures";
import type { AckScript } from "../../../live/FakeServer";
import type { MatchSnap, MeSnap } from "../../../live/types";
import { playerPickSteps, stepIndex } from "../../match/draft";
import { renderPage } from "../../../test/render";
import { MatchRoute } from "./MatchRoute";
import { resetMatchToasts } from "./useMatchToasts";

function open(match: MatchSnap, me: MeSnap, answer?: (name: string, args: Record<string, unknown>) => AckScript) {
  return renderPage(<MatchRoute />, {
    snaps: { me, [`match:${match.id}`]: match },
    playerId: me.player.id,
    route: `/matches/${match.id}`,
    path: "/matches/:id",
    answer,
  });
}

const view = (scenario: string, who: "captain" | "player" | "spectator") =>
  [fixture.match(scenario, who), fixture.me(scenario, who)] as const;

async function sent(server: ReturnType<typeof open>["server"], name: string, args: Record<string, unknown>) {
  await vi.waitFor(() => expect(server.lastAct()).toMatchObject({ name, args }));
}

beforeEach(() => {
  vi.spyOn(notify, "error").mockImplementation(() => "");
  vi.spyOn(notify, "success").mockImplementation(() => "");
});

afterEach(() => {
  vi.restoreAllMocks();
  resetMatchToasts();
});

describe("Captain vote", () => {
  it("lets a player choose up to two and vote", async () => {
    const { server } = open(...view("captain_phase", "player"));
    expect(await screen.findByRole("heading", { name: "Vote for captains" })).toBeInTheDocument();
    expect(screen.getByText("Up to 2 · 4 / 12 voted")).toBeInTheDocument();
    // P1 has voted already, for P5 and P8: their vote shows, and can be changed.
    expect(screen.getByRole("status")).toHaveTextContent("Your vote is in.");
    const p5 = screen.getByRole("button", { name: "Vote for P5" });
    const p8 = screen.getByRole("button", { name: "Vote for P8" });
    expect(p5).toHaveAttribute("aria-pressed", "true");
    expect(p8).toHaveAttribute("aria-pressed", "true");
    const vote = screen.getByRole("button", { name: "Update vote" });
    expect(vote).toBeDisabled();

    await userEvent.click(p5);
    expect(vote).toBeEnabled();
    await userEvent.click(screen.getByRole("button", { name: "Vote for P1 (you) (has voted)" }));
    // A third choice replaces the oldest.
    await userEvent.click(screen.getByRole("button", { name: "Vote for P7" }));
    expect(p8).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(vote);
    await sent(server, "lobby.vote", { match_id: "1", candidate_ids: ["1", "7"] });
  });

  it("takes the vote limit from the snapshot", async () => {
    open({ ...fixture.match("captain_phase", "player"), votes_per_player: 3 }, fixture.me("captain_phase", "player"));
    expect(await screen.findByText("Up to 3 · 4 / 12 voted")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Vote for P7" }));
    for (const name of ["P5", "P7", "P8"]) {
      expect(screen.getByRole("button", { name: `Vote for ${name}` })).toHaveAttribute("aria-pressed", "true");
    }
  });

  it("starts a player who hasn't voted with nothing chosen", async () => {
    const match = fixture.match("captain_phase", "player");
    open({ ...match, viewer: { ...match.viewer, has_voted: false, votes: [] } }, fixture.me("captain_phase", "player"));
    expect(await screen.findByRole("button", { name: "Vote" })).toBeDisabled();
    const list = screen.getByRole("list", { name: "Candidates" });
    for (const button of within(list).getAllByRole("button")) {
      expect(button).toHaveAttribute("aria-pressed", "false");
    }
  });

  it("shows who has voted", async () => {
    open(...view("captain_phase", "player"));
    const list = await screen.findByRole("list", { name: "Candidates" });
    expect(within(list).getAllByText("Voted")).toHaveLength(4);
  });

  it("locks players who can't captain yet", async () => {
    open(ineligibleVoteMatch(), fixture.me("captain_phase", "player"));
    expect(await screen.findByText("Up to 2 · 4 / 12 voted · Captains need 5 matches")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "P5, can't captain: 3/5 matches" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "P6, can't captain: 3 strikes" })).toBeDisabled();
  });

  it("lets spectators watch without voting", async () => {
    open(...view("captain_phase", "spectator"));
    expect(await screen.findByRole("heading", { name: "Captain vote" })).toBeInTheDocument();
    expect(screen.getByText("Watching")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /vote/i })).not.toBeInTheDocument();
  });

  it("only waits when Auto Captain is on", async () => {
    open(fixture.match("captain_phase", "player"), autoCaptainMe());
    expect(await screen.findByText("Picking captains")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Candidates" })).not.toBeInTheDocument();
  });
});

describe("Player draft", () => {
  it("lets the captain on turn pick from the pool", async () => {
    const { server } = open(...view("player_draft", "captain"));
    expect(await screen.findByRole("heading", { name: "Your pick" })).toBeInTheDocument();
    expect(screen.getByText("Pick 2 of 10")).toBeInTheDocument();
    // P3 went to P2's Team already: not in the pickable pool.
    expect(screen.queryByRole("button", { name: "Pick P3" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Pick P4" }));
    await sent(server, "draft.pick_player", { match_id: "1", step_index: 1, player_id: "4" });
  });

  it("shows the teams filling up", async () => {
    open(...view("player_draft", "captain"));
    const panel = (await screen.findByRole("heading", { name: "P2's Team" })).closest("[aria-labelledby]") as HTMLElement;
    const players = within(panel).getByRole("list", { name: "Players" });
    expect(within(players).getAllByRole("listitem", { name: "Open seat" })).toHaveLength(4);
  });

  it("shows players and spectators who is picking, with nothing to press", async () => {
    open(...view("player_draft", "player"));
    expect(await screen.findByRole("heading", { name: "P1 is picking" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Pick / })).not.toBeInTheDocument();
  });

  it("shows the whole pick order, by captain", () => {
    const steps = playerPickSteps(fixture.match("player_draft", "captain"));
    expect(steps.map((s) => s.label)).toEqual(["P2", "P1", "P1", "P2", "P2", "P1", "P1", "P2", "P2", "P1"]);
    expect(steps.map((s) => s.state)).toEqual(["done", "current", ...Array<string>(8).fill("upcoming")]);
    expect(steps[0]?.title).toBe("P2's Team took P3, pick 1");
    expect(steps[9]?.title).toBe("P1's Team pick, pick 10");
  });

  it("has no pick order before the captains are set", () => {
    expect(playerPickSteps(fixture.match("captain_phase", "player"))).toEqual([]);
  });
});

describe("Coinflip", () => {
  it("lets the winner choose a side and order", async () => {
    const { server } = open(...view("coinflip", "captain"));
    expect(await screen.findByRole("heading", { name: "You won the flip" })).toBeInTheDocument();
    expect(screen.getByText("Pick 1 bans and picks first.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /The Archmother\s*Pick 2/ }));
    await sent(server, "draft.coinflip", { match_id: "1", choice: "am_pick2" });
  });

  it("shows everyone else who is choosing", async () => {
    open(...view("coinflip", "player"));
    expect(await screen.findByRole("heading", { name: "P1 is choosing" })).toBeInTheDocument();
    for (const card of within(screen.getByRole("list", { name: "Choices" })).getAllByRole("button")) {
      expect(card).toBeDisabled();
    }
  });

  it("asks the scrim's other captain for a side after the winner took an order", async () => {
    const { server } = open(...view("scrim_coinflip", "captain"));
    expect(await screen.findByRole("heading", { name: "Choose your side" })).toBeInTheDocument();
    expect(screen.getByText("Last pick")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /The Hidden King/ }));
    await sent(server, "draft.coinflip", { match_id: "1", choice: "hidden_king" });
  });

  it("lets a scrim captain start the draft once both have chosen", async () => {
    const { server } = open(fixture.match("scrim_ready_to_draft", "captain"), fixture.me("scrim_ready_to_draft", "captain"));
    expect(await screen.findByRole("heading", { name: "Ready to draft" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /The Archmother/ })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(screen.getByRole("button", { name: "Start draft" }));
    await sent(server, "scrims.start", { match_id: "1" });
  });

  it("has no Start draft for scrim spectators", async () => {
    open(fixture.match("scrim_ready_to_draft", "spectator"), fixture.me("scrim_ready_to_draft", "spectator"));
    expect(await screen.findByText("Waiting for a captain to start the draft.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Start draft" })).not.toBeInTheDocument();
  });
});

describe("Hero draft", () => {
  it("knows the step the service expects", () => {
    expect(stepIndex(fixture.match("champion_draft", "captain"))).toBe(13);
    expect(stepIndex(fixture.match("player_draft", "captain"))).toBe(1);
    // A scrim's steps follow on from the player picks it never makes.
    expect(stepIndex(fixture.match("scrim_champion_draft", "captain"))).toBe(12);
    expect(stepIndex(fixture.match("coinflip", "captain"))).toBeNull();
  });

  it("lets the captain on turn choose, then lock in", async () => {
    const match = fixture.match("champion_draft", "captain");
    const { server } = open(match, fixture.me("champion_draft", "captain"));
    expect(await screen.findByRole("heading", { name: "Your ban" })).toBeInTheDocument();
    expect(screen.getByText("Ban 4 of 6 · Next: P2")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ban" })).toBeDisabled();
    // Taken heroes can't be chosen.
    expect(screen.getByRole("button", { name: "Infernus, banned" })).toBeDisabled();

    const free = match.champions.find((c) => !c.taken)!;
    await userEvent.click(screen.getByRole("button", { name: `Pick ${free.name}` }));
    await userEvent.click(screen.getByRole("button", { name: `Ban ${free.name}` }));
    await sent(server, "draft.champion", { match_id: "1", step_index: 13, champion_id: free.id });
  });

  it("has a Random button", async () => {
    const { server } = open(...view("champion_draft", "captain"));
    await userEvent.click(await screen.findByRole("button", { name: "Random" }));
    await sent(server, "draft.random_champion", { match_id: "1", step_index: 13 });
  });

  it("shows the other captain whose turn it is", async () => {
    const { match, me } = waitingDraft();
    open(match, me);
    expect(await screen.findByRole("heading", { name: "P1 is banning" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Random" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Pick / })).not.toBeInTheDocument();
    expect(screen.queryByText("Watching")).not.toBeInTheDocument();
  });

  it("lets players and spectators watch", async () => {
    open(...view("champion_draft", "spectator"));
    expect(await screen.findByRole("heading", { name: "P1 is banning" })).toBeInTheDocument();
    expect(screen.getByText("Watching")).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Draft order" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Pick / })).not.toBeInTheDocument();
  });

  it("lets a scrim captain ban and pick from the web", async () => {
    const match = fixture.match("scrim_champion_draft", "captain");
    const { server } = open(match, fixture.me("scrim_champion_draft", "captain"));
    expect(await screen.findByRole("heading", { name: "Your ban" })).toBeInTheDocument();
    const free = match.champions.find((c) => !c.taken)!;
    await userEvent.click(screen.getByRole("button", { name: `Pick ${free.name}` }));
    await userEvent.click(screen.getByRole("button", { name: `Ban ${free.name}` }));
    await sent(server, "draft.champion", { match_id: "1", step_index: 12, champion_id: free.id });
    await userEvent.click(screen.getByRole("button", { name: "Random" }));
    await sent(server, "draft.random_champion", { match_id: "1", step_index: 12 });
  });
});

describe("Lobby code", () => {
  it("lets the host post the code, trimmed and in capitals", async () => {
    const { server } = open(...view("lobby_code", "captain"));
    expect(await screen.findByRole("heading", { name: "You host" })).toBeInTheDocument();
    expect(screen.getByText("Duplicate heroes off")).toBeInTheDocument();
    const field = screen.getByRole("textbox", { name: "Lobby code" });
    await userEvent.type(field, "  7kq2-m9 ");
    expect(field).toHaveValue("  7KQ2-M9 ");
    await userEvent.click(screen.getByRole("button", { name: "Post code" }));
    await sent(server, "draft.lobby_code", { match_id: "1", code: "7KQ2-M9" });
  });

  it("shows the service's refusal under the field", async () => {
    const refusal = "That doesn't look like a lobby code: use letters, numbers or dashes.";
    open(...view("lobby_code", "captain"), () => ({ ok: false, error: refusal }));
    await userEvent.type(await screen.findByRole("textbox", { name: "Lobby code" }), "!!{Enter}");
    expect(await screen.findByText(refusal)).toBeInTheDocument();
    expect(notify.error).not.toHaveBeenCalled();
  });

  it("tells players who hosts", async () => {
    open(...view("lobby_code", "player"));
    expect(await screen.findByRole("heading", { name: "P2 hosts" })).toBeInTheDocument();
    expect(screen.getByText("P2 is creating the lobby.")).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("tells spectators the code is for players", async () => {
    open(...view("lobby_code", "spectator"));
    expect(await screen.findByText(/^Players only/)).toBeInTheDocument();
  });
});

describe("Lobby (bot-hosted)", () => {
  it("shows the code and lets a captain start the match", async () => {
    const { server } = open(apiLobbyMatch("captain"), fixture.me("in_progress", "captain"));
    expect(await screen.findByText("ABC123")).toBeInTheDocument();
    expect(screen.getByText("Lobby closes")).toBeInTheDocument();
    const phases = screen.getByRole("list", { name: "Match phases" });
    expect(within(phases).getByText("Lobby").closest("li")).toHaveAttribute("aria-current", "step");
    await userEvent.click(screen.getByRole("button", { name: "Start match" }));
    await sent(server, "draft.api_start", { match_id: "1" });
  });

  it("shows a refusal under the button", async () => {
    const refusal = "The match couldn't be started. Try again in a moment.";
    open(apiLobbyMatch("captain"), fixture.me("in_progress", "captain"), () => ({ ok: false, error: refusal }));
    await userEvent.click(await screen.findByRole("button", { name: "Start match" }));
    expect(await screen.findByText(refusal)).toBeInTheDocument();
  });

  it("has no Start match for players who aren't captains", async () => {
    open(apiLobbyMatch("player"), fixture.me("in_progress", "player"));
    expect(await screen.findByText("ABC123")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Start match" })).not.toBeInTheDocument();
  });

  it("never shows spectators a code", async () => {
    open(apiLobbyMatch("spectator"), fixture.me("in_progress", "spectator"));
    expect(await screen.findByText("Players only")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Copy lobby code" })).not.toBeInTheDocument();
  });
});

describe("In game", () => {
  it("shows the time in game, the code and both teams", async () => {
    open(...view("in_progress", "player"));
    expect(await screen.findByText("In game")).toBeInTheDocument();
    expect(screen.getByRole("timer")).toHaveTextContent(/^0:(19|20)$/);
    expect(screen.getByText(/ · ABC123$/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "P2's Team" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "P1's Team" })).toBeInTheDocument();
    expect(screen.getAllByRole("list", { name: "Heroes" })).toHaveLength(2);
  });

  it("leaves the code out for spectators", async () => {
    open(...view("in_progress", "spectator"));
    expect(await screen.findByText("In game")).toBeInTheDocument();
    expect(screen.queryByText(/ABC123/)).not.toBeInTheDocument();
  });
});

describe("Scrims", () => {
  it("lets anyone claim the open side", async () => {
    const { server } = open(fixture.match("scrim_captain_claim", "spectator"), fixture.me("scrim_captain_claim", "spectator"));
    expect(await screen.findByRole("heading", { name: "Claim a side" })).toBeInTheDocument();
    expect(screen.getByText("Claimed")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Become captain" }));
    await sent(server, "scrims.claim", { match_id: "1", side: "am" });
  });

  it("doesn't let a captain claim the other side too", async () => {
    open(fixture.match("scrim_captain_claim", "captain"), fixture.me("scrim_captain_claim", "captain"));
    expect(await screen.findByText("P1 (you)")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Become captain" })).not.toBeInTheDocument();
  });

  it("shows the finished draft", async () => {
    open(fixture.match("scrim_drafted", "captain"), fixture.me("scrim_drafted", "captain"));
    expect(await screen.findByRole("heading", { name: "Draft done" })).toBeInTheDocument();
    expect(screen.getAllByRole("list", { name: "Heroes" })).toHaveLength(2);
  });
});

describe("Teams picked toast", () => {
  it("toasts once when the player draft ends with the viewer on a team", async () => {
    const [match, me] = view("player_draft", "player");
    const { server } = open(match, me);
    await screen.findByRole("heading", { name: "P1 is picking" });
    const next = fixture.match("coinflip", "player");
    act(() => server.snap(`match:${match.id}`, next));
    await screen.findByRole("heading", { name: "P1 is choosing" });
    expect(notify.success).toHaveBeenCalledWith("Teams picked", "You're on P2's Team");
    act(() => server.snap(`match:${match.id}`, { ...next, deadline_at: "2026-01-05T19:00:30.000Z" }));
    expect(notify.success).toHaveBeenCalledTimes(1);
  });

  it("doesn't toast when the page opens after the draft", async () => {
    open(...view("coinflip", "player"));
    await screen.findByRole("heading", { name: "P1 is choosing" });
    expect(notify.success).not.toHaveBeenCalled();
  });

  it("doesn't toast spectators", async () => {
    const [match, me] = view("player_draft", "spectator");
    const { server } = open(match, me);
    await screen.findByRole("heading", { name: "P1 is picking" });
    act(() => server.snap(`match:${match.id}`, fixture.match("coinflip", "spectator")));
    await screen.findByRole("heading", { name: "P1 is choosing" });
    expect(notify.success).not.toHaveBeenCalled();
  });
});
