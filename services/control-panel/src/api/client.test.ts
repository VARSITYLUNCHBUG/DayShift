import { describe, expect, it } from "vitest";

import { parseChampionLines } from "../lib/match";
import { createControlApi } from "./control";
import { ApiError, JsonClient, parseJson, type FetchLike } from "./http";
import { SimModal } from "./schemas";
import { createSimApi, parseEventData } from "./sim";

interface Call {
  url: string;
  method: string;
  body: string | undefined;
  form: FormData | undefined;
  headers: Record<string, string>;
}

/** A fetch stand-in that records calls and answers with a canned status and body text. */
function fakeFetch(status: number, body: string): { fetcher: FetchLike; calls: Call[] } {
  const calls: Call[] = [];
  const fetcher: FetchLike = (url, init) => {
    calls.push({
      url,
      method: init?.method ?? "GET",
      body: typeof init?.body === "string" ? init.body : undefined,
      form: init?.body instanceof FormData ? init.body : undefined,
      headers: (init?.headers ?? {}) as Record<string, string>,
    });
    return Promise.resolve(new Response(body, { status }));
  };
  return { fetcher, calls };
}

const json = (value: unknown) => JSON.stringify(value);

// Shapes copied from devtools/README.md ("Read models") and services/discord-sim control.py.
const PLAYER = {
  id: 7,
  discord_user_id: "1100000000000000123",
  name: "Dev 7",
  rating: 1200,
  mu: "54.999999",
  sigma: "8.333333",
  games: 0,
  queued: true,
  queue_position: 3,
  match_id: null,
  dm_open: true,
  sim_user: true,
  picks: { prefer: ["haze", "wraith"], ban: ["seven"] },
};

const MATCH = {
  id: 1,
  status: "player_draft",
  kind: "ranked",
  mode: { slug: "draft_3ban", version: 1 },
  version: 31,
  step_index: 2,
  deadline_at: "2026-11-16T21:04:05Z",
  seconds_left: 41,
  frozen: false,
  on_hold: false,
  held_seconds: null,
  turn: { action: "player_pick", team: "B", player_ids: [4], step: 2 },
  captains: { A: 1, B: 4 },
  teams: { A: [1, 9], B: [4] },
  players: [
    { id: 1, discord_user_id: "1100000000000000101", name: "Dev 1", rating: 1500, team: "A", is_captain: true, ready: true, active: true, removed_reason: "" },
    { id: 4, discord_user_id: "1100000000000000104", name: "Dev 4", rating: 1400, team: "B", is_captain: true, ready: true, active: true, removed_reason: "" },
    { id: 9, discord_user_id: "1100000000000000109", name: "Dev 9", rating: 1100, team: "A", is_captain: false, ready: true, active: true, removed_reason: "" },
    // Not drafted yet: the league stores a blank team.
    { id: 3, discord_user_id: "1100000000000000103", name: "Dev 3", rating: 1000, team: "", is_captain: false, ready: true, active: true, removed_reason: "" },
  ],
  swaps: [{ id: 5, status: "declined", requested_by: 1, give: 9, take: 4, deadline_at: "2026-11-16T21:05:00Z" }],
  picks: [
    { step: 0, action: "player_pick", team: "A", player_id: 9, champion: null, source: "user", random: false },
    { step: 10, action: "ban", team: "B", player_id: null, champion: { id: 1, slug: "infernus", name: "Infernus" }, source: "timeout", random: true },
  ],
  coinflip_winner: "",
  hidden_king_team: "",
  champion_first_pick: "",
  lobby_code: "",
  lobby_code_host: null,
  winner: "",
  votes: {},
  sub_requests: [{ id: 2, status: "open", reason: "sub_out", leaving: 9, requested_by: 9, offers: [{ id: 3, player_id: 13, status: "pending" }] }],
  text_channel_id: "1100000000000000207",
  script: { draft: [9, 3], champions: [], captain_votes: {} },
  created_at: "2026-11-16T21:00:00Z",
  ended_at: null,
};

describe("parseJson", () => {
  it("keeps integers beyond 2^53 exact", () => {
    const value = parseJson('{"id": 1100000000000000123, "small": 42}') as Record<string, unknown>;
    expect(value.id).toBe("1100000000000000123");
    expect(value.small).toBe(42);
  });
});

