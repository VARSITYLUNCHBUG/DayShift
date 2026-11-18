/**
 * Response shapes of the dev control API (`/_control/api/`, devtools/README.md) and the Discord
 * simulator's control API (`/_sim/`, services/discord-sim), parsed into the view models the
 * screens use. Fields the panel doesn't need are ignored, optional ones default, so a backend
 * tweak is a fix here and not in every screen.
 */
import { z } from "zod";

/** Discord ids: both APIs send strings; numbers (kept exact by `parseJson`) are accepted too. */
export const Snowflake = z.union([z.string(), z.number()]).transform(String);

const Pk = z.number().int();
const optStr = z.string().nullish();
const optNum = z.number().nullish();
const optBool = z.boolean().nullish();
const strList = z
  .array(z.union([z.string(), z.number()]).transform(String))
  .nullish()
  .transform((v) => v ?? []);
const Team = z.enum(["A", "B"]);
/** Empty strings mean "not set" in the league models; treat them as null. */
const blank = z
  .string()
  .nullish()
  .transform((v) => (v ? v : null));
/** A participant's team: `""` until the player draft puts them on one. */
const blankTeam = z
  .union([Team, z.literal("")])
  .nullish()
  .transform((v) => (v ? v : null));

/* ------------------------------------------------------------------ control: players */

export const PlayerPicks = z.object({ prefer: strList, ban: strList });
export type PlayerPicks = z.output<typeof PlayerPicks>;

export const Player = z
  .object({
    id: Pk,
    name: z.string(),
    discord_user_id: Snowflake.nullish(),
    rating: optNum,
    games: optNum,
    queued: optBool,
    queue_position: optNum,
    match_id: Pk.nullish(),
    dm_open: optBool,
    sim_user: optBool,
    picks: PlayerPicks.nullish(),
  })
  .transform((p) => ({
    id: p.id,
    name: p.name,
    discordId: p.discord_user_id ?? null,
    rating: p.rating ?? null,
    games: p.games ?? 0,
    inQueue: p.queued ?? false,
    matchId: p.match_id ?? null,
    dmOpen: p.dm_open ?? null,
    simUser: p.sim_user ?? false,
    picks: p.picks ?? { prefer: [], ban: [] },
  }));
export type Player = z.output<typeof Player>;

/** `GET players`: `{players: [...]}`. */
export const PlayerList = z.object({ players: z.array(Player) }).transform((r) => r.players);

/* ------------------------------------------------------------------ control: matches */

const MatchPlayer = z
  .object({
    id: Pk,
    name: z.string(),
    discord_user_id: Snowflake.nullish(),
    rating: optNum,
    team: blankTeam,
    is_captain: optBool,
    ready: optBool,
    checked_in: optBool,
    missed_checkin: optBool,
    active: optBool,
    removed_reason: blank,
  })
  .transform((p) => ({
    id: p.id,
    name: p.name,
    discordId: p.discord_user_id ?? null,
    rating: p.rating ?? null,
    team: p.team,
    isCaptain: p.is_captain ?? false,
    ready: p.ready ?? null,
    /** Captains only, from the captain check-in on. */
    checkedIn: p.checked_in ?? null,
    /** Replaced as captain for missing the check-in. */
    missedCheckin: p.missed_checkin ?? false,
    active: p.active ?? true,
    removedReason: p.removed_reason,
  }));
export type MatchPlayer = z.output<typeof MatchPlayer>;

const Champion = z.object({ id: Pk.nullish(), slug: z.string(), name: optStr });

const MatchPick = z
  .object({
    step: optNum,
    action: z.string(),
    team: Team.nullish(),
    player_id: Pk.nullish(),
    champion: Champion.nullish(),
    source: optStr,
    random: optBool,
  })
  .transform((p) => ({
    step: p.step ?? null,
    action: p.action,
    team: p.team ?? null,
    playerId: p.player_id ?? null,
    champion: p.champion ? (p.champion.name ?? p.champion.slug) : null,
    source: p.source ?? null,
    random: p.random ?? false,
  }));
