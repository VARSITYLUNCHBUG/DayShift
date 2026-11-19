# discord-sim

A small fake Discord for running DayShift on your own machine and in tests. One aiohttp process
on one port (8090) serves:

- **REST v10** under `/api/v10/...`, the routes the bot calls, with Discord's JSON, status codes,
  error codes and rate-limit headers.
- **The gateway** websocket at `/gateway`: HELLO, IDENTIFY, READY, GUILD_CREATE, heartbeats,
  RESUME and every dispatch the bot reads.
- **Attachments** at `/attachments/...`, like Discord's CDN.
- **A control API** under `/_sim/...`, to look at the world, add fake users and act as them:
  click buttons, run slash commands, submit modals, chat, join voice.
- **A deadlock-api stand-in** under `/deadlock-api/v1/...`: the custom lobby routes the bot
  calls, the hero roster the admin's champion sync reads and the Steam names /link reads, so a
  dev stack never calls the real one.

The real bot runs against it unchanged. Point two settings at it and nothing else:

```bash
DISCORD_TOKEN=sim-token
DISCORD_GUILD_ID=1100000000000000001
DISCORD_API_BASE=http://127.0.0.1:8090/api/v10
DISCORD_GATEWAY_URL=ws://127.0.0.1:8090/gateway
```

`bot/client.py` applies `DISCORD_API_BASE` to `discord.http.Route.BASE` and `DISCORD_GATEWAY_URL`
to `DiscordWebSocket.DEFAULT_GATEWAY`. All state is in memory: restart the sim, or
`POST /_sim/reset`, and you're back to the seed.

It is for development and tests only. It has no real auth beyond a shared token, so never expose
its port beyond your machine.

## Run it

With uv (Python 3.13):

```bash
cd services/discord-sim
uv sync
uv run discord-sim            # listens on 0.0.0.0:8090
```

With Docker:

```bash
docker build -t discord-sim services/discord-sim
docker run --rm -p 127.0.0.1:8090:8090 discord-sim
```

The image runs as an unprivileged user and has a health check on `GET /_sim/health`. In the dev
stack, `compose.dev.yaml` builds it as the `discord-sim` service and publishes it on
`127.0.0.1:18090`.

### Settings

| Variable | Default | What it does |
|---|---|---|
| `SIM_HOST` / `SIM_PORT` | `0.0.0.0` / `8090` | Where it listens. |
| `SIM_BOT_TOKEN` | `sim-token` | The bot token it accepts (REST `Authorization: Bot ...` and IDENTIFY). `*` accepts any non-empty token. |
| `SIM_PUBLIC_URL` | empty | Base for attachment and gateway URLs. Empty means "from each request's Host header", so the bot (`http://discord-sim:8090`) and your shell (`http://127.0.0.1:18090`) both get URLs they can reach. |
| `SIM_SEED_USERS` | `0` | Fake members to create at start, `player1` to `playerN`. |
| `SIM_GUILD_NAME` / `SIM_BOT_NAME` | `Draft Sim` / `DayShift` | Display names. |
| `SIM_INTERACTION_ACK_SECONDS` | `3` | How long the bot has to answer an interaction, as on Discord. A late callback gets 10062. `0` turns it off. |
| `SIM_INTERACTION_TOKEN_SECONDS` | `900` | How long followups and `@original` edits work. After that, 10015. |
| `SIM_STRICT` | `true` | Discord's validation of message bodies: component limits, no `content` with Components V2, `attachment://` must name a file. Errors come back as 50035 with an `errors` tree. |
| `SIM_MESSAGE_CONTENT_INTENT` | `false` | Whether the app has the privileged Message Content intent. Without it, other people's messages arrive with empty content, as for the real bot. |
| `SIM_CORS_ORIGINS` | the control panel's | Comma-separated origins allowed to call `/_sim` from a browser (`http://localhost:18091`, `http://127.0.0.1:18091` and the Vite dev server on 5174). `*` allows any. |
| `SIM_LOG_SIZE` | `5000` | How many entries `/_sim/log` keeps. |

## The seeded world

The sim starts with one guild and fixed IDs, so fixtures can point at them. Everything created
later gets a real time-based snowflake (about `1571689348791795712` in late 2026), so an ID is
never reused, not across resets and not after a restart, and `created_at` in discord.py is the
real time. Every ID is clear of the stand-in players (< 1000) and the test helpers
(10,000,000 + n).

