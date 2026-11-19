# Quick start

Run the whole stack on one machine, with the admin on 127.0.0.1. You need Docker with the
compose plugin, plus [uv](https://docs.astral.sh/uv/) if you want to generate secrets with the
commands below.

For a server on the internet, use the [deploy guide](../deploy/README.md) instead: it adds
automatic HTTPS, health alerts, nightly backups and a hardened host.

## 1. Create the Discord bot

Create an application and a bot in the
[Discord Developer Portal](https://discord.com/developers/applications). No privileged intents
are needed.

Invite it to your server, replacing `YOUR_APP_ID`:

```
https://discord.com/oauth2/authorize?client_id=YOUR_APP_ID&scope=bot+applications.commands&permissions=281475298741265
```

## 2. Fill in `.env`

Copy `.env.example` to `.env` and fill in:

| Variable | What it is |
|---|---|
| `DISCORD_TOKEN` | The bot's token, from the Developer Portal |
| `DISCORD_GUILD_ID` | Your Discord server's ID |
| `DJANGO_SECRET_KEY` | A long random string |
| `POSTGRES_PASSWORD` | The database password. It goes into a database URL, so use letters and digits only |

Generate the key and the password with:

```bash
uv run python -c "import secrets; print(secrets.token_urlsafe(50))"
uv run python -c "import secrets; print(secrets.token_hex(32))"
```

`DATABASE_URL` in `.env` is only for running `manage.py` on your machine against the compose
database. Put the same password in it.

## 3. Start the stack

From the published image:

```bash
docker compose pull && docker compose up -d
```

Or built from your checkout. Set `DAYSHIFT_IMAGE_TAG=local` in `.env` first, so your build has a
tag of its own that a later `pull` doesn't replace:

```bash
docker compose up -d --build
```

That starts `db` (Postgres), the one-shot `migrate` (migrations and presets, before anything
else), `web`, `bot` and the `edge` (Caddy), which serves the admin on http://127.0.0.1:8000.
`docker compose ps` should show every service it lists as healthy. `migrate` has exited by then,
so only `docker compose ps -a` shows it.

The published image is `ghcr.io/varsitylunchbug/dayshift`, listed under the repo's
Packages. It's built from `main` without score OCR: `latest` and `main` follow `main`, and
`sha-<commit>` pins one build (`DAYSHIFT_IMAGE_TAG`). To build with score OCR, see
[Score OCR](integrations.md#score-ocr).

## 4. Set up the Discord server

In Discord, run `/setup pug_role:@PUGS` as the server owner or an Administrator. It creates the
queue, Waiting Room, results, leaderboard, archive and staff-alerts channels, and it is safe to
run again.

With a PUG role, only that role sees the queue, Waiting Room, results and leaderboard, and only
it can use `/leaderboard`. Without one, everyone can.

Then give your staff roles their areas with `/permissions grant` (see
[Permissions](admin.md#permissions)).

## 5. Create an admin login

```bash
docker compose exec web python manage.py createsuperuser
```

It asks for a username, your Discord user ID and a password. Every login is a player,
so the Discord ID is required: copy yours from Discord (turn on Developer Mode in Settings,
Advanced, then right-click your name and choose Copy User ID). If you've already played, your
player gets the login and keeps its history.

Sign in at http://127.0.0.1:8000/admin/. [The admin guide](admin.md) covers what you can change
there.

## Running it

```bash
docker compose ps
docker compose logs -f bot
docker compose exec bot python manage.py check_ledger
```

- `check_ledger` is also **Check ledger** on the admin's Rating runs list, and `rebuild_ratings`
  recreates `player_ratings` from the ledger without writing to the ledger itself
  ([the ledger](ratings.md#the-ledger)).
- If channels aren't being created or cleaned up, check the admin's Outbox effects page, filtered
  to `failed`.
- Back up the database daily: the volume is the only copy of match history and ratings. A
  client install does that by itself; the [deploy guide](../deploy/README.md#running-it) has how,
  and how to restore.

## Ports

The edge listens on 127.0.0.1 only (`EDGE_PORT`, default 8000), and Postgres on
127.0.0.1:55432 (`DB_PORT`) for tools on your machine. Don't publish either: to put the bot on the
internet, use the [deploy guide](../deploy/README.md), which serves the same stack over HTTPS with
a certificate from Let's Encrypt.

## Next steps

- [How a match runs](match-flow.md), so you know what players will see.
- [The admin](admin.md): runtime settings, draft modes, champions and staff permissions.
- The [deploy guide](../deploy/README.md), when it's time to put it on a server.