describe("JsonClient", () => {
  it("builds urls, sends JSON and parses the reply", async () => {
    const { fetcher, calls } = fakeFetch(200, json({ ok: true }));
    const client = new JsonClient("/_sim/", fetcher);
    const out = await client.raw("/log", { method: "POST", body: { a: 1 }, query: { since: 5, skip: undefined } });
    expect(out).toEqual({ ok: true });
    expect(calls[0]?.url).toBe("/_sim/log?since=5");
    expect(calls[0]?.method).toBe("POST");
    expect(calls[0]?.body).toBe('{"a":1}');
    expect(calls[0]?.headers["Content-Type"]).toBe("application/json");
  });

  it("raises the control API's error message", async () => {
    const body = json({ error: { code: "invalid_action", message: "You are not in this match." } });
    const err = await createControlApi("/c", fakeFetch(409, body).fetcher)
      .fire(3)
      .catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(409);
    expect((err as ApiError).message).toBe("You are not in this match.");
  });

  it("raises the simulator's error message", async () => {
    const err = await createSimApi("/_sim", fakeFetch(404, json({ error: "No user '9'." })).fetcher)
      .userDms("9")
      .catch((e: unknown) => e);
    expect((err as ApiError).message).toBe("No user '9'.");
  });

  it("falls back to the text or the status", async () => {
    const text = await createControlApi("/x", fakeFetch(502, "Bad Gateway").fetcher)
      .state()
      .catch((e: unknown) => e);
    expect((text as ApiError).message).toBe("Bad Gateway");
    const empty = await createControlApi("/x", fakeFetch(500, "").fetcher)
      .state()
      .catch((e: unknown) => e);
    expect((empty as ApiError).message).toBe("GET state failed with 500");
  });

  it("raises ApiError naming the field when the shape is wrong", async () => {
    const { fetcher } = fakeFetch(200, json({ matches: [{ id: 1 }] }));
    const err = await createControlApi("/x", fetcher).state().catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).message).toMatch(/matches\.0\.status/);
  });
});

