// A stand-in for the control API (devtools/README.md) and the Discord simulator's control API,
// so the panel can be built and checked without the dev stack. In-memory, no dependencies; the
// shapes follow the real services, the behaviour is only roughly like a match.
//
//   node mock/server.mjs                 one port (18099) serving /_control/ and /_sim/
//   MOCK_PORTS=8000,8090 node mock/...   several ports (the Docker smoke test uses this)
import http from "node:http";

const ports = (process.env.MOCK_PORTS ?? "18099").split(",").map(Number);
const FLOW = [
  "ready_check",
  "captain_phase",
  "captain_checkin",
  "player_draft",
  "coinflip",
  "champion_draft",
  "lobby_code",
  "in_progress",
  "awaiting_confirmation",
  "completed",
];
const TURN = {
  ready_check: "ready",
  captain_phase: "vote",
  captain_checkin: "checkin",
  player_draft: "player_pick",
  coinflip: "coinflip",
  champion_draft: "pick",
  lobby_code: "lobby_code",
  in_progress: "report",
  awaiting_confirmation: "confirm",
};
const GUILD = "1100000000000000001";
const BOT = "1100000000000000003";
const CHANNELS = [
  { id: "1100000000000000010", name: "Deadlock", type: 4, parent_id: null, position: 0 },
  { id: "1100000000000000011", name: "queue", type: 0, parent_id: "1100000000000000010", position: 0 },
  { id: "1100000000000000012", name: "results", type: 0, parent_id: "1100000000000000010", position: 1 },
  { id: "1100000000000000013", name: "Waiting Room", type: 2, parent_id: "1100000000000000010", position: 2 },
];
const QUEUE_CHANNEL = CHANNELS[1].id;
const MATCH_CHANNEL = "1100000000000000014";
CHANNELS.push({ id: MATCH_CHANNEL, name: "match-1", type: 0, parent_id: CHANNELS[0].id, position: 3 });
const SWAPPABLE = new Set(["coinflip", "champion_draft", "lobby_code"]);
// The modals the real bot opens (bot/handlers/results.py and draft.py), as the sim stores them.
const MODALS = {
  report_open: {
    custom_id: "report-modal",
    title: "Report the result",
    components: [
      { type: 18, id: 1, label: "Winning team", component: { type: 3, id: 2, custom_id: "winner", placeholder: "Who won?", min_values: 1, max_values: 1, options: [{ label: "Team A", value: "A" }, { label: "Team B", value: "B" }] } },
      { type: 18, id: 3, label: "Scoreboard screenshot", component: { type: 19, id: 4, custom_id: "shot", min_values: 1, max_values: 1, required: true } },
      { type: 18, id: 5, label: "Deadlock match ID", component: { type: 4, id: 6, custom_id: "dl", style: 1, required: false, max_length: 18, placeholder: "Optional" } },
    ],
  },
  lobby_code_open: {
    custom_id: "lobby-modal",
    title: "Enter the lobby code",
    components: [{ type: 1, id: 1, components: [{ type: 4, id: 2, custom_id: "code", label: "Custom lobby code", style: 1, min_length: 3, max_length: 32, placeholder: "From the Deadlock lobby" }] }],
  },
};
const SCENARIOS = [
  {
    name: "full_match",
    description: "A whole ranked match, one phase per step.",
    steps: [
      { title: "Start from the dev fixtures", method: "POST", path: "reset" },
      { title: "Twelve players join", method: "POST", path: "queue/join", body: { count: 12 } },
      { title: "Everyone readies up", method: "POST", path: "matches/latest/advance", body: { until: "captain_phase" } },
      { title: "Play it out", method: "POST", path: "matches/latest/advance", body: { until: "completed" } },
    ],
  },
  {
    name: "ready_check_miss",
    description: "The ready check runs out.",
    steps: [
      { title: "Fill the queue", method: "POST", path: "queue/fill" },
      { title: "The timer runs out", method: "POST", path: "matches/latest/fire" },
    ],
  },
  {
    name: "swap_players",
    description: "After the player draft, one captain offers a swap and the other accepts.",
    steps: [
      { title: "Start from the dev fixtures", method: "POST", path: "reset" },
      { title: "Twelve players join", method: "POST", path: "queue/join", body: { count: 12 } },
      { title: "Through to the coinflip", method: "POST", path: "matches/latest/advance", body: { until: "coinflip" } },
      { title: "Team A's captain offers a swap", method: "POST", path: "matches/latest/act", body: { action: "swap", player_id: "captain:A" }, expect: { status: "coinflip" } },
      { title: "Team B's captain accepts", method: "POST", path: "matches/latest/act", body: { action: "accept_swap", player_id: "captain:B" } },
      { title: "A second answer is refused", method: "POST", path: "matches/latest/act", body: { action: "accept_swap", player_id: "captain:B" }, expect: { http: 409 } },
      { title: "The rest of the match", method: "POST", path: "matches/latest/advance", body: { until: "completed" } },
    ],
  },
];