| What | ID |
|---|---|
| Owner, `sim-owner` ("Sim Owner"), the guild owner | `1100000000000000000` |
| Guild "Draft Sim", and its `@everyone` role | `1100000000000000001` |
| Bot user, `DayShift`, and the application | `1100000000000000002` |
| Role "DayShift" (managed, Administrator), held by the bot | `1100000000000000003` |
| Role "Staff" (mentionable) | `1100000000000000004` |
| Category "Text Channels" | `1100000000000000010` |
| Text channel `#general` | `1100000000000000011` |
| Category "Voice Channels" | `1100000000000000012` |
| Voice channel "General" | `1100000000000000013` |
| `SIM_SEED_USERS` members `player1`, `player2`, ... | `1100000000000000100` + n |

`GET /_sim/state` reports all of these under `seed`.

## REST v10

Every route answers with `Content-Type: application/json` exactly (discord.py won't parse JSON
with a charset), `X-RateLimit-*` headers that never reach zero, and Discord's error JSON:
`{"message": "...", "code": N}`, plus `errors` for 50035. Routes need `Authorization: Bot <token>`
except `/interactions/...`, `/webhooks/...` and `/gateway`, which Discord doesn't authenticate
either. Unknown routes are `404 {"message": "404: Not Found", "code": 0}`.

| Method and path | What it does | Errors |
|---|---|---|
| `GET /users/@me` | The bot user. | 401 bad token |
| `GET /users/{user}` | Any user. | 10013 |
| `POST /users/@me/channels` `{recipient_id}` | Opens (or reuses) the DM channel. Always works; DM settings bite on send. | 50033 bots and unknown users |
| `GET /oauth2/applications/@me`, `GET /applications/@me` | The application (sets `application_id`). | |
| `GET`, `PUT /applications/{app}/commands` | Global commands: list, bulk overwrite. A command keeps its ID while its name and type stay. | 50001 wrong app |
| `GET`, `PUT /applications/{app}/guilds/{guild}/commands` | Guild commands, the same way. The bot syncs these at start. | 10004, 50001 |
| `GET /gateway`, `GET /gateway/bot` | The gateway URL (discord.py's plain Client doesn't call these). | |
| `GET /guilds/{guild}` | The guild, without channels or members. | 10004 |
| `GET /guilds/{guild}/channels` | Every channel. | 10004 |
| `POST /guilds/{guild}/channels` | Creates a category (4), text (0) or voice (2) channel. Text names are lower-cased with dashes, as on Discord. A channel without overwrites copies its category's. Sends `CHANNEL_CREATE` before it replies. | 50035 bad name, type or parent |
| `GET /guilds/{guild}/roles` | Every role. | |
| `GET /guilds/{guild}/members/{user}` | One member. | 10007 |
| `PATCH /guilds/{guild}/members/{user}` | `channel_id` moves (or with `null` disconnects) someone in voice and sends `VOICE_STATE_UPDATE` with the member. Also `nick`, `roles`, `mute`, `deaf`. | **40032** not in voice, 10007 |
| `GET /channels/{channel}` | A guild or DM channel. | 10003 |
| `PATCH /channels/{channel}` | Name, parent, overwrites, topic, position, bitrate, user limit. Sends `CHANNEL_UPDATE`. | 10003 |
| `DELETE /channels/{channel}` | Deletes it and replies with it. Everyone in it leaves voice (`VOICE_STATE_UPDATE`), children of a category lose their parent (`CHANNEL_UPDATE`), then `CHANNEL_DELETE`. | 10003 |
| `PUT /channels/{channel}/permissions/{target}` `{allow, deny, type}` | Sets an overwrite (type 0 role, 1 member). 204, then `CHANNEL_UPDATE`. | 10011 role, 10007 member |
| `DELETE /channels/{channel}/permissions/{target}` | Removes it. 204, then `CHANNEL_UPDATE`. | 10009 |
| `POST /channels/{channel}/invites` | An invite. Reuses a matching one unless `unique`. | 50024 categories |
| `GET /invites/{code}` | An invite. | 10006 |
| `PUT /channels/{channel}/voice-status` `{status}` | Sets a voice channel's status. 204. | 50024 not voice |
| `GET /channels/{channel}/messages` | History, newest first. `limit` (1-100), `before`, `after`, `around`. Ephemeral messages never show. | 10003 |
| `POST /channels/{channel}/messages` | Sends a message, JSON or multipart (`payload_json` plus `files[N]`). Sends `MESSAGE_CREATE`. | **50007** DM to someone with DMs closed, 50006 empty, 50035 |
| `GET /channels/{channel}/messages/{message}` | One message. | 10008 |
| `PATCH /channels/{channel}/messages/{message}` | Edits the bot's own message. Only `SUPPRESS_EMBEDS` and `IS_COMPONENTS_V2` flags change, and V2 sticks. Sends `MESSAGE_UPDATE`. | 10008, 50005 someone else's |
| `DELETE /channels/{channel}/messages/{message}` | 204, then `MESSAGE_DELETE`. | 10008 |
| `POST /interactions/{id}/{token}/callback` | The bot's answer to an interaction: 4 message, 5 deferred ("thinking"), 6 deferred update, 7 update, 8 autocomplete, 9 modal. With `?with_response=1` (discord.py always sends it) the reply is the `{interaction, resource}` body discord.py parses. | 10062 unknown or later than 3 s, 40060 already answered, 50035 wrong type for the interaction |
| `POST /webhooks/{app}/{token}` | A followup. The first one after a type 5 replaces the loading message, which is `@original`; later ones are new messages. `flags: 64` makes them ephemeral. | 10015 |
| `GET`, `PATCH`, `DELETE /webhooks/{app}/{token}/messages/{id or @original}` | The interaction's own messages. After a component's type 6, `@original` is the message the button was on. | 10015, 10008 |
| `GET /attachments/{channel}/{attachment}/{filename}` | The bytes of an upload, without auth, like the CDN. `url` and `proxy_url` in payloads point here. | 404 |