export type MatchPick = z.output<typeof MatchPick>;

const Turn = z.object({
  action: optStr,
  team: Team.nullish(),
  player_ids: z.array(Pk).nullish(),
  step: optNum,
});

const SubRequest = z.object({
  id: Pk,
  status: z.string(),
  reason: optStr,
  leaving: Pk.nullish(),
  offers: z.array(z.object({ id: Pk, player_id: Pk, status: z.string() })).nullish(),
});

/** A captain offering one of their players for one of the other team's (`league.PlayerSwap`). */
const Swap = z.object({
  id: Pk,
  status: z.string(),
  requested_by: Pk.nullish(),
  give: Pk,
  take: Pk,
  deadline_at: optStr,
});

export const Match = z
  .object({
    id: Pk,
    status: z.string(),
    kind: optStr,
    mode: z.object({ slug: z.string(), version: optNum }).nullish(),
    step_index: optNum,
    deadline_at: optStr,
    seconds_left: optNum,
    frozen: optBool,
    on_hold: optBool,
    held_seconds: optNum,
    turn: Turn.nullish(),
    captains: z.object({ A: Pk.nullish(), B: Pk.nullish() }).nullish(),
    players: z.array(MatchPlayer).nullish(),
    picks: z.array(MatchPick).nullish(),
    coinflip_winner: blank,
    lobby_code: blank,
    /** deadlock-api's lobby: refused (then the host enters a code), its party, whether it started. */
    api_lobby: z.object({ failed: optBool, party_id: optStr, started: optBool }).nullish(),
    winner: blank,
    votes: z.record(z.string(), z.number()).nullish(),
    sub_requests: z.array(SubRequest).nullish(),
    swap_open: optBool,
    swaps: z.array(Swap).nullish(),
    text_channel_id: Snowflake.nullish(),
    script: z.record(z.string(), z.unknown()).nullish(),
  })
  .transform((m) => {
    const players = m.players ?? [];
    const nameOf = new Map(players.map((p) => [p.id, p.name]));
    const turnIds = m.turn?.player_ids ?? [];
    return {
      id: m.id,
      status: m.status,
      kind: m.kind ?? "ranked",
      mode: m.mode ? `${m.mode.slug} v${m.mode.version ?? "?"}` : null,
      stepIndex: m.step_index ?? null,
      deadlineAt: m.deadline_at ?? null,
      secondsLeft: m.seconds_left ?? null,
      frozen: m.frozen ?? false,
      onHold: m.on_hold ?? false,
      players,
      captains: { A: m.captains?.A ?? null, B: m.captains?.B ?? null },
      picks: (m.picks ?? []).map((p) => ({
        ...p,
        label: p.champion ?? (p.playerId !== null ? (nameOf.get(p.playerId) ?? `#${p.playerId}`) : "?"),
      })),
      turn: m.turn?.action
        ? {
            action: m.turn.action,
            team: m.turn.team ?? null,
            playerIds: turnIds,
            names: turnIds.map((id) => nameOf.get(id) ?? `#${id}`),
          }
        : null,
      coinflipWinner: m.coinflip_winner,
      lobbyCode: m.lobby_code,
      apiLobby: m.api_lobby
        ? { failed: m.api_lobby.failed ?? false, partyId: m.api_lobby.party_id ?? null, started: m.api_lobby.started ?? false }
        : null,
      winner: m.winner,
      votes: Object.entries(m.votes ?? {}).map(([id, count]) => ({
        name: nameOf.get(Number(id)) ?? `#${id}`,
        count,
      })),
      subRequests: (m.sub_requests ?? []).map((s) => ({
        id: s.id,
        status: s.status,
        reason: s.reason ?? null,
        leaving: s.leaving != null ? (nameOf.get(s.leaving) ?? `#${s.leaving}`) : null,
        offers: (s.offers ?? []).length,
        pendingOffers: (s.offers ?? []).filter((o) => o.status === "pending").length,
      })),
      swapOpen: m.swap_open ?? null,
      swaps: (m.swaps ?? []).map((s) => ({
        id: s.id,
        status: s.status,
        requestedBy: s.requested_by ?? null,
        give: s.give,
        take: s.take,
        label: `${nameOf.get(s.give) ?? `#${s.give}`} ⇄ ${nameOf.get(s.take) ?? `#${s.take}`}`,
      })),
      textChannelId: m.text_channel_id ?? null,
      script: m.script ?? {},
    };
  });