let seq = 0;
let nextSnowflake = 1100000000000000100n;
let db;
const clients = new Set();

function emit(kind, fields) {
  const entry = { seq: ++seq, time: Date.now() / 1000, kind, ...fields };
  for (const res of clients) res.write(`id: ${entry.seq}\nevent: ${kind}\ndata: ${JSON.stringify(entry)}\n\n`);
}

const error = (status, code, message) => Object.assign(new Error(message), { status, code });

function botMessage(channelId, content, components = []) {
  const id = String(nextSnowflake++);
  const message = {
    id,
    channel_id: channelId,
    author_id: BOT,
    author_name: "Draft Bot",
    content,
    text: [],
    flags: 0,
    ephemeral: false,
    loading: false,
    created_at: new Date().toISOString(),
    edited_at: null,
    components,
    attachments: [],
    raw: { id, channel_id: channelId, content, author: { id: BOT, username: "Draft Bot", bot: true }, embeds: [] },
  };
  db.messages.push(message);
  emit("rest", { method: "POST", path: `/api/v10/channels/${channelId}/messages`, status: 200 });
  return message;
}

const button = (custom_id, label, style = 2, emoji = null) => ({
  type: 2, custom_id, label, emoji, style, url: null, disabled: false, options: [],
});

function reset() {
  db = { players: [], queue: [], matches: [], messages: [], attachments: new Map(), pausedAll: false, lobbies: "create", nextPk: 1, nextMatch: 1, nextSwap: 1 };
  botMessage(QUEUE_CHANNEL, "Queue is open.", [button("queue:join", "Join queue", 3), button("queue:leave", "Leave")]);
  addPlayers({ count: 12, name_prefix: "Dev " });
}

function playerModel(p) {
  const position = db.queue.indexOf(p.id);
  const match = db.matches.find((m) => m.status !== "completed" && m.player_ids.includes(p.id));
  return {
    id: p.id,
    discord_user_id: p.discord_user_id,
    name: p.name,
    rating: p.rating,
    games: 0,
    queued: position >= 0,
    queue_position: position >= 0 ? position + 1 : null,
    match_id: match ? match.id : null,
    dm_open: p.dm_open,
    sim_user: true,
    picks: p.picks,
  };
}

function addPlayers({ count = 1, rating, name_prefix = "Dev ", dm_open = true, join_queue = false }) {
  const made = [];
  for (let i = 0; i < count; i++) {
    const pk = db.nextPk++;
    const value =
      typeof rating === "number" ? rating : rating ? rating.min + ((rating.max - rating.min) * i) / Math.max(1, count - 1) : 1500;
    const p = { id: pk, name: `${name_prefix}${pk}`, discord_user_id: String(nextSnowflake++), rating: Math.round(value), dm_open, picks: { prefer: [], ban: [] } };
    db.players.push(p);
    made.push(p);
    emit("control", { method: "POST", path: "/_sim/users", status: 201 });
  }
  const matchId = join_queue ? joinQueue(made.map((p) => p.id)) : null;
  return { players: made.map(playerModel), match_id: matchId };
}