describe("control API", () => {
  it("reads state", async () => {
    const state = {
      community: {
        id: 1,
        guild_id: "1100000000000000001",
        name: "Dev League",
        active_mode: { id: 2, slug: "draft_3ban", version: 1 },
        channels: { queue: "1100000000000000010" },
      },
      season: { id: 1, number: 1 },
      lobby_size: 12,
      queue: [{ position: 1, joined_at: "2026-11-16T21:00:00Z", player: PLAYER }],
      matches: [MATCH],
      recent: [{ id: 3, status: "completed", winner: "A", ended_at: "2026-11-16T20:00:00Z" }],
      timers: { paused_all: true, frozen_matches: [1] },
      sim: { configured: true, reachable: false, url: "http://discord-sim:8090", bot_on_sim: false },
    };
    const { fetcher, calls } = fakeFetch(200, json(state));
    const out = await createControlApi("/_control/api", fetcher).state();
    expect(calls[0]?.url).toBe("/_control/api/state");
    expect(out.community).toEqual({ id: 1, name: "Dev League" });
    expect(out.mode).toBe("draft_3ban v1");
    expect(out.queue[0]).toMatchObject({ id: 7, name: "Dev 7", inQueue: true, discordId: "1100000000000000123" });
    expect(out.timersPaused).toBe(true);
    expect(out.simReachable).toBe(false);
    expect(out.botOnSim).toBe(false);
    expect(out.recent).toEqual([{ id: 3, status: "completed", winner: "A" }]);
  });

  it("reads a match: turn names, pick labels, blanks as null", async () => {
    const out = await createControlApi("/c", fakeFetch(200, json({ matches: [MATCH] })).fetcher).state();
    const match = out.matches[0];
    expect(match?.turn).toEqual({ action: "player_pick", team: "B", playerIds: [4], names: ["Dev 4"] });
    expect(match?.picks.map((p) => [p.action, p.label, p.random])).toEqual([
      ["player_pick", "Dev 9", false],
      ["ban", "Infernus", true],
    ]);
    expect(match?.players[0]).toMatchObject({ isCaptain: true, team: "A", removedReason: null });
    expect(match?.players[3]).toMatchObject({ name: "Dev 3", team: null });
    expect(match?.winner).toBeNull();
    expect(match?.subRequests).toEqual([{ id: 2, status: "open", reason: "sub_out", leaving: "Dev 9", offers: 1, pendingOffers: 1 }]);
    expect(match?.swaps).toEqual([{ id: 5, status: "declined", requestedBy: 1, give: 9, take: 4, label: "Dev 9 ⇄ Dev 4" }]);
    expect(match?.players[0]?.checkedIn).toBeNull();
    expect(match?.script).toEqual({ draft: [9, 3], champions: [], captain_votes: {} });
  });

  it("reads a fresh install (no community)", async () => {
    const empty = { community: null, season: null, lobby_size: null, queue: [], matches: [], recent: [], timers: { paused_all: false, frozen_matches: [] }, sim: { configured: false, reachable: false, url: "" } };
    const out = await createControlApi("/c", fakeFetch(200, json(empty)).fetcher).state();
    expect(out).toMatchObject({ community: null, mode: null, lobbySize: 12, matches: [] });
  });

  it("reads players", async () => {
    const out = await createControlApi("/c", fakeFetch(200, json({ players: [PLAYER] })).fetcher).players();
    expect(out[0]).toMatchObject({ id: 7, dmOpen: true, simUser: true, picks: { prefer: ["haze", "wraith"], ban: ["seven"] } });
  });

  it("posts the documented bodies", async () => {
    const { fetcher, calls } = fakeFetch(200, "{}");
    const api = createControlApi("/c", fetcher);
    await api.createPlayers({ count: 4, rating: { min: 800, max: 1600 }, join_queue: true });
    await api.setPicks(2, { prefer: ["haze"], ban: [] });
    await api.leaveQueue([1, 2]);
    await api.fillQueue();
    await api.act(1, { player_id: "captain:A", action: "report", args: { winner: "B" }, via: "service" });
    await api.setScript(1, { draft: [9, 3], champions: parseChampionLines("0 infernus\n4 haze A"), winner: "B" });
    expect(calls.map((c) => `${c.method} ${c.url} ${c.body ?? ""}`)).toEqual([
      'POST /c/players {"count":4,"rating":{"min":800,"max":1600},"join_queue":true}',
      'PUT /c/players/2/picks {"prefer":["haze"],"ban":[]}',
      'POST /c/queue/leave {"player_ids":[1,2]}',
      "POST /c/queue/fill {}",
      'POST /c/matches/1/act {"player_id":"captain:A","action":"report","args":{"winner":"B"},"via":"service"}',
      'PUT /c/matches/1/script {"draft":[9,3],"champions":[{"step":0,"slug":"infernus"},{"step":4,"slug":"haze","team":"A"}],"winner":"B"}',
    ]);
  });

  it("reads what advance did", async () => {
    const body = json({ match: MATCH, from: "ready_check", to: "player_draft", actions: [{}, {}] });
    const { fetcher, calls } = fakeFetch(200, body);
    const out = await createControlApi("/c", fetcher).advance(1, { until: "player_draft", via: "discord" });
    expect(calls[0]?.body).toBe('{"until":"player_draft","via":"discord"}');
    expect(out).toEqual({ from: "ready_check", to: "player_draft", actions: 2 });
  });

  it("lists scenarios and runs one step of them", async () => {
    const list = { scenarios: [{ name: "full_match", description: "A whole match", steps: [{ title: "Reset", method: "POST", path: "reset" }] }] };
    const scenarios = await createControlApi("/c", fakeFetch(200, json(list)).fetcher).scenarios();
    expect(scenarios[0]).toMatchObject({ name: "full_match", description: "A whole match" });

    const ran = { ok: false, ran: [{ index: 3, title: "x", method: "POST", path: "fire", status: 409, seconds: 0.25, response: { error: {} } }], next: 3, total: 9 };
    const { fetcher, calls } = fakeFetch(200, json(ran));
    const out = await createControlApi("/c", fetcher).runSteps([{ method: "POST", path: "fire" }], 3, 1);
    expect(calls[0]?.body).toBe('{"steps":[{"method":"POST","path":"fire"}],"from":3,"count":1}');
    expect(out).toEqual({ ok: false, ran: [{ index: 3, status: 409, seconds: 0.25, response: { error: {} } }], next: 3, total: 9 });
  });
});