export type Match = z.output<typeof Match>;

/* ------------------------------------------------------------------ control: state */

const QueueEntry = z
  .object({ position: optNum, joined_at: optStr, player: Player })
  .transform((e) => e.player);

const Community = z
  .object({
    id: Pk,
    name: z.string(),
    guild_id: Snowflake.nullish(),
    active_mode: z.object({ slug: z.string(), version: optNum }).nullish(),
  })
  .nullish();

const Recent = z.object({ id: Pk, status: z.string(), winner: blank, ended_at: optStr });

export const ControlState = z
  .object({
    community: Community,
    season: z.object({ id: Pk, number: optNum }).nullish(),
    lobby_size: optNum,
    queue: z.array(QueueEntry).nullish(),
    matches: z.array(Match).nullish(),
    recent: z.array(Recent).nullish(),
    timers: z.object({ paused_all: optBool, frozen_matches: z.array(Pk).nullish() }).nullish(),
    lobbies: z.enum(["create", "fail"]).nullish(),
    sim: z.object({ configured: optBool, reachable: optBool, url: optStr }).nullish(),
  })
  .transform((s) => ({
    community: s.community ? { id: s.community.id, name: s.community.name } : null,
    mode: s.community?.active_mode
      ? `${s.community.active_mode.slug} v${s.community.active_mode.version ?? "?"}`
      : null,
    season: s.season?.number ?? null,
    lobbySize: s.lobby_size ?? 12,
    queue: s.queue ?? [],
    matches: s.matches ?? [],
    recent: (s.recent ?? []).map((r) => ({ id: r.id, status: r.status, winner: r.winner })),
    timersPaused: s.timers?.paused_all ?? false,
    /** Whether deadlock-api makes the next lobbies, or refuses them so hosts enter a code. */
    lobbies: s.lobbies ?? null,
    simReachable: s.sim?.reachable ?? null,
  }));
export type ControlState = z.output<typeof ControlState>;

/* ------------------------------------------------------------------ control: scenarios */

/** A step is one API call: `{title?, method, path, body?}`. Kept as-is so it can be edited and re-sent. */
export const ScenarioStep = z.record(z.string(), z.unknown());
export type ScenarioStep = z.output<typeof ScenarioStep>;

const Scenario = z
  .object({ name: z.string(), description: optStr, steps: z.array(ScenarioStep).nullish() })
  .transform((s) => ({ name: s.name, description: s.description ?? "", steps: s.steps ?? [] }));
export type Scenario = z.output<typeof Scenario>;

/** `GET scenarios`: `{scenarios: [...]}`. */
export const ScenarioList = z.object({ scenarios: z.array(Scenario) }).transform((r) => r.scenarios);

/** `POST scenarios/run`: answers 200 even when a step failed; `ok` says which. */
export const ScenarioRun = z
  .object({
    ok: z.boolean(),
    ran: z.array(
      z.looseObject({ index: Pk, status: z.number(), seconds: optNum, response: z.unknown().optional() }),
    ),
    next: Pk,
    total: Pk,
  })
  .transform((r) => ({
    ok: r.ok,
    ran: r.ran.map((step) => ({ index: step.index, status: step.status, seconds: step.seconds ?? null, response: step.response })),
    next: r.next,
    total: r.total,
  }));