const busy = (id) => db.queue.includes(id) || db.matches.some((m) => m.status !== "completed" && m.player_ids.includes(id));

function joinQueue(ids) {
  for (const id of ids) if (!busy(id)) db.queue.push(id);
  return db.queue.length >= 12 ? popMatch() : null;
}

function popMatch() {
  const ids = db.queue.splice(0, 12);
  const match = { id: db.nextMatch++, status: "ready_check", step_index: 0, frozen: false, picks: [], ready: new Set(), checkedIn: new Set(), swaps: [], player_ids: ids, script: {} };
  match.deadline = Date.now() + 180_000;
  db.matches.push(match);
  botMessage(QUEUE_CHANNEL, `Match #${match.id} popped. Ready up!`, [
    button(`ready:${match.id}`, "Ready", 3, { name: "✅" }),
    { type: 3, custom_id: `side:${match.id}`, label: "Pick a side", emoji: null, style: null, url: null, disabled: false,
      options: [{ label: "Team A", value: "A" }, { label: "Team B", value: "B" }] },
  ]);
  botMessage(MATCH_CHANNEL, `Match #${match.id}: the lobby and the result.`, [
    button("lobby_code_open", "Enter lobby code", 1),
    button("report_open", "Report", 3),
  ]);
  return match.id;
}

function matchModel(m) {
  const stage = FLOW.indexOf(m.status);
  const players = m.player_ids.map((id, i) => {
    const p = db.players.find((x) => x.id === id);
    // Like the league models: "" until the player draft puts them on a team.
    const drafted = stage >= 4 || (i < 2 && stage >= 2) ? (i % 2 ? "B" : "A") : "";
    const swapped = m.swaps.some((s) => s.status === "accepted" && (s.give === id || s.take === id));
    const team = swapped ? (drafted === "A" ? "B" : "A") : drafted;
    const captain = i < 2 && stage >= 2;
    return { id, discord_user_id: p?.discord_user_id, name: p?.name ?? `#${id}`, rating: p?.rating ?? null, team, is_captain: captain, ready: m.ready.has(id) || stage > 0, checked_in: captain && (stage > 2 || m.checkedIn.has(id)), missed_checkin: false, active: true, removed_reason: "" };
  });
  const apiLobby = m.status === "lobby_code" && db.lobbies === "create";
  const action = apiLobby ? "api_lobby" : (TURN[m.status] ?? null);
  const waiting =
    m.status === "ready_check"
      ? players.filter((p) => !p.ready).map((p) => p.id)
      : m.status === "captain_checkin"
        ? players.filter((p) => p.is_captain && !p.checked_in).map((p) => p.id)
        : action && !apiLobby
          ? [players[m.step_index % 2].id]
          : [];
  return {
    id: m.id,
    status: m.status,
    kind: "ranked",
    mode: { slug: "draft_3ban", version: 1 },
    step_index: m.step_index,
    deadline_at: new Date(m.frozen ? Date.now() + 3e11 : m.deadline).toISOString(),
    seconds_left: Math.max(0, Math.round(((m.frozen ? m.left : m.deadline) - (m.frozen ? 0 : Date.now())) / 1000)),
    frozen: m.frozen,
    on_hold: false,
    held_seconds: null,
    turn: { action, team: action && m.status !== "ready_check" ? (m.step_index % 2 ? "B" : "A") : null, player_ids: waiting, step: m.step_index },
    captains: stage >= 1 ? { A: players[0].id, B: players[1].id } : {},
    teams: { A: players.filter((p) => p.team === "A").map((p) => p.id), B: players.filter((p) => p.team === "B").map((p) => p.id) },
    players,
    picks: m.picks,
    coinflip_winner: stage >= 4 ? "A" : "",
    hidden_king_team: "",
    champion_first_pick: "",
    lobby_code: m.lobbyCode ?? (stage > 6 ? `DEV${m.id}` : ""),
    lobby_code_host: players[0].id,
    api_lobby: { failed: db.lobbies === "fail" && stage >= 6, party_id: db.lobbies === "create" && stage > 6 ? `dev-${m.id}` : null, started: stage > 6 },
    winner: m.status === "completed" ? "A" : "",
    votes: m.status === "captain_phase" ? { [players[0].id]: 3, [players[1].id]: 2 } : {},
    sub_requests: [],
    swap_open: SWAPPABLE.has(m.status),
    swaps: m.swaps,
    text_channel_id: MATCH_CHANNEL,
    script: m.script,
    created_at: new Date().toISOString(),
    ended_at: null,
  };
}