describe("sim API", () => {
  it("reads health and state", async () => {
    const health = await createSimApi("/_sim", fakeFetch(200, json({ ok: true, version: "0.1.0", bot_connected: false, sessions: 0 })).fetcher).health();
    expect(health).toEqual({ ok: true, version: "0.1.0", botConnected: false });

    const state = {
      guild: { id: "1100000000000000001", name: "Sim Guild", owner_id: "1100000000000000002" },
      bot: { user_id: "1100000000000000003", application_id: "1100000000000000003", connected: true },
      roles: [],
      channels: [
        { id: "11", name: "Waiting Room", type: 2, parent_id: null, position: 0, voice_members: ["21"], message_count: 0 },
      ],
      members: [
        { id: "21", name: "Dev 1", username: "dev1", is_bot: false, is_owner: false, dm_open: false, voice_channel_id: "11", roles: [], nick: null, dm_channel_id: null },
      ],
      commands: [],
    };
    const out = await createSimApi("/_sim", fakeFetch(200, json(state)).fetcher).state();
    expect(out.botUserId).toBe("1100000000000000003");
    expect(out.botConnected).toBe(true);
    expect(out.channels[0]).toMatchObject({ type: 2, voiceMembers: ["21"] });
    expect(out.members[0]).toMatchObject({ id: "21", name: "Dev 1", isBot: false, dmOpen: false, voiceChannelId: "11" });
  });

  it("flattens messages and clicks as a fake user", async () => {
    const message = {
      id: "900",
      channel_id: "11",
      author_id: "5",
      author_name: "DayShift",
      content: "",
      text: ["Match #1", "Ready up"],
      flags: 32768 | 64,
      ephemeral: true,
      ephemeral_for: "1100000000000000100",
      loading: false,
      created_at: "2026-11-16T21:00:00Z",
      edited_at: null,
      components: [{ type: 2, custom_id: "ready:1", label: "Ready", emoji: { name: "✅" }, style: 3, url: null, disabled: false, options: [], min_values: null, max_values: null }],
      attachments: [],
      raw: { author: { id: "5", bot: true }, embeds: [] },
    };
    const { fetcher, calls } = fakeFetch(200, json({ channel: {}, messages: [message] }));
    const api = createSimApi("/_sim", fetcher);
    const list = await api.channelMessages("11", 20);
    expect(calls[0]?.url).toBe("/_sim/channels/11/messages?limit=20");
    expect(list[0]).toMatchObject({ authorName: "DayShift", authorIsBot: true, text: "Match #1\n\nReady up", ephemeralFor: "1100000000000000100" });
    expect(list[0]?.components[0]).toMatchObject({ customId: "ready:1", label: "Ready", emoji: "✅", style: 3 });

    await api.sendMessage("21", { dm: true }, "hi");
    expect(calls[1]?.body).toBe('{"user_id":"21","dm":true,"content":"hi"}');
  });

  it("summarises log events", () => {
    const rest = { seq: 1, time: 1763326800.5, kind: "rest", method: "POST", path: "/api/v10/channels/1/messages", status: 200 };
    expect(parseEventData(json(rest))).toMatchObject({ seq: 1, kind: "rest", summary: "POST /api/v10/channels/1/messages → 200" });
    expect(parseEventData(json({ seq: 2, time: 1, kind: "gateway", event: "MESSAGE_CREATE", data: {} }))?.summary).toBe(
      "MESSAGE_CREATE",
    );
    expect(parseEventData("not json")).toBeNull();
  });
});

// The report modal as discord.py 2.7.1 sends it (bot/handlers/results.py ReportModal), with
// the ids the sim adds, and the lobby code modal's older ActionRow form.
const REPORT_MODAL = {
  custom_id: "f1e2d3",
  title: "Report the result",
  components: [
    {
      type: 18,
      id: 1,
      label: "Winning team",
      component: { type: 3, id: 2, custom_id: "w", placeholder: "Who won?", min_values: 1, max_values: 1, options: [{ label: "Team Ash", value: "A" }, { label: "Team Bo", value: "B" }] },
    },
    { type: 18, id: 3, label: "Scoreboard screenshot", component: { type: 19, id: 4, custom_id: "shot", min_values: 1, max_values: 1, required: true } },
    { type: 18, id: 5, label: "Deadlock match ID", component: { type: 4, id: 6, custom_id: "dl", style: 1, required: false, max_length: 18, placeholder: "Optional" } },
    { type: 18, id: 7, label: "Key players", component: { type: 3, id: 8, custom_id: "keys", min_values: 0, max_values: 2, required: false, options: [{ label: "Dev 9", value: "9" }] } },
  ],
};