Messages keep their components exactly as the bot sent them, with Discord's numeric `id` added
to each, so a click can rebuild the view (`LayoutView.from_message`). `attachment://name` media in
a Media Gallery come back as the hosted file's URL, as on Discord.

## Gateway

`GET /gateway?v=10&encoding=json&compress=zlib-stream` upgrades to the websocket discord.py
expects:

1. The sim sends HELLO (`heartbeat_interval` 41250 ms) and answers every heartbeat with an ACK.
2. IDENTIFY with the right token gets READY (`session_id`, `resume_gateway_url` pointing back at
   the sim, the bot user, the guild as unavailable, the application) and then GUILD_CREATE with
   roles, channels, voice states, and the members Discord would send: the bot and everyone in
   voice (all members only with the Guild Members intent). A bad token closes with 4004, and
   asking for Message Content without `SIM_MESSAGE_CONTENT_INTENT` closes with 4014.
3. Dispatches carry increasing `s`. A session keeps the last 2000 for two minutes after a
   disconnect, so RESUME replays what was missed and sends RESUMED. A session that can't resume
   gets INVALID_SESSION (`d: false`) and the client identifies again.
4. `compress=zlib-stream` gets binary zlib-stream frames, as from Discord. Without it, text frames.
   Only `encoding=json` is supported.

Events follow the intents a session asked for:

| Event | When | Intent |
|---|---|---|
| `CHANNEL_CREATE`, `CHANNEL_UPDATE`, `CHANNEL_DELETE` | Channel routes, overwrite changes. | Guilds |
| `GUILD_ROLE_CREATE` | `POST /_sim/roles`. | Guilds |
| `VOICE_STATE_UPDATE` (with `member`) | `/_sim/voice`, voice moves, deleted voice channels. | Guild Voice States |
| `MESSAGE_CREATE`, `MESSAGE_UPDATE`, `MESSAGE_DELETE` | Anything that posts, edits or deletes a non-ephemeral message, the bot's own included. Content is blank without Message Content, unless the bot wrote it or is mentioned. | Guild Messages, Direct Messages |
| `GUILD_MEMBER_ADD`, `GUILD_MEMBER_UPDATE`, `GUILD_MEMBER_REMOVE` | `/_sim/users` changes. | Guild Members |
| `INTERACTION_CREATE` | The `/_sim/interactions/...` routes. Sent to one connected session. | always |

Presence updates, voice joins by the bot and member requests (ops 3, 4, 8) are accepted and
ignored.

## Control API