function findMatch(ref) {
  const live = db.matches;
  const match = ref === "latest" ? live[live.length - 1] : live.find((m) => m.id === Number(ref));
  if (!match) throw error(404, "not_found", `No match ${ref}.`);
  return match;
}

function advance(m, until) {
  const from = m.status;
  const target = until ? FLOW.indexOf(until) : FLOW.indexOf(m.status) + 1;
  if (until && target <= FLOW.indexOf(m.status)) throw error(400, "bad_request", `The match is already past ${until}.`);
  const actions = [];
  while (FLOW.indexOf(m.status) < target && m.status !== "completed") {
    if (m.status === "player_draft") m.picks.push({ step: m.picks.length, action: "player_pick", team: "A", player_id: m.player_ids[2], champion: null, source: "user", random: false });
    if (m.status === "champion_draft") m.picks.push({ step: m.picks.length, action: "ban", team: "B", player_id: null, champion: { id: 1, slug: "infernus", name: "Infernus" }, source: "user", random: false });
    actions.push({ player_id: m.player_ids[0], action: TURN[m.status], args: {}, via: "service" });
    m.status = FLOW[FLOW.indexOf(m.status) + 1];
    m.step_index = 0;
    m.deadline = Date.now() + 45_000;
    emit("gateway", { event: "MESSAGE_UPDATE", data: { match: m.id, status: m.status } });
  }
  return { match: matchModel(m), from, to: m.status, actions };
}

function state() {
  return {
    community: { id: 1, guild_id: GUILD, name: "Dev League", active_mode: { id: 2, slug: "draft_3ban", version: 1 }, channels: { queue: QUEUE_CHANNEL } },
    season: { id: 1, number: 1 },
    lobby_size: 12,
    queue: db.queue.map((id, i) => ({ position: i + 1, joined_at: new Date().toISOString(), player: playerModel(db.players.find((p) => p.id === id)) })),
    matches: db.matches.filter((m) => m.status !== "completed").map(matchModel),
    recent: db.matches.filter((m) => m.status === "completed").map((m) => ({ id: m.id, status: m.status, winner: "A", ended_at: null })),
    timers: { paused_all: db.pausedAll, frozen_matches: db.matches.filter((m) => m.frozen).map((m) => m.id) },
    lobbies: db.lobbies,
    sim: { configured: true, reachable: true, url: "http://mock" },
  };
}

