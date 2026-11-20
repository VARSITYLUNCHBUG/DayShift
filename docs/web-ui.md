# The player web UI

DayShift's second client. Players sign in on the web and play the same match they play on
Discord: queue, ready check, captain vote and check-in, the player draft, the coinflip, the hero
draft, the lobby, the report and the result, plus subs, swaps and early leaves. The web adds hero
wishes and team chat, the postgame screens (summary, timeline, replay, advanced) and a private
profile with a shareable card.

It never has rules of its own. Every button calls the same `league/services` function the
Discord button calls, so the bot and the web always agree, and a refusal reads the same on both.
Whatever one client does, the other shows within a moment.

The app is a React single-page app in `services/web/` (React 19, TypeScript, Vite, HeroUI v3,
Tailwind). The web service serves it: Django answers every page with its `index.html`, and
WhiteNoise serves its files under `/static/web/`. There is no Node in production.

## Signing in

- **Discord** is how a player signs in: OAuth2 with the `identify` scope only, so the web UI
  learns who you are and nothing else. The bot then checks you're a member of the server
  (`WEB_GUILD_ID`) with its own token. Someone who isn't gets the invite (`DISCORD_INVITE_URL`)
  instead.
- **Steam** proves a Steam account is yours: you sign in on Steam's own page (OpenID), so
  DayShift never sees your Steam password. A proven account can sign you in later, after the
  same membership check.
- **Privacy.** Your profile is yours alone: other players see your name and avatar on the
  ladder and in matches, never your profile or your Steam or Discord ids. Match pages are
  the shared record, so everyone signed in can open them. Hero wishes and team chat go to your
  own team only, and the lobby code to the match's players only.
- Admin logins are separate and stay password-only: signing in to the web UI never opens
  `/admin/`.

## Running it locally

You need Postgres (the dev stack's, from `make dev`, on `127.0.0.1:15432`, or any other), uv and
Node 22.12 or later.

```bash
export DJANGO_DOTENV=off DEBUG=true DEV_CONTROL=true WEB_DEV_LOGIN=true \
       DJANGO_SECRET_KEY=dev-only DATABASE_URL=postgres://dayshift:dev@127.0.0.1:15432/dayshift
uv run --frozen python manage.py migrate     # then load_presets and dev_seed on a new database
uv run --frozen uvicorn config.asgi:application --port 8000 --reload --lifespan off

cd services/web && npm ci && npm run dev     # http://localhost:5173
```

Vite serves the app with hot reload and proxies `/api`, `/auth`, `/avatar`, `/admin`,
`/_control`, `/static/hero-art` and the `/ws` websocket to Django on port 8000.

- **Dev login.** With `WEB_DEV_LOGIN=true` (refused without `DEBUG`), the sign-in page offers
  `/auth/dev/`: sign in as any player, or make a stand-in with a name. The Discord simulator has
  no OAuth2, so this is how you sign in on the dev stack too.
- **The other eleven players.** Drive them with the dev control API (`/_control/api/`, see
  [devtools/README.md](../devtools/README.md)) or the control panel on top of it: make fake
  players, fill the queue around you, and complete phases or act as anyone. The web UI picks it
  all up live.
- **The dev stack** (`make dev`) builds the app into its image, so it's also on the edge at
  http://localhost:18080/.
- **Without the Vite server**, `npm run build` writes `services/web/dist`, and uvicorn serves it
  at http://localhost:8000/ as production does.
- **Types from Django.** The websocket's messages are pydantic models. After changing them, run
  `uv run --frozen python manage.py export_ws_schema`, then `npm run gen` in `services/web`, which
  rewrites `src/live/protocol.gen.ts`. CI fails when the two are out of step.

## Live updates

The bot and the web are separate processes, so Postgres carries the news between them.

1. Every service change that touches a match, the queue or a player sends
   `pg_notify('dayshift_live', topic)` inside its own transaction, so a notification goes out
   only when the change commits. Topics are `match:<id>`, `queue:<community id>` and
   `player:<player id>`.
2. The web process holds one `LISTEN dayshift_live` connection, on its own thread. Each topic it
   hears goes to an in-process hub.
3. The hub rebuilds the snapshot of that topic (in a read-only, repeatable-read transaction),
   cuts it down for each viewer, and sends it to every socket on `/ws/` that follows it.
   Snapshots carry a revision, so a client never goes backwards.
4. Players act over the same socket. Each action calls the service function; its snapshots go out
   before its answer, and a refusal carries the service's own message. A socket gets ten actions
   per five seconds.

If the LISTEN connection drops, the hub reconnects and rebuilds everything it serves, since
anything said meanwhile was lost. The hub lives in the web process's memory, so web runs **one
worker**: a second would need a channel layer such as Redis to share it.

## Tests

| What | Where | Runs |
|---|---|---|
| The Python side: auth, snapshots, actions, the socket, NOTIFY | `tests/test_web_*.py`, `tests/test_live.py` | `make test`, CI |
| Components and the live client (Vitest) | `services/web/src/**/*.test.tsx` | `npm test`, `make web-test`, CI |
| Types, lint, the build | `services/web` | `npm run typecheck`, `npm run lint`, `npm run build`, CI |
| End to end (Playwright) | `services/web/e2e/` | git hooks, `make web-e2e` |

The Playwright suites run on your machine only, never in CI. `scripts/web-e2e.sh` starts a
throwaway Postgres in Docker, migrates and seeds it, builds the app, starts uvicorn and runs
Chromium against it, then tears it all down.

- **pre-commit** runs the smoke set (about a minute) when a commit touches `services/web/`,
  `league/web/`, `league/services/` or `config/`, and `web-check` (types, lint, Vitest) for
  `services/web/`.
- **pre-push** runs the full suite.

Install both hooks once with `uv run pre-commit install` (the config's
`default_install_hook_types` installs pre-push too), and Chromium with
`npx playwright install chromium` in `services/web`. Skip a run with `SKIP=web-e2e git push`,
or `SKIP=web-e2e-smoke git commit`. [services/web/e2e/README.md](../services/web/e2e/README.md)
has the details.

## Deploying it

The web UI is in the published image: nothing else to build or run.

- **Environment** (`.env.example` lists them):

  | Variable | What |
  |---|---|
  | `PUBLIC_URL` | Where players open it, such as `https://play.example.com`. Sign-in redirects are built from it, never from the request. |
  | `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET` | The bot application's OAuth2 client, from the Developer Portal's OAuth2 page |
  | `WEB_GUILD_ID` | The server players must be in. Defaults to `DISCORD_GUILD_ID`. |
  | `DISCORD_INVITE_URL` | Optional: the `https://discord.gg/` invite for people who aren't in it yet |
  | `WEB_DB_THREADS` | Optional: threads for the socket's database work (8) |
  | `WEB_DEV_LOGIN` | Never in production. It refuses to start without `DEBUG`. |

  `ALLOWED_HOSTS` must name the domain: it also checks the websocket's `Origin`, which is what
  stops another site opening a player's socket.
- **The OAuth2 redirect.** In the Developer Portal, add `PUBLIC_URL` + `/auth/discord/callback/`
  (`https://play.example.com/auth/discord/callback/`) to the application's redirects. Steam needs
  nothing registered.
- **The edge.** `/ws/` needs no special config: Caddy's `reverse_proxy` passes websocket
  upgrades through as they are, with the `Host` and `Origin` the browser sent. Behind another
  proxy, make sure it forwards `Upgrade` and `Connection` and keeps a quiet socket open for at
  least a minute: the app pings within that.
- **One web worker**, as the image's command already runs it (see above).