JSON in and out, under `/_sim`. Errors are `{"error": "...", ...details}` with a fitting status:
400 bad input, 403 the fake user couldn't do that in Discord either (or `"reason": "origin"`,
below), 404 not found, 409 the
component is disabled, 503 no bot is connected to the gateway (`"reason": "no_bot"`; it may be
reconnecting, so retry), 504 the bot didn't answer. Users, channels and roles can be given by ID or by name
(`"player3"`, `"queue"`, `"Staff"`).

A call that changes anything under `/_sim` or `/attachments` (any method but GET, HEAD and
OPTIONS) from a browser page on another site gets 403 `"reason": "origin"`: only
`SIM_CORS_ORIGINS`, loopback pages and pages on the host being called get through. Clients that
send no `Origin` header (the bot, web, tests, curl) pass. The examples assume the dev stack's
port:

```bash
SIM=http://127.0.0.1:18090
```

### Look around

```bash
curl -s $SIM/_sim/health      # {"ok": true, "bot_connected": true, "sessions": 1, ...}
curl -s $SIM/_sim/state       # guild, bot ids, seed ids, roles, channels, members, commands
curl -s $SIM/_sim/users       # every user, with voice channel, roles and dm_open
curl -s $SIM/_sim/commands    # the slash commands the bot synced
```

`GET /_sim/channels/{id or name}/messages?limit=50&include_ephemeral=true` and
`GET /_sim/users/{id}/dms?limit=50` list messages newest first, each with its `text`
(TextDisplay contents), `components` flattened to
`{custom_id, type, label, emoji, style, url, disabled, options[], min_values, max_values}`,
`attachments`, `mentions`, `ephemeral_for`, `interaction` (who triggered it) and the `raw` Discord
payload:

```bash
curl -s "$SIM/_sim/channels/queue/messages?limit=1"
curl -s "$SIM/_sim/users/1571689348791795713/dms"
```

### Reset

```bash
curl -s -X POST $SIM/_sim/reset
```

Back to the seed. Faults and pending interactions are cleared, and connected clients get a
RECONNECT; their resume is refused, so they identify again and get a fresh READY and GUILD_CREATE.
Synced slash commands stay, because the bot syncs them only once at start-up. discord.py waits
5 seconds before it identifies again, so poll `/_sim/health` until `bot_connected` is `true`
before you click or run commands.

### Users, roles, voice

```bash
# Twelve members named player1..player12 with DMs open; `names` instead of `count` names them.
curl -s -X POST $SIM/_sim/users -H 'Content-Type: application/json' \
  -d '{"count": 12, "name_prefix": "player", "dm_open": true}'

# Close someone's DMs (the bot then gets 50007), rename, give roles.
curl -s -X PATCH $SIM/_sim/users/player3 -H 'Content-Type: application/json' \
  -d '{"dm_open": false, "name": "Haze main", "roles": ["Staff"]}'

curl -s -X DELETE $SIM/_sim/users/player3

# A new role, for permission tests.
curl -s -X POST $SIM/_sim/roles -H 'Content-Type: application/json' \
  -d '{"name": "Match Staff", "mentionable": true}'

# A channel made by a server admin rather than the bot: Discord's channel JSON
# ({name, type?, parent_id?, permission_overwrites?, topic?}); parent_id may be a name.
# The bot sees CHANNEL_CREATE.
curl -s -X POST $SIM/_sim/channels -H 'Content-Type: application/json' \
  -d '{"name": "scrims", "type": 0, "parent_id": "Text Channels"}'

# Join, move or leave (null) voice as a user. The bot sees VOICE_STATE_UPDATE.
curl -s -X POST $SIM/_sim/voice -H 'Content-Type: application/json' \
  -d '{"user_id": "player1", "channel_id": "Waiting Room"}'
```

`POST /_sim/users` also takes `roles` and `voice_channel_id`, and answers
`{"users": [...]}` with status 201.

### Act as a user

Each of these sends `INTERACTION_CREATE` and waits (5 s by default, `timeout` up to 30) for the
bot's callback. The answer is
`{interaction_id, type, response: {type, data}, settled, message, followups, modal, choices}`:
`message` is the reply the user saw. After a deferred reply (type 5) it waits for the followup
that replaces "thinking"; after a deferred update (type 6) it returns at once, and the bot's edits
follow. The bot often defers a click and then sends a refusal ("It isn't your turn") as an
ephemeral followup: pass `"followup_wait": 1` to wait up to that long for one, and it comes back
in `followups`.
A fake user can only click in channels they can see, as in Discord; pass `"force": true` to skip
that check. `GET /_sim/interactions/{interaction_id}` answers the same shape for an interaction
started earlier, as it stands now: whether it settled, and the followups since (where the
refusal of a deferred click lands). 404 once it has expired.