function call(method, path, body) {
  const [verb, sub] = [method, path.replace(/^\/+|\/+$/g, "")];
  let m;
  if (verb === "GET" && sub === "state") return state();
  if (verb === "POST" && sub === "reset") return reset(), { ok: true, seed: { players: 12 }, state: state() };
  if (verb === "GET" && sub === "players") return { players: db.players.map(playerModel) };
  if (verb === "POST" && sub === "players") return addPlayers(body);
  if (verb === "POST" && sub === "queue/join") {
    const ids = body.player_ids ?? db.players.filter((p) => !busy(p.id)).slice(0, body.count).map((p) => p.id);
    return { match_id: joinQueue(ids), queue: state().queue };
  }
  if (verb === "POST" && sub === "queue/leave") return (db.queue = db.queue.filter((id) => !body.player_ids.includes(id))), { queue: state().queue };
  if (verb === "POST" && sub === "queue/fill") {
    const made = addPlayers({ count: 12 - db.queue.length, rating: body.rating, name_prefix: "Fill " });
    return { players: made.players, match_id: joinQueue(made.players.map((p) => p.id)), queue: state().queue };
  }
  if (verb === "POST" && (sub === "timers/pause" || sub === "timers/resume")) {
    db.pausedAll = sub.endsWith("pause");
    for (const x of db.matches) setFrozen(x, db.pausedAll);
    return { paused_all: db.pausedAll, frozen_matches: db.matches.filter((x) => x.frozen).map((x) => x.id) };
  }
  if (verb === "PUT" && sub === "lobbies") {
    if (!["create", "fail"].includes(body.lobby)) throw error(400, "bad_request", 'lobby is "create" or "fail".');
    return (db.lobbies = body.lobby), { lobbies: db.lobbies };
  }
  if (verb === "GET" && sub === "scenarios") return { scenarios: SCENARIOS };
  if (verb === "POST" && sub === "scenarios/run") {
    const steps = body.name ? SCENARIOS.find((s) => s.name === body.name).steps : body.steps;
    const start = body.from ?? 0;
    const end = body.count == null ? steps.length : Math.min(steps.length, start + body.count);
    const ran = [];
    for (let index = start; index < end; index++) {
      const step = steps[index];
      const [status, response] = respond(step.method, step.path, step.body ?? {});
      ran.push({ index, ...step, status, response });
      if (status >= 400) return { ok: false, ran, next: index, total: steps.length };
    }
    return { ok: true, ran, next: end, total: steps.length };
  }
  if ((m = sub.match(/^players\/(\d+)(\/picks)?$/))) {
    const p = db.players.find((x) => x.id === Number(m[1]));
    if (!p) throw error(404, "not_found", `No player ${m[1]}.`);
    if (m[2] && verb === "PUT") return (p.picks = { prefer: body.prefer ?? [], ban: body.ban ?? [] }), playerModel(p);
    if (verb === "PATCH") return Object.assign(p, body), playerModel(p);
    if (verb === "DELETE") {
      if (busy(p.id) && !db.queue.includes(p.id)) throw error(409, "invalid_action", "That player is in a live match.");
      db.queue = db.queue.filter((id) => id !== p.id);
      db.players = db.players.filter((x) => x !== p);
      return { deleted: "hard" };
    }
  }
  if ((m = sub.match(/^matches\/(\w+)\/(\w+)$/))) {
    const match = findMatch(m[1]);
    switch (m[2]) {
      case "advance":
        return advance(match, body.until);
      case "fire":
        advance(match);
        return { match: matchModel(match), fired: true };
      case "pause":
      case "resume":
        return setFrozen(match, m[2] === "pause"), matchModel(match);
      case "script":
        return (match.script = body), matchModel(match);
      case "act":
        act(match, body);
        return { match: matchModel(match), actions: [{ player_id: body.player_id ?? null, action: body.action, args: body.args ?? {}, via: body.via ?? "discord" }] };
    }
  }
  throw error(404, "not_found", `No route ${sub}. GET /_control/api/ lists them.`);
}