describe("sim modals", () => {
  it("turns a clicked button's modal into fields", async () => {
    const answer = { interaction_id: "77", type: 3, response: { type: 9, data: REPORT_MODAL }, settled: true, message: null, followups: [], modal: REPORT_MODAL, choices: null };
    const { fetcher, calls } = fakeFetch(200, json(answer));
    const out = await createSimApi("/_sim", fetcher).clickComponent({ user_id: "21", message_id: "900", custom_id: "dl:v1:report_open:1:" });
    expect(JSON.parse(calls[0]?.body ?? "{}")).toMatchObject({ custom_id: "dl:v1:report_open:1:", followup_wait: 1 });
    expect(out.replies).toEqual([]);
    expect(out.modal?.title).toBe("Report the result");
    expect(out.modal?.fields.map((f) => [f.kind, f.kind === "note" ? f.text : f.label, f.kind === "note" ? null : f.required])).toEqual([
      ["select", "Winning team", true],
      ["file", "Scoreboard screenshot", true],
      ["text", "Deadlock match ID", false],
      ["select", "Key players", false],
    ]);
    expect(out.modal?.fields[0]).toMatchObject({ options: [{ label: "Team Ash", value: "A", description: null }, { label: "Team Bo", value: "B", description: null }], maxValues: 1 });
    expect(out.modal?.fields[3]).toMatchObject({ maxValues: 2 });
  });

  it("reads a text input in an ActionRow, and a note", () => {
    const legacy = {
      custom_id: "m2",
      title: "Enter the lobby code",
      components: [
        { type: 10, id: 1, content: "Ask the host." },
        { type: 1, id: 2, components: [{ type: 4, id: 3, custom_id: "code", label: "Custom lobby code", style: 1, min_length: 3, max_length: 32 }] },
      ],
    };
    const out = SimModal.parse(legacy);
    expect(out.fields).toEqual([
      { kind: "note", text: "Ask the host." },
      { kind: "text", customId: "code", label: "Custom lobby code", description: null, required: true, multiline: false, placeholder: null, minLength: 3, maxLength: 32, value: "" },
    ]);
  });

  it("echoes the bot's reply and refusals, not the board a button edits", async () => {
    const reply = (id: string, content: string) => ({ id, channel_id: "11", content, components: [], raw: {} });
    const deferredUpdate = { interaction_id: "78", response: { type: 6 }, message: reply("900", "the board"), followups: [reply("901", "It isn't your turn.")], modal: null };
    const out = await createSimApi("/_sim", fakeFetch(200, json(deferredUpdate)).fetcher).clickComponent({ user_id: "21", message_id: "900", custom_id: "x" });
    expect(out.replies).toEqual(["It isn't your turn."]);
    const answered = { interaction_id: "79", response: { type: 5 }, message: reply("902", "Code shared with both teams."), followups: [] };
    const sent = await createSimApi("/_sim", fakeFetch(200, json(answered)).fetcher).submitModal({ user_id: "21", custom_id: "m2", values: { code: "ABC" }, attachments: {} });
    expect(sent.replies).toEqual(["Code shared with both teams."]);
  });

  it("uploads a file as multipart, then names it in the modal submit", async () => {
    const { fetcher, calls } = fakeFetch(201, json({ id: "1571689348791795835", filename: "board.png", url: "http://x/attachments/1/2/board.png" }));
    const api = createSimApi("/_sim", fetcher);
    const stored = await api.uploadAttachment(new Blob(["png"], { type: "image/png" }), "board.png");
    expect(stored).toEqual({ id: "1571689348791795835", filename: "board.png" });
    expect(calls[0]?.url).toBe("/_sim/attachments");
    expect(calls[0]?.headers["Content-Type"]).toBeUndefined();
    expect((calls[0]?.form?.get("file") as File).name).toBe("board.png");

    await api.submitModal({ user_id: "21", custom_id: "f1e2d3", values: { w: ["A"] }, attachments: { shot: [stored.id], other: [{ filename: "screenshot.png" }] } }).catch(() => undefined);
    expect(JSON.parse(calls[1]?.body ?? "{}")).toEqual({
      user_id: "21",
      custom_id: "f1e2d3",
      values: { w: ["A"] },
      attachments: { shot: ["1571689348791795835"], other: [{ filename: "screenshot.png" }] },
      followup_wait: 1,
    });
  });
});
