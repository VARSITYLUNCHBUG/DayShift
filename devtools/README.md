# devtools: the dev control API

A local-only Django app that lets you drive the league by hand: make fake players, give them
ratings, fill the queue, play any phase of a match as its players, and freeze, fire or resume
its timers. The control panel (`services/control-panel/`) is a UI over this API, and the
scenarios in `devtools/scenarios/` are scripts of the same calls.

It is loaded only with `DEBUG=true` and `DEV_CONTROL=true`. Settings then add `devtools` to
`INSTALLED_APPS` and switch `ROOT_URLCONF` to `config.urls_dev`, which mounts it at
`/_control/`. It has no authentication: never turn it on anywhere but your own machine.

It talks to the league through `league.services` (the same calls the bot makes), and to the
Discord simulator through its control API at `DISCORD_SIM_URL` (`devtools/sim_client.py`).
Without a simulator everything still works except `via: "discord"`; fake players then get
Discord IDs from a local range instead of from the simulator.

## Commands

```
manage.py dev_seed              # load fixtures/dev/*.json on an empty database, then the extras
manage.py dev_seed --reload     # load the fixtures again over what is there
manage.py dev_scenario --list   # the scenarios in devtools/scenarios/
manage.py dev_scenario full_match
manage.py dev_scenario full_match --from 2 --count 3
```

They exist only with `DEV_CONTROL=true` (and `DEBUG=true`), like the API.

`dev_seed` runs after `migrate` and `load_presets`. It is safe to run again: the fixtures load
only into an empty database (or with `--reload`), and the extras are idempotent:

1. Lay the simulator's guild out the way `/setup` does, without anyone running `/setup`: the
   `PUGS` role, the `Deadlock` category, the `Waiting Room` voice channel and the queue, results
   and leaderboard channels for the PUG role, `scoreboard-archive` for match staff and
   `staff-alerts` for all staff, with `/setup`'s permission overwrites. It makes only what the
   community doesn't already have in the simulator, wires the ids in with
   `community.save_wiring`, and queues the queue panel and the leaderboard for the bot to post.
   A `/setup` run later keeps them and fills in only what is missing. Without these channels
   there is no queue panel, and no report gets past the archive.
2. Make sure each fixture player is a simulator member with the fixture's name and the PUG role.
   The fixture IDs are the members the simulator seeds with `SIM_SEED_USERS=14`; a player who
   isn't a member is created there, and the player's Discord ID is updated to the new member's.
   Every fake player the API makes later gets the PUG role too.
3. Seed each fixture player's rating through the ledger (`ratings.seed_player`), once.
4. Let the fixture players captain (a `CaptainOverride` of `allow`), once, so a lobby of fresh
   players still holds a real captain vote.

It prints what it did, such as `Channels made: Waiting Room, queue, results, leaderboard,
scoreboard-archive, staff-alerts` and `Channels and PUG role: wired`. Without a simulator it
loads the fixtures and seeds the ratings, and says the channels aren't wired.

## Conventions

- Base URL: `/_control/api/`. Request and response bodies are JSON. No CSRF token or login.
  Instead, a call that changes anything (any method but GET, HEAD and OPTIONS) is refused with
  403 `cross_origin` when it carries an `Origin` header from another site: only pages on
  localhost, 127.0.0.1, `::1` or the host being called get through, so a web page you visit can't
  reset your database. Clients that send no `Origin` (curl, httpx, the e2e suite) aren't
  browsers, and pass.
- Players are named by `Player.id` (`id` below), never by Discord ID. Discord IDs (and every
  other snowflake: guild, channel, message) are sent as **strings**, because they don't fit in
  a JavaScript number. Inputs accept strings or numbers.