// One action as one player: enough of each to see the panel follow a match through.
function act(m, body) {
  const who = Number(body.player_id) || null;
  const args = body.args ?? {};
  const pending = m.swaps.find((s) => s.status === "pending");
  if (body.action === "ready") m.ready.add(who ?? m.player_ids[0]);
  else if (body.action === "checkin") {
    m.checkedIn.add(who ?? m.player_ids[0]);
    if (m.player_ids.slice(0, 2).every((id) => m.checkedIn.has(id))) advance(m);
  } else if (body.action === "swap") {
    if (!SWAPPABLE.has(m.status)) throw error(409, "stale_action", "Teams can only be swapped between the player draft and the game.");
    if (pending) throw error(409, "invalid_action", "A swap is already waiting for an answer.");
    m.swaps.push({ id: db.nextSwap++, status: "pending", requested_by: who ?? m.player_ids[0], give: Number(args.give ?? m.player_ids[2]), take: Number(args.take ?? m.player_ids[3]), deadline_at: new Date(Date.now() + 60_000).toISOString(), resolved_by: null });
  } else if (body.action === "accept_swap" || body.action === "decline_swap") {
    if (!pending) throw error(409, "invalid_action", `No swap is waiting for an answer in match #${m.id}.`);
    pending.status = body.action === "accept_swap" ? "accepted" : "declined";
    pending.resolved_by = who;
  } else if (TURN[m.status] === body.action || (body.action === "api_lobby" && m.status === "lobby_code")) advance(m);
}

function setFrozen(m, frozen) {
  if (frozen && !m.frozen) m.left = m.deadline - Date.now();
  if (!frozen && m.frozen) m.deadline = Date.now() + m.left;
  m.frozen = frozen;
}

function respond(method, path, body) {
  try {
    return [200, call(method, path, body)];
  } catch (err) {
    return [err.status ?? 500, { error: { code: err.code ?? "error", message: err.message } }];
  }
}

function member(p) {
  return { id: p.discord_user_id, name: p.name, username: p.name.toLowerCase().replace(/\s/g, ""), is_bot: false, is_owner: false, dm_open: p.dm_open, voice_channel_id: p.id <= 3 ? CHANNELS[3].id : null, roles: [], nick: null, dm_channel_id: null };
}

function simCall(method, path, body, query) {
  let m;
  if (method === "GET" && path === "/_sim/health") return { ok: true, version: "mock", bot_connected: true, sessions: 1 };
  if (method === "GET" && path === "/_sim/state") {
    const members = db.players.map(member);
    return {
      guild: { id: GUILD, name: "Sim Guild", owner_id: "1100000000000000002" },
      bot: { user_id: BOT, application_id: BOT, connected: true },
      roles: [],
      channels: CHANNELS.map((c) => ({ ...c, voice_members: c.type === 2 ? members.filter((x) => x.voice_channel_id === c.id).map((x) => x.id) : [], message_count: 0 })),
      members: [{ id: BOT, name: "Draft Bot", username: "draftbot", is_bot: true, dm_open: false, voice_channel_id: null }, ...members],
      commands: ["setup"],
    };
  }
  if ((m = path.match(/^\/_sim\/channels\/(\d+)\/messages$/))) {
    const limit = Number(query.get("limit") ?? 50);
    return { channel: CHANNELS.find((c) => c.id === m[1]) ?? null, messages: db.messages.filter((x) => x.channel_id === m[1]).reverse().slice(0, limit) };
  }
  if ((m = path.match(/^\/_sim\/users\/(\d+)\/dms$/))) {
    const p = db.players.find((x) => x.discord_user_id === m[1]);
    if (!p) throw Object.assign(new Error(`No user '${m[1]}'.`), { status: 404 });
    const dm = `dm-${m[1]}`;
    if (!db.messages.some((x) => x.channel_id === dm)) {
      botMessage(dm, `Hi ${p.name}, a sub spot is open in match #1.`, [button("sub:accept", "Take the spot", 1), button("sub:decline", "No thanks", 4)]);
    }
    return { channel_id: dm, messages: db.messages.filter((x) => x.channel_id === dm).reverse() };
  }
  if (method === "POST" && path === "/_sim/interactions/component") {
    const p = db.players.find((x) => x.discord_user_id === String(body.user_id));
    const source = db.messages.find((x) => x.id === String(body.message_id));
    if (!source) throw Object.assign(new Error("No message with that message_id."), { status: 404 });
    emit("gateway", { event: "INTERACTION_CREATE", data: { custom_id: body.custom_id } });
    const modal = MODALS[body.custom_id];
    if (modal) return { interaction_id: String(seq), type: 3, response: { type: 9, data: modal }, settled: true, message: null, followups: [], modal, choices: null };
    const reply = botMessage(source.channel_id, `${p?.name ?? body.user_id} pressed ${body.custom_id}${body.values ? ` (${body.values.join(", ")})` : ""}`);
    return { interaction_id: String(seq), type: 3, response: { type: 4 }, settled: true, message: reply, modal: null, choices: null };
  }
  if (method === "POST" && path === "/_sim/interactions/modal") {
    const p = db.players.find((x) => x.discord_user_id === String(body.user_id));
    const files = Object.values(body.attachments ?? {}).flat();
    const names = files.map((f) => (typeof f === "string" ? (db.attachments.get(f) ?? f) : f.filename));
    emit("gateway", { event: "INTERACTION_CREATE", data: { type: 5, custom_id: body.custom_id } });
    const text = `${p?.name ?? body.user_id} submitted ${body.custom_id}: ${JSON.stringify(body.values ?? {})}${names.length ? ` with ${names.join(", ")}` : ""}`;
    return { interaction_id: String(seq), type: 5, response: { type: 5 }, settled: true, message: botMessage(MATCH_CHANNEL, text), followups: [], modal: null, choices: null };
  }
  if (method === "POST" && path === "/_sim/attachments") {
    const id = String(nextSnowflake++);
    const filename = body.filename ?? "file";
    db.attachments.set(id, filename);
    return { id, filename, url: `/_sim/attachments/${id}`, sim_url: `/_sim/attachments/${id}` };
  }
  if (method === "POST" && path === "/_sim/messages") {
    const p = db.players.find((x) => x.discord_user_id === String(body.user_id));
    const channel = body.dm ? `dm-${body.user_id}` : String(body.channel_id);
    const message = botMessage(channel, body.content);
    Object.assign(message, { author_id: String(body.user_id), author_name: p?.name ?? "user" });
    message.raw.author = { id: String(body.user_id), bot: false };
    emit("gateway", { event: "MESSAGE_CREATE", data: { channel_id: channel } });
    return message;
  }
  throw Object.assign(new Error(`mock: no route ${method} ${path}`), { status: 404 });
}