```bash
# Press the newest enabled button labelled "Join" in #queue (case and emoji ignored).
# 404 lists the labels it could find.
curl -s -X POST $SIM/_sim/interactions/click -H 'Content-Type: application/json' \
  -d '{"user_id": "player1", "channel_id": "queue", "label": "Join"}'

# The same in a DM the bot sent (the ready check).
curl -s -X POST $SIM/_sim/interactions/click -H 'Content-Type: application/json' \
  -d '{"user_id": "player1", "dm_user_id": "player1", "label": "Ready"}'

# An exact component, and select values (option values or labels; users by ID or name).
curl -s -X POST $SIM/_sim/interactions/component -H 'Content-Type: application/json' \
  -d '{"user_id": "player1", "message_id": "1571689348791795808",
       "custom_id": "dl:v1s:pick_player:1:", "values": ["player7"]}'

# A slash command, subcommands in the name. The default channel is #general.
curl -s -X POST $SIM/_sim/interactions/command -H 'Content-Type: application/json' \
  -d '{"user_id": "1100000000000000000", "name": "setup"}'
curl -s -X POST $SIM/_sim/interactions/command -H 'Content-Type: application/json' \
  -d '{"user_id": "sim-owner", "name": "permissions grant", "options": {"role": "Staff", "area": "Match control"}}'

# Autocomplete: the bot's choices for a half-typed option.
curl -s -X POST $SIM/_sim/interactions/autocomplete -H 'Content-Type: application/json' \
  -d '{"user_id": "sim-owner", "name": "ping", "options": {"message": "hi", "name": "sc"}, "focused": "name"}'

# Submit the modal the bot last opened for the user. Fields by custom_id or label; a file
# upload without data_base64 is a 1x1 PNG, enough for a placeholder screenshot.
curl -s -X POST $SIM/_sim/interactions/modal -H 'Content-Type: application/json' \
  -d '{"user_id": "player1", "values": {"Winner": "Team A"},
       "attachments": {"Screenshot": [{"filename": "scoreboard.png"}]}}'

# Chat in a channel (the bot sees MESSAGE_CREATE, without content), with an optional file.
curl -s -X POST $SIM/_sim/messages -H 'Content-Type: application/json' \
  -d '{"user_id": "player1", "channel_id": "match-1", "content": "gg",
       "attachments": [{"filename": "shot.png", "data_base64": "iVBORw0KGgo..."}]}'
```

Slash command options are checked against the synced schema: unknown or missing options,
choices, ranges and channel types give a 400. Attachment options take an uploaded attachment's
ID or an inline `{filename, data_base64?}`. A command with `default_member_permissions` is refused
(403) for a user without them, as Discord hides it.

### Files

```bash
# Upload ahead of a command or modal (JSON with base64, or multipart field "file").
curl -s -X POST $SIM/_sim/attachments -F file=@scoreboard.png
# Download any attachment through the control prefix (handy behind the panel's proxy).
curl -s $SIM/_sim/attachments/1571689348791795835 -o out.png
```

### Log and events

Every REST call the bot makes, every gateway dispatch and every control action goes in a ring
buffer:

```bash
curl -s "$SIM/_sim/log?since=0&limit=100&kind=rest"   # {"entries": [...], "last_seq": N}
curl -N "$SIM/_sim/events"                            # Server-Sent Events, live
```

Each entry has `seq`, `time` and `kind` (`rest`, `gateway`, `control` or `deadlock_api`).
REST entries carry `method`, `path`, `query`, `status`, the request `body` and any `error`;
gateway entries the
`event` and its `data`. The event stream sends `id: <seq>`, `event: <kind>` and `data: <entry>`,
resumes from `Last-Event-ID` (or `?since=`), and sends a comment every 15 s to stay open.

### deadlock-api