export type ScenarioRun = z.output<typeof ScenarioRun>;

/** Any JSON reply from an action endpoint: shown to the user, never interpreted. */
export const AnyJson = z.unknown();

/* ------------------------------------------------------------------ sim: health and state */

export const SimHealth = z
  .object({ ok: z.boolean(), version: optStr, bot_connected: optBool, sessions: optNum })
  .transform((h) => ({ ok: h.ok, version: h.version ?? null, botConnected: h.bot_connected ?? null }));
export type SimHealth = z.output<typeof SimHealth>;

const SimChannel = z
  .object({
    id: Snowflake,
    name: optStr,
    type: z.number(),
    parent_id: Snowflake.nullish(),
    position: optNum,
    voice_members: strList,
  })
  .transform((c) => ({
    id: c.id,
    name: c.name ?? c.id,
    type: c.type,
    parentId: c.parent_id ?? null,
    position: c.position ?? 0,
    voiceMembers: c.voice_members,
  }));
export type SimChannel = z.output<typeof SimChannel>;

const SimMember = z
  .object({
    id: Snowflake,
    name: z.string(),
    username: optStr,
    is_bot: optBool,
    dm_open: optBool,
    voice_channel_id: Snowflake.nullish(),
  })
  .transform((m) => ({
    id: m.id,
    name: m.name,
    isBot: m.is_bot ?? false,
    dmOpen: m.dm_open ?? true,
    voiceChannelId: m.voice_channel_id ?? null,
  }));
export type SimMember = z.output<typeof SimMember>;

export const SimState = z
  .object({
    guild: z.object({ id: Snowflake, name: optStr }),
    bot: z
      .object({ user_id: Snowflake, application_id: Snowflake.nullish(), connected: optBool })
      .nullish(),
    channels: z.array(SimChannel).nullish(),
    members: z.array(SimMember).nullish(),
  })
  .transform((s) => ({
    guildId: s.guild.id,
    guildName: s.guild.name ?? null,
    channels: s.channels ?? [],
    members: s.members ?? [],
    botUserId: s.bot?.user_id ?? null,
    botConnected: s.bot?.connected ?? null,
  }));
export type SimState = z.output<typeof SimState>;

/* ------------------------------------------------------------------ sim: messages */

const Emoji = z
  .union([z.string(), z.object({ name: optStr, id: Snowflake.nullish() }).transform((e) => e.name ?? "")])
  .nullish()
  .transform((e) => e || null);

const SelectOption = z
  .object({ label: optStr, value: z.string(), description: optStr })
  .transform((o) => ({ label: o.label ?? o.value, value: o.value, description: o.description ?? null }));

/** A flattened button or select (`components.interactive` in the sim). */
export const SimComponent = z
  .object({
    type: z.number(),
    custom_id: optStr,
    label: optStr,
    emoji: Emoji,
    style: optNum,
    url: optStr,
    disabled: optBool,
    options: z.array(SelectOption).nullish(),
    max_values: optNum,
  })
  .transform((c) => ({
    type: c.type,
    customId: c.custom_id ?? null,
    label: c.label ?? null,
    emoji: c.emoji,
    style: c.style ?? null,
    url: c.url ?? null,
    disabled: c.disabled ?? false,
    options: c.options ?? [],
    maxValues: c.max_values ?? 1,
  }));
export type SimComponent = z.output<typeof SimComponent>;

const Attachment = z
  .object({ filename: optStr, url: optStr, content_type: optStr })
  .transform((a) => ({ filename: a.filename ?? "file", url: a.url ?? null }));

const RawMessage = z.looseObject({
  author: z.object({ bot: optBool }).nullish(),
  embeds: z.array(z.looseObject({ title: optStr, description: optStr })).nullish(),
});