- A match ID in a path can be `latest`: the newest match.
- Times are ISO 8601 in UTC. `seconds_left` is computed when the response is built.
- Errors have a status and a body like this. The message is safe to show.

  ```json
  {"error": {"code": "invalid_action", "message": "You are not in this match."}}
  ```

  | Status | `code` | When |
  |---|---|---|
  | 400 | `bad_request` | The body is malformed or a field is wrong |
  | 403 | `not_allowed` | The league refused: that player may not do this |
  | 403 | `cross_origin` | A browser page on another site tried to change dev state |
  | 404 | `not_found` | No such player, match, scenario or route |
  | 409 | `invalid_action`, `stale_action` | The league refused: a rule, or the match moved on |
  | 502 | `sim_error` | The simulator answered with an error, or isn't reachable |
  | 503 | `bot_offline` | No bot is connected to the simulator's gateway (a press waits up to 10 s for it to reconnect first) |
  | 503 | `busy` | A reset couldn't get the league tables from the bot in 30 s |
  | 504 | `timeout` | The bot didn't act on a simulated click in time |
  | 500 | `server_error` | A bug: the web process logs the traceback |

- `via` picks how a player's action is made. `"service"` calls `league.services` directly.
  `"discord"` presses the real component as that fake user, through the simulator
  (`/_sim/interactions/component`), so the bot's own handlers run. Components are found by the
  bot's `custom_id` (`dl:v1:<action>:<match>:<arg>`), never by label, wherever the bot put them:
  the match channel, the player's DMs (sub offers), or `#staff-alerts` (the dispute card,
  pressed as the guild owner). A form the press opens is filled in and sent with
  `/_sim/interactions/modal`, with a placeholder screenshot in any file upload. The API waits up
  to 10 seconds for the bot to post the component, presses again if the bot has just replaced
  the message, then waits for the match to change. A refusal from the bot answers 409 with the
  bot's own words; a bot that never acts answers 504, naming the match, its status and the
  enabled buttons there. The default is `"discord"` when the simulator is reachable, otherwise
  `"service"`. Every action goes through the bot except `void` (staff do that with a command),
  which always uses the service; the action log says which was used.
- Timers. Every request first re-freezes frozen matches whose deadline an action just reset
  (see `pause` below), so a frozen match stays frozen whatever acts on it, the API or the bot.
  Something that sets a deadline between two requests, such as a click in the simulator by
  hand, is only caught by the next request.

## Read models

### Player

```json
{
  "id": 7,
  "discord_user_id": "1100000000000010007",
  "name": "Dev 7",
  "rating": 1200,
  "mu": "54.999999",
  "sigma": "8.333333",
  "games": 0,
  "queued": true,
  "queue_position": 3,
  "match_id": null,
  "dm_open": true,
  "sim_user": true,
  "picks": {"prefer": ["haze", "wraith"], "ban": ["seven"]}
}
```

`rating` is the shown rating in the open season (`null` before any is seeded). `match_id` is the
live match they're in. `dm_open` is what the API last set (`null` if never). `sim_user` says the
Discord ID came from the simulator.

### Match

```json
{
  "id": 1,
  "status": "player_draft",
  "kind": "ranked",
  "mode": {"slug": "draft_3ban", "version": 1},
  "version": 31,
  "step_index": 2,
  "deadline_at": "2026-11-16T21:04:05Z",
  "seconds_left": 41,
  "frozen": false,
  "on_hold": false,
  "held_seconds": null,
  "turn": {"action": "player_pick", "team": "B", "player_ids": [4], "step": 2},
  "captains": {"A": 1, "B": 4},
  "teams": {"A": [1, 9], "B": [4]},
  "players": [
    {"id": 1, "discord_user_id": "1100000000000000100", "name": "Ash", "rating": 1500,
     "team": "A", "is_captain": true, "ready": true, "checked_in": true,
     "missed_checkin": false, "active": true, "removed_reason": ""}
  ],
  "picks": [
    {"step": 0, "action": "player_pick", "team": "A", "player_id": 9, "champion": null,
     "source": "user", "random": false},
    {"step": 10, "action": "ban", "team": "B", "player_id": null,
     "champion": {"id": 1, "slug": "infernus", "name": "Infernus"}, "source": "timeout",
     "random": true}
  ],
  "coinflip_winner": "",
  "hidden_king_team": "",
  "champion_first_pick": "",
  "lobby_code": "",
  "lobby_code_host": null,
  "api_lobby": {"failed": false, "party_id": null, "started": false},
  "winner": "",
  "votes": {"1": 3, "4": 2},
  "sub_requests": [
    {"id": 2, "status": "open", "reason": "sub_out", "leaving": 6, "requested_by": 6,
     "deadline_at": "...", "name_until": "...",
     "offers": [{"id": 3, "player_id": 13, "status": "pending", "deadline_at": "..."}]}
  ],
  "swap_open": false,
  "swaps": [
    {"id": 1, "status": "accepted", "requested_by": 1, "give": 9, "take": 5,
     "deadline_at": "...", "resolved_by": 4}
  ],
  "text_channel_id": "1100000000000000207",
  "script": {"draft": [9, 3], "champions": [], "captain_votes": {}},
  "created_at": "...",
  "ended_at": null
}
```