The app calls deadlock-api.com for each match's custom lobby, the hero roster and Steam names.
Point the app's
`DEADLOCK_API_BASE` at `<sim>/deadlock-api` (the app does that by itself when `DISCORD_SIM_URL`
is set and `DEADLOCK_API_BASE` isn't) and the sim answers instead, in deadlock-api's shapes:

| Route | Answer |
|---|---|
| `POST /deadlock-api/v1/matches/custom/create` | `{party_id, party_code, created}` with a made-up 6-character code, or 503 when lobbies are set to fail |
| `POST /deadlock-api/v1/matches/custom/{party_id}/start` | `{"ok": true}`, or 404 for an unknown party |
| `GET /deadlock-api/v1/matches/custom/{party_id}/match-id`, `GET /deadlock-api/v1/matches/{id}/metadata` | Always 404: nothing is ever played, so the bot treats it as not known yet |
| `GET /deadlock-api/v1/assets/heroes?only_active=true` | The hero roster as deadlock-api's list of heroes (`id`, `name`, `player_selectable`, `disabled`, `images`, ...): the repo's seed roster, `presets/champions.yaml`, so the admin's champion sync finds nothing to change. `only_active=true` leaves out heroes nobody can pick |
| `GET /deadlock-api/v1/players/steam?account_ids=1,2` | A list of `{account_id, personaname, profileurl, ...}`: every account is named `steam_<id>` unless set otherwise; 400 for a bad id list |

```bash
curl -s $SIM/_sim/deadlock-api        # {"lobby": "create", "lobbies": [...]}: the lobbies made
# The next lobbies fail, so the bot falls back to asking the host for a lobby code.
curl -s -X PUT $SIM/_sim/deadlock-api -H 'Content-Type: application/json' -d '{"lobby": "fail"}'
# A renamed hero and a new one, for the admin's champion sync to find (replaces the roster).
curl -s -X PUT $SIM/_sim/deadlock-api -H 'Content-Type: application/json'   -d '{"heroes": [{"id": 1, "name": "Infernus"}, {"id": 2, "name": "Seven II"}, {"id": 99, "name": "New"}]}'
# Name a Steam account, and make another one unknown (merged into the names set so far).
curl -s -X PUT $SIM/_sim/deadlock-api -H 'Content-Type: application/json'   -d '{"steam_names": {"123": "Ash", "456": null}}'
```

Each hero is `{id, name, player_selectable?, disabled?}`. A bad key or value answers 400 and changes
nothing. `POST /_sim/reset` goes back to `create`, the seed roster and no Steam names. Each call is logged with kind `deadlock_api`.

### Faults

Make the next matching REST calls fail, to exercise the bot's retries and error paths:

```bash
# The next message send is rate limited (429 with Via and retry_after, as discord.py needs).
curl -s -X POST $SIM/_sim/faults -H 'Content-Type: application/json' \
  -d '{"path": "/messages$", "method": "POST", "status": 429, "retry_after": 1.5}'
# Three 500s on channel creation, then normal service. `times: -1` fails until cleared.
curl -s -X POST $SIM/_sim/faults -H 'Content-Type: application/json' \
  -d '{"path": "/guilds/\\d+/channels$", "status": 500, "times": 3}'
curl -s $SIM/_sim/faults
curl -s -X DELETE $SIM/_sim/faults
```

`path` is a regular expression searched in the request path; `code` and `message` set the error
body.

## Tests

```bash
cd services/discord-sim
uv run pytest           # unit tests, plus a real discord.py 2.7.1 client against the sim
uv run ruff check . && uv run ruff format --check . && uv run mypy
```

`tests/test_discordpy.py` starts the sim on a random port and connects a real `discord.Client`
with the bot's intents, pointed at it the way `bot/client.py` does. It covers READY and
GUILD_CREATE, a Components V2 LayoutView clicked through `/_sim/interactions/click` (reply,
deferred reply, deferred update with an `@original` edit, a modal), a slash command, the 50007 DM,
40032 and voice moves, `CHANNEL_CREATE` reaching the cache, a file upload served from its
attachment URL, chat without content, and a reset that reconnects the client.

## What it doesn't do

- One guild, one bot. No sharding, threads, reactions, pins, bans, webhooks the bot creates,
  stickers, emojis, presences, or voice connections (the bot never joins voice).
- Rate limits are reported but never enforced; use a fault to get a 429.
- `GUILD_MEMBERS_CHUNK` isn't sent; the bot doesn't ask for it.