export const SimMessage = z
  .object({
    id: Snowflake,
    channel_id: Snowflake.nullish(),
    author_id: Snowflake.nullish(),
    author_name: optStr,
    content: optStr,
    /** Every TextDisplay's text, in order (Components V2 messages have no `content`). */
    text: z.array(z.string()).nullish(),
    flags: optNum,
    ephemeral: optBool,
    ephemeral_for: Snowflake.nullish(),
    loading: optBool,
    created_at: optStr,
    edited_at: optStr,
    components: z.array(SimComponent).nullish(),
    attachments: z.array(Attachment).nullish(),
    raw: RawMessage.nullish(),
  })
  .transform((m) => ({
    id: m.id,
    channelId: m.channel_id ?? null,
    authorId: m.author_id ?? null,
    authorName: m.author_name ?? m.author_id ?? "?",
    authorIsBot: m.raw?.author?.bot ?? false,
    content: m.content ?? "",
    text: (m.text ?? []).join("\n\n"),
    ephemeral: m.ephemeral ?? false,
    /** The only user who sees an ephemeral message, and so the only one who can click it. */
    ephemeralFor: m.ephemeral_for ?? null,
    loading: m.loading ?? false,
    createdAt: m.created_at ?? null,
    edited: Boolean(m.edited_at),
    components: m.components ?? [],
    attachments: m.attachments ?? [],
    embeds: (m.raw?.embeds ?? [])
      .map((e) => [e.title, e.description].filter(Boolean).join(" — "))
      .filter(Boolean),
    raw: m.raw ?? null,
  }));
export type SimMessage = z.output<typeof SimMessage>;

/** `GET channels/{id}/messages` and `GET users/{id}/dms`: `{messages: [...]}`, newest first. */
export const SimMessageList = z
  .object({ messages: z.array(SimMessage) })
  .transform((r) => r.messages);

/* ------------------------------------------------------------------ sim: modals and interactions */

// Discord component types that can appear in a modal.
const ACTION_ROW = 1;
const STRING_SELECT = 3;
const TEXT_INPUT = 4;
const SELECT_TYPES = new Set([3, 5, 6, 7, 8]);
const TEXT_DISPLAY = 10;
const LABEL = 18;
const FILE_UPLOAD = 19;
const PARAGRAPH = 2;

/** One input as the bot sent it (inside a Label or an ActionRow). */
const RawInput = z.looseObject({
  type: z.number(),
  custom_id: optStr,
  label: optStr,
  style: optNum,
  placeholder: optStr,
  required: optBool,
  min_length: optNum,
  max_length: optNum,
  min_values: optNum,
  max_values: optNum,
  value: optStr,
  options: z.array(SelectOption).nullish(),
});

const RawModalItem = z.looseObject({
  type: z.number(),
  label: optStr,
  description: optStr,
  content: optStr,
  component: RawInput.nullish(),
  components: z.array(RawInput).nullish(),
});

interface FieldBase {
  customId: string;
  label: string;
  description: string | null;
  required: boolean;
}

/** A modal field the panel can render: a text input, a select, a file upload, or plain text. */
export type ModalField =
  | (FieldBase & {
      kind: "text";
      multiline: boolean;
      placeholder: string | null;
      minLength: number | null;
      maxLength: number | null;
      value: string;
    })
  | (FieldBase & {
      kind: "select";
      /** Options for a string select; user, role and channel selects take typed ids. */
      options: { label: string; value: string; description: string | null }[];
      minValues: number;
      maxValues: number;
      placeholder: string | null;
    })
  | (FieldBase & { kind: "file"; minValues: number; maxValues: number })
  | { kind: "note"; text: string };