`turn.action` is who must act now: `ready`, `vote`, `checkin` (the captains),
`player_pick`, `coinflip`, `ban`, `pick`, `api_lobby` (deadlock-api is making the lobby),
`lobby_code` (it couldn't: the host enters one), `start_match`, `report`, `confirm`, `resolve`
(staff), or `null` once the match is over. `turn.player_ids` are the players who still have to
do it. `step` (draft phases only) is `match.step_index`. When `frozen` is true, `seconds_left` is
the time the timer will have when it resumes, and `deadline_at` is the real (pushed out)
deadline. `swap_open` says a captain can offer a swap now; a pending swap's answer clock is
frozen and fired like the others.

## Endpoints

### `GET /_control/api/`

Lists every route: `{"name": "devtools", "routes": [{"method": "GET", "path": "state", "summary": "..."}]}`.

### `GET state`

```json
{
  "community": {"id": 1, "guild_id": "1100000000000000001", "name": "Dev League",
                "active_mode": {"id": 2, "slug": "draft_3ban", "version": 1},
                "channels": {"queue": "...", "waiting_room": "...", "results": "...",
                             "archive": "...", "match_category": "...", "staff": "...",
                             "leaderboard": "..."},
                "pug_role_id": "...",
                "settings": {"max_concurrent_matches": 12, "auto_captain": false,
                             "score_ocr": "off", "api_results": false,
                             "lobby_region": "", "interim_points": false}},
  "season": {"id": 1, "number": 1},
  "lobby_size": 12,
  "queue": [{"position": 1, "joined_at": "...", "player": {"id": 1, "name": "Dev 1", "...": "..."}}],
  "matches": [{"...": "live matches, as the Match read model"}],
  "recent": [{"id": 3, "status": "completed", "winner": "A", "ended_at": "..."}],
  "timers": {"paused_all": false, "frozen_matches": [1]},
  "lobbies": "create",
  "sim": {"configured": true, "reachable": true, "url": "http://discord-sim:8090"}
}
```

`community` is `null` before `dev_seed` (then most other calls answer 409). `settings` are the
community's runtime settings, which the admin changes. `lobbies` is whether deadlock-api makes
the next lobbies (see `PUT lobbies`).

### `POST reset`

Body: `{"fixture": "dev_default"}` (default) or `{"fixture": "none"}`.

First stops the bot's pending effects and waits (up to 5 s) for the ones it is running, so none
writes into the emptied tables. Then it locks every league table at once, so nothing can happen
between that and the wipe: no deadline fires, no effect is claimed. Each try at the locks gives
up after 0.5 s and goes again, so a reset never deadlocks with the bot; if the
bot claimed an effect in between, the reset goes round again. After 30 s of that it answers 503
(`busy`) and changes nothing. Holding the locks, it resets the simulator (`POST /_sim/reset`),
empties every league table except champions and draft modes (ids restart at 1, except outbox
effect ids, which keep counting), drops all devtools state, and runs `dev_seed` (with `"none"`:
only the community and season, no players), which lays the guild out again. Logins in `/admin`
survive: they're players, so the reset puts each one back, merged into the fixture player with the
same Discord ID if there is one. The bot reconnects to the reset simulator by itself
within a few seconds; `GET /_sim/health` says when (`bot_connected`).

Response: `{"ok": true, "seed": {"fixtures_loaded": true, "players": 14, "ratings_seeded": 14,
"captains_allowed": 14, "sim": true, "guild_id": "1100000000000000001", "channels_created":
["Waiting Room", "queue", ...], "channels_wired": true}, "state": {...}}`.

### `GET players`

`{"players": [Player, ...]}`, ordered by id. Retired players (see DELETE) are left out; add
`?all=1` to include them.

### `POST players`

```json
{"count": 4, "rating": {"min": 800, "max": 1600}, "name_prefix": "Dev", "join_queue": true,
 "dm_open": true}
```

All optional except `count` (1 to 50). `rating` is a number or `{min, max}` (spread evenly
across the new players; 0 is the floor). Creates the users in the simulator (or local IDs without
one), the `Player` rows, seeds each rating through the ledger, and joins them to the queue in
order. Joining the 12th pops a lobby.

Response: `{"players": [Player, ...], "match_id": 1}` (`match_id` is set when a lobby popped).

### `PATCH players/{id}`

`{"rating": 1350, "name": "Big Dev", "dm_open": false}`, any subset. `rating` re-seeds through the
ledger (sigma goes back to the season's start). `name` and `dm_open` are also sent to the
simulator. Response: Player.

### `DELETE players/{id}`

Takes them out of the queue and deletes their simulator user. A player with no history is
deleted (`{"deleted": "hard"}`); one with ratings or matches can't be (the ledger is
append-only), so they're retired instead (`{"deleted": "retired"}`): hidden from the list, and
never picked by `queue/join {count}` or the autopilot's sub actions. A player in a live match is
refused (409).

### `PUT players/{id}/picks`

`{"prefer": ["haze", "wraith"], "ban": ["seven"]}`, champion slugs (or ids). When this player's
team is on turn in the champion draft, the autopilot picks the first available of the team's
`prefer` lists (captain first), and bans the first available of their `ban` lists. Response:
Player.

### `POST queue/join`

`{"player_ids": [1, 2, 3]}`, or `{"count": 5}` (the first free players by id, not queued, not in
a live match, not retired), and an optional `via`. With `"discord"` (the default when the
simulator is up) each player presses Join on the queue panel. Response:
`{"queue": [...], "match_id": null}` (`match_id` is set when a lobby popped).

### `POST queue/leave`

`{"player_ids": [3]}`, and an optional `via` (Leave on the queue panel). Response:
`{"queue": [...]}`.

`POST players` with `join_queue` and `POST queue/fill` always join through the service.

### `POST queue/fill`

`{"rating": 1000}` (optional, as in `POST players`). Creates as many new fake players as the
queue needs to reach the lobby size and joins them. Response:
`{"players": [...new], "queue": [...], "match_id": 1}`.

### `GET matches/{id}`

The Match read model.

### `PUT matches/{id}/script`

```json
{
  "draft": [9, 3, 11],
  "champions": [{"step": 0, "slug": "infernus"}, {"step": 4, "team": "A", "slug": "haze"}],
  "captain_votes": {"*": [1, 4], "7": [2, 4]},
  "coinflip": "archmother",
  "lobby_code": "DEV-1",
  "winner": "B"
}
```

Every key is optional; the script replaces the previous one. The autopilot follows it before
its defaults:

| Key | Meaning | Default |
|---|---|---|
| `draft` | player ids in the order captains pick them (the first one still free is picked) | highest skill (mu), then lowest id |
| `champions` | per champion step (0 is the first ban or pick of the champion draft; `team` is optional and only checked): the champion to ban or pick | the team's `prefer`/`ban` lists, then a seeded random champion |
| `captain_votes` | voter id (or `*` for everyone) to the 1 or 2 candidates | the two highest-skill eligible players |
| `coinflip` | the side the coinflip winner chooses: `hidden_king` or `archmother` | `hidden_king` |
| `lobby_code` | the code the host enters | `DEV{match id}` |
| `winner` | `A` or `B`: who the captains report, and how a dispute is resolved | `A` |

Response: the Match read model.

### `POST matches/{id}/advance`

`{"until": "in_progress", "via": "service"}`, both optional.

Without `until`, completes the current phase: every player who still has to act does, one step
at a time, until the status changes (a draft phase is all of its steps). With `until`, keeps
going phase by phase until the match reaches that status (`captain_phase`, `captain_checkin`,
`player_draft`, `coinflip`, `champion_draft`, `lobby_code`, `in_progress`,
`awaiting_confirmation`, or `completed`). A status the match has already reached or passed is a
200 that does nothing: the bot can move on by itself, as when deadlock-api's lobby takes the
match straight past `lobby_code`. A disputed match is resolved with the script's `winner`. A
match on hold (an open sub) is refused (409) until the sub is settled. In the lobby step,
`via: "service"` accepts or fails deadlock-api's lobby as `PUT lobbies` says; `via: "discord"`
waits for the bot to get it from the simulator's stand-in.

Response, with each phase's time and each action's:

```json
{
  "match": {"...": "Match"},
  "from": "ready_check",
  "to": "player_draft",
  "phases": [{"status": "ready_check", "seconds": 2.06, "actions": 12},
             {"status": "captain_checkin", "seconds": 0.42, "actions": 2}],
  "actions": [
    {"player_id": 1, "action": "ready", "args": {}, "via": "discord", "seconds": 0.17},
    {"player_id": 1, "action": "checkin", "args": {}, "via": "discord", "seconds": 0.2}
  ]
}
```

### `POST matches/{id}/act`

`{"player_id": "captain:A", "action": "report", "args": {"winner": "B"}, "via": "service"}`

One action as one player. `player_id` is a player id or a selector (below); left out, it is
whoever's turn it is. Send `player_ids` (a list of ids or selectors) instead to make the same
action as several players in turn, such as ten of twelve readying up. `args` per action (all
optional):

| `action` | `args` | Service call (with `via: "service"`) |
|---|---|---|
| `ready` | | `lobby.mark_ready` |
| `vote` | `candidates: [ids]` | `lobby.cast_captain_votes` |
| `checkin` | | `lobby.check_in` (a captain's **I'm here**) |
| `pick` | player draft: `player_id`; champion draft: `champion` (slug or id) | `draft.pick_player` / `draft.choose_champion` |
| `ban` | `champion` | `draft.choose_champion` |
| `coinflip` | `choice`: `hidden_king` or `archmother` | `draft.choose_coinflip` |
| `swap` | `give`, `take`: player refs (default: the captain's first non-captain, and the other team's) | `swaps.propose` (default actor: captain A) |
| `accept_swap`, `decline_swap` | `swap_id` (default: the pending one) | `swaps.answer` (default actor: the other captain) |
| `api_lobby` | `create` (default: as `PUT lobbies` says) | `draft.accept_api_lobby` / `draft.api_lobby_failed` (nobody in the match: deadlock-api) |
| `lobby_code` | `code` | `draft.submit_lobby_code` |
| `start_match` | | `draft.mark_api_started` (**Start match**, default actor: captain A) |
| `report` | `winner` | `results.submit_report` with a placeholder screenshot |
| `confirm` | | `results.confirm` |
| `dispute` | `note` | `results.dispute` |
| `resolve` | `outcome`: `A`, `B` or `void` | `results.resolve_dispute` (staff: through Discord, the dispute card pressed as the guild owner) |
| `void` | `reason` | `lobby.staff_void` (always service) |
| `request_sub` | `leaving`: player ref (default: the actor) | `subs.request_sub_out` |
| `approve_sub` | `request_id`, `approve` (default true) | `subs.answer_sub_out` |
| `cancel_sub` | `request_id` | `subs.cancel_sub` |
| `invite_sub` | `request_id`, `invitee`: player ref | `subs.invite_sub` |
| `offer_queue` | `request_id` | `subs.offer_to_queue` |
| `accept_sub` | `offer_id` | `subs.answer_offer(accept=True)` |
| `decline_sub` | `offer_id` | `subs.answer_offer(accept=False)` |

`request_id` defaults to the match's newest unresolved sub request, `offer_id` to the actor's
pending offer for this match.

Player selectors: `captain:A`, `captain:B`, `acting` (whose turn it is), `host` (lobby code
host), `other_captain` (the captain who hasn't reported yet), `participant:N` (the Nth active
participant by id, from 1), `non_captain:N`, `queued:N` (the Nth in the queue), `offered`
(the player of the newest pending sub offer), `requester` (whoever asked for the newest sub).
Before it picks `offered`, an open seat nobody has been asked for yet while someone waits in the
queue is offered to them first: the deadline loop's sub pass (`subs.tick`) runs then, as it
would within a second anyway, so a step that acts as `offered` right after a player joins doesn't
race the bot's own pass.

Response: `{"match": Match, "actions": [{"player_id": 1, "action": "ready", "args": {}, "via": "service"}]}`.

### `POST matches/{id}/fire`

Fires the match's current deadline now, exactly as the bot's deadline loop would when it runs
out (`deadlines.fire_match_deadline`): a missed ready check removes the unready players and
penalises them, a draft step auto-picks, and so on. One fire is one timeout step. On a match on
hold, it fires the open sub's timer instead (`subs.tick`). Works the same on a frozen match: the
new deadline is frozen again straight away.

Response: `{"match": Match, "fired": true}`.

### `POST matches/{id}/pause`, `POST matches/{id}/resume`

Freezes the match's timers, or restores them. Pausing saves the seconds left on the match's
deadline (and on its open sub requests, sub offers and early-leave reports), and pushes those
deadlines ten years out, so neither the bot's deadline loop nor `extend_past_due` touches them.
`held_seconds` is never used, so every action still works. Each action that sets a fresh
deadline on a frozen match is frozen again with its full time. Resuming sets each deadline to
now plus the seconds saved. Response: Match.

### `POST timers/pause`, `POST timers/resume`

The same for every live match, including ones that start while paused. Response:
`{"paused_all": true, "frozen_matches": [1, 2]}`.

### `PUT lobbies`

`{"lobby": "create"}` (the default) or `{"lobby": "fail"}`: whether deadlock-api makes the next
custom lobbies. It sets the simulator's deadlock-api stand-in (`PUT /_sim/deadlock-api`) and the
service path alike, so `fail` sends the next lobby down the host's lobby code fallback. A match
already in its lobby step keeps the answer it got. A reset goes back to `create`. Response:
`{"lobbies": "fail"}`.

### `GET scenarios`

```json
{"scenarios": [{"name": "full_match", "description": "...", "steps": [{"...": "..."}]}]}
```

### `POST scenarios/run`

`{"name": "full_match"}`, or `{"steps": [...]}`, plus optional `"from": 0` and `"count": 1` to run
only some steps (the panel's step-through mode runs one at a time). Each step is one API call:

```json
{"title": "Everyone readies up", "method": "POST", "path": "matches/latest/advance",
 "body": {"via": "service"}}
```

Steps run in order and stop at the first error. Response:

```json
{
  "ok": true,
  "ran": [{"index": 0, "title": "...", "method": "POST", "path": "reset", "body": {},
           "status": 200, "seconds": 0.66, "response": {"...": "..."}}],
  "next": 5,
  "total": 9
}
```

A failed step has its error status and body, `ok` is false, and `next` is that step's index.

## Scenarios

| Name | What it shows |
|---|---|
| `full_match` | A whole ranked match, from an empty queue to the posted result, one phase per step |
| `ready_check_miss` | Two players miss the ready check: they get a cooldown, and their seats are offered to the queue and filled |
| `checkin_miss` | One captain misses the check-in: the next player in the vote takes over, and the draft starts |
| `sub_mid_draft` | A player subs out during the player draft, and the next player in the queue takes the spot |
| `swap_players` | After the player draft, one captain offers a swap and the other accepts |
| `lobby_code_fallback` | deadlock-api can't make the lobby, so the host creates one and enters its code |
| `dispute_result` | The captains disagree on the result, and staff settle the dispute |
| `restart_after_unfilled_sub` | Nobody takes a seat left during the draft, so the lobby restarts with the same players and a fresh captain vote |

Steps without a `via` use the default, so a scenario runs through the bot whenever the
simulator is up. Write your own as `devtools/scenarios/<name>.json`:
`{"description": "...", "steps": [...]}`, and give it an end-state check in
`tests/test_devtools_scenarios.py` and `tests/e2e/test_scenarios.py` (see the
[developer guide](../docs/dev/README.md#the-control-panel-and-scenarios)).
