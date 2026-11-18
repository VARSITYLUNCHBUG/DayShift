# Control panel (dev only)

A small web app for driving the local dev stack by hand: make fake players, fill the queue,
push a match through its phases, click the bot's buttons as any fake user, and step through
scripted scenarios. It is a UI over two APIs:

- the dev control API in Django, `/_control/api/` (`devtools/README.md`), and
- the Discord simulator's control API, `/_sim/` (`services/discord-sim/`).

It has no login and talks to APIs that have none either. Never run it anywhere but your own
machine.

## Running it

With the dev stack (`make dev`, see `docs/dev/README.md`) it runs as the
`control-panel` service at <http://127.0.0.1:18091>. The container is nginx serving the built
app on port 8091, and it proxies:

| Path | Goes to |
|---|---|
| `/_control/` | `http://web:8000` |
| `/_sim/` (and the `/_sim/events` stream, unbuffered) | `http://discord-sim:8090` |
| `/healthz` | nginx itself (the container healthcheck) |
| anything else | the app (`index.html`) |

So the browser only ever talks to one origin. Upstreams are looked up per request, so the panel
still starts when the simulator isn't there (real-Discord mode); the sim parts then show as down.

To work on the panel itself, with Node 22 or later:

```
npm ci
npm run dev          # http://127.0.0.1:5174, proxying to the dev stack on 18000 and 18090
```

No stack running? Use the built-in mock of both APIs instead:

```
npm run mock         # terminal 1: fake control API and simulator on 18099
npm run dev:mock     # terminal 2: the dev server, proxying to the mock
```

Point the dev server somewhere else with `PANEL_CONTROL_TARGET` and `PANEL_SIM_TARGET`.

## Screens

The header shows the **DEV ONLY** badge, which community, season and draft mode are loaded,
and health dots for `web` (the control API answers), `sim` (the simulator answers) and `bot`
(the bot has a gateway session with the simulator). **Pause timers** and **Resume timers** freeze
every live match's clock. **Reset…** asks first, then resets the simulator and reloads the dev
fixtures (`dev_default`, or `none` for just the community and season).

Keys `1` to `4` switch screens (when you're not typing in a field).

1. **Players**: add N fake players with a fixed rating or a range, DMs open or closed, and
   optionally straight into the queue. In the table you can edit a rating in place (Enter
   saves, Esc cancels), flip DMs, set a champion plan (preferred and banned slugs the
   autopilot uses), queue or unqueue a selection, and delete.
2. **Queue & matches**: the queue in order, **Fill to 12**, and a card per live match with its
   status, whose turn it is, teams, picks and bans, check-ins, swaps, and a live countdown.
   - **Complete phase** plays out the current phase; **Advance to ▸** keeps going until a
     status. Both act as the players who still have to act.
   - The selector at the top picks how: **Discord clicks** (the bot's own handlers run, through
     the simulator) or **league services** (direct calls, faster). **Auto**, the default, uses
     Discord clicks while the bot is connected to the simulator and the services otherwise.
   - **Pause timer** / **Resume timer** freeze that match; **Fire now** runs its deadline as if
     it had run out.
   - **Act as…** sends one action as one player (or a selector such as `captain:A` or
     `acting`), with its arguments as JSON. It offers only what the phase allows (check-in,
     swaps, subs, the lobby, the report and so on), who can do it, and the arguments filled in;
     **Every action and player** lifts that, to try the league's refusals.
   - **Script…** stores a plan the autopilot follows: draft order, champion steps, captain votes,
     coinflip choice, lobby code and winner.
3. **Discord view**: the simulated guild. Pick a channel, or a user's DMs, to see the messages
   as the bot wrote them, with their buttons and selects. Choose who to act as at the top and
   click any button as them (in a DM you always act as that user), or type a message. A button
   that opens a form (the result report, say) shows the form as the bot built it, with a file
   picker for uploads (left empty, the simulator's placeholder image is sent). **raw** shows the
   Discord payload. On the right, the simulator's live event log: every REST call the bot makes,
   every gateway event, every control call. Click a line for its JSON.
4. **Scenarios**: the presets in `devtools/scenarios/`, run one API call at a time from the
   browser. **Next step** (`N`) runs one step and stops, so you can look around between steps
   (the runbook mode); **Run** (`P`) goes on to the end and **Pause** (`P`) stops before the next
   step; a step's number sets a breakpoint; **Rewind** (`R`) starts over. Each step shows what it
   expected (a step's own `expect`, `{"status": ..., "http": ...}`, or the status its `until`
   names) against what happened, and **Stop when a step doesn't do what it expects** pauses on a
   surprise. **Seconds between steps** slows a run down. The steps are editable JSON, and
   **Custom steps…** starts from an empty list.

## Code

- `src/api/` is the only code that knows the APIs: `http.ts` (fetch, errors, exact parsing of
  large integer ids), `control.ts` and `sim.ts` (one function per endpoint), and `schemas.ts`
  (zod schemas that check each response and turn it into what the screens use). When an API
  changes shape, this folder is where you fix it; `client.test.ts` pins the shapes against the
  examples in the backends' docs.
- `src/screens/` has the screens (Players and Scenarios as one file each, `matches/` and
  `discord/` as folders with their cards and modals), `src/components/` the small shared pieces,
  `src/lib/` the rules the screens share (which actions a phase allows, scenario expectations),
  and `src/hooks/` polling (`usePoll`, state every 1.5 to 2 s), the event stream
  (`useEventLog`), toasts for actions (`useAction`) and keyboard shortcuts.
- `mock/server.mjs` is the stand-in for both APIs, with no dependencies.
- Tests sit next to what they test (`*.test.ts`, `*.test.tsx`): the API client, `src/lib/`, and
  the act-as, bot-form and scenario screens (in jsdom).

Built with Vite, React 19, TypeScript (strict), HeroUI v3 and Tailwind v4, pinned to the
versions the web UI uses.

```
npm run typecheck
npm run lint
npm test             # vitest
npm run build        # into dist/
docker build -t draftbot-dev/control-panel:local .
```