function field(input: z.output<typeof RawInput>, label: string | null, description: string | null): ModalField | null {
  const customId = input.custom_id;
  if (!customId) return null;
  const base: FieldBase = {
    customId,
    label: label ?? input.label ?? customId,
    description,
    required: input.required ?? true,
  };
  if (input.type === TEXT_INPUT) {
    return {
      ...base,
      kind: "text",
      multiline: input.style === PARAGRAPH,
      placeholder: input.placeholder ?? null,
      minLength: input.min_length ?? null,
      maxLength: input.max_length ?? null,
      value: input.value ?? "",
    };
  }
  if (input.type === FILE_UPLOAD) {
    return { ...base, kind: "file", minValues: input.min_values ?? 1, maxValues: input.max_values ?? 1 };
  }
  if (SELECT_TYPES.has(input.type)) {
    return {
      ...base,
      kind: "select",
      options: input.type === STRING_SELECT ? (input.options ?? []) : [],
      minValues: input.min_values ?? 1,
      maxValues: input.max_values ?? 1,
      placeholder: input.placeholder ?? null,
    };
  }
  return null;
}

/** The modal the bot opened (an interaction's type 9 callback), as fields to fill in. */
export const SimModal = z
  .object({ custom_id: z.string(), title: optStr, components: z.array(RawModalItem).nullish() })
  .transform((m) => {
    const fields: ModalField[] = [];
    for (const item of m.components ?? []) {
      if (item.type === LABEL && item.component) {
        const f = field(item.component, item.label ?? null, item.description ?? null);
        if (f) fields.push(f);
      } else if (item.type === ACTION_ROW) {
        for (const input of item.components ?? []) {
          const f = field(input, null, null);
          if (f) fields.push(f);
        }
      } else if (item.type === TEXT_DISPLAY && item.content) {
        fields.push({ kind: "note", text: item.content });
      }
    }
    return { customId: m.custom_id, title: m.title ?? m.custom_id, fields };
  });
export type SimModal = z.output<typeof SimModal>;

// Interaction callback types that post a reply (4 a message, 5 "thinking" then a followup).
// The others (6 and 7) edit the message the component was on, which needs no echo.
const REPLY_CALLBACKS = new Set([4, 5]);

/**
 * What `/_sim/interactions/*` answers once the bot replied: the reply the user saw, any
 * followups (where the bot puts refusals such as "It isn't your turn"), or the modal it opened.
 */
export const SimInteraction = z
  .looseObject({
    interaction_id: Snowflake,
    response: z.looseObject({ type: z.number() }).nullish(),
    message: SimMessage.nullish(),
    followups: z.array(SimMessage).nullish(),
    modal: SimModal.nullish(),
  })
  .transform((r) => ({
    interactionId: r.interaction_id,
    modal: r.modal ?? null,
    /** The bot's visible replies, in order: the reply, then each followup. */
    replies: [REPLY_CALLBACKS.has(r.response?.type ?? 0) ? r.message : null, ...(r.followups ?? [])]
      .filter((m): m is SimMessage => Boolean(m))
      .map((m) => [m.content, m.text, ...m.embeds].filter(Boolean).join("\n"))
      .filter(Boolean),
  }));
export type SimInteraction = z.output<typeof SimInteraction>;

/** `POST /_sim/attachments`: the stored file, to name in a modal's file upload by id. */
export const SimAttachment = z
  .looseObject({ id: Snowflake, filename: optStr })
  .transform((a) => ({ id: a.id, filename: a.filename ?? "file" }));
export type SimAttachment = z.output<typeof SimAttachment>;

/* ------------------------------------------------------------------ sim: event log */

/** One log entry: a REST call (`rest`), a gateway event (`gateway`) or a control call (`control`). */
export const SimEvent = z
  .looseObject({
    seq: Pk,
    time: optNum,
    kind: z.string(),
    method: optStr,
    path: optStr,
    status: optNum,
    event: optStr,
  })
  .transform((e) => {
    const summary = e.method
      ? `${e.method} ${e.path ?? ""}${e.status != null ? ` → ${e.status}` : ""}`
      : (e.event ?? e.kind);
    return {
      seq: e.seq,
      time: e.time ?? null,
      kind: e.kind,
      summary,
      status: e.status ?? null,
      raw: e,
    };
  });
export type SimEvent = z.output<typeof SimEvent>;