// Snowflakes may arrive as exact JSON numbers; keep their digits like the Python services do.
function parseBody(text) {
  return JSON.parse(text, (_key, value, context) =>
    typeof value === "number" && !Number.isSafeInteger(value) ? context.source : value,
  );
}

function handler(req, res) {
  const url = new URL(req.url, "http://mock");
  if (url.pathname === "/_sim/events") {
    res.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-cache", "X-Accel-Buffering": "no" });
    res.write(": hello\n\n");
    clients.add(res);
    req.on("close", () => clients.delete(res));
    return;
  }
  let chunks = "";
  req.on("data", (c) => (chunks += c));
  req.on("end", () => {
    // Uploads: only the file name matters to the mock.
    const multipart = (req.headers["content-type"] ?? "").startsWith("multipart/form-data");
    const body = multipart ? { filename: /filename="([^"]*)"/.exec(chunks)?.[1] } : chunks ? parseBody(chunks) : {};
    let status = 200;
    let out;
    if (url.pathname.startsWith("/_control/api/")) {
      [status, out] = respond(req.method, url.pathname.slice("/_control/api/".length), body);
    } else {
      try {
        out = simCall(req.method, url.pathname, body, url.searchParams);
      } catch (err) {
        status = err.status ?? 500;
        out = { error: err.message };
      }
    }
    if (status === 200 && req.method === "POST" && url.pathname === "/_sim/attachments") status = 201;
    res.writeHead(status, { "Content-Type": "application/json" });
    res.end(JSON.stringify(out ?? null));
  });
}

reset();
setInterval(() => emit("gateway", { event: "HEARTBEAT_ACK" }), 10_000);
for (const port of ports) {
  http.createServer(handler).listen(port, "0.0.0.0", () => console.log(`mock API on :${port}`));
}
