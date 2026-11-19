# Deploying DayShift

Ansible installs the bot on a fresh Ubuntu 24.04 or Debian 12 server: Docker, a hardened host, the
compose project with HTTPS, nightly backups and health alerts. Afterwards it upgrades it to new
images. You run it from your own machine (the controller); the server builds nothing, it pulls
the published image. One server per install, one Discord server per install.

What ends up on the server:

| Piece | What it is |
|---|---|
| `/opt/dayshift/` | `compose.yaml`, `compose.prod.yaml` and `infra/caddy/Caddyfile` from this checkout, and `.env`, written from your inventory and vault |
| `edge` | Caddy, on 80 and 443: HTTPS with a certificate it gets and renews from Let's Encrypt by itself |
| `web` | The Django admin and the calibration dashboard, and their static files |
| `bot` | The Discord connection, clicks, the effect worker, the match timers and the health watchdog |
| `migrate` | One-shot: migrations and presets, before web and bot start |
| `db` | Postgres 17, not published on the host |
| `dayshift-backup.timer` | A nightly `pg_dump` to `/var/backups/dayshift`, checked and kept 14 days |
| `dayshift-health.timer` | Every 5 minutes: is every container running and healthy? A change is posted once |
| `dayshift-notify` | Posts to your Discord webhook (`vault_alert_webhook_url`) and logs to the journal |
| The host | A deploy user with your SSH keys only, no root or password logins, ufw with 22, 80 and 443 open, unattended upgrades (Docker's included) |

## What you need

- A VPS with Ubuntu 24.04 or Debian 12, 2 GB of RAM and 20 GB of disk, and root SSH with your key.
- A domain such as `play.example.com`, with its `A` (and `AAAA`) record pointing at the server.
  The edge gets its certificate on first start, which only works once the name resolves there.
- A controller: Linux, or the dev VM on Windows (`scripts\dev-vm.ps1 shell`), with uv and make.

## Install

1. Create the Discord application and its bot in the
   [Developer Portal](https://discord.com/developers/applications) (no privileged intents), copy
   the bot token, and invite it, replacing `YOUR_APP_ID`:
   `https://discord.com/oauth2/authorize?client_id=YOUR_APP_ID&scope=bot+applications.commands&permissions=281475298741265`
2. Install Ansible on the controller, from the repo checked out at the release you're deploying:
   ```bash
   make deploy-tools
   ```
3. Copy the example inventory and fill it in:
   ```bash
   cp -r deploy/ansible/inventories/example deploy/ansible/inventories/acme
   cp deploy/ansible/inventories/acme/group_vars/all/vault.yml.example deploy/ansible/inventories/acme/group_vars/all/vault.yml
   ```
   - `hosts.yml`: the server's address.
   - `group_vars/all/main.yml`: the domain, the image tag (a `sha-<commit>` from the repo's
     packages), the Discord server ID and your SSH public key. Every setting is commented.
   - `group_vars/all/vault.yml`: the bot token, a Django secret key and a Postgres password, and
     optionally the alert webhook and a healthchecks.io ping URL. Then encrypt it with
     `deploy/ansible/.venv/bin/ansible-vault encrypt deploy/ansible/inventories/acme/group_vars/all/vault.yml`.
   Keep `inventories/acme` in a private repository of your own: `deploy/.gitignore` leaves it
   out of this one.
4. The first run logs in as root and creates the deploy user. After that, root logins are off:
   ```bash
   cd deploy/ansible && .venv/bin/ansible-playbook -i inventories/acme site.yml --ask-vault-pass -e ansible_user=root
   ```
   It ends by checking `https://<domain>/readyz` answers.
5. In Discord, run `/setup pug_role:@PUGS` as the server owner, then `/permissions grant` for the
   staff roles.
6. Create an admin login. It asks for your Discord user ID as well as a username and password:
   every login is a player, and one who has already played keeps their history
   ([quick start](../docs/quickstart.md#5-create-an-admin-login)).
   ```bash
   ssh -t deploy@<server> 'cd /opt/dayshift && sudo docker compose exec web python manage.py createsuperuser'
   ```

A test server whose name isn't public (`play.example.test`, say) can't get a Let's Encrypt
certificate: set `dayshift_tls_internal: true` and Caddy signs one with its own CA, and
`dayshift_check_https: false` if the controller can't resolve the name.

## Running it

| Task | How |
|---|---|
| Apply a changed inventory or vault, or a newer checkout's compose files | `make site CLIENT=acme` |
| Upgrade to another image | `make deploy CLIENT=acme TAG=sha-<commit>`. It backs up first; set the same tag in `main.yml` afterwards |
| Roll back | Deploy the old tag. If the new one migrated the database, restore the backup the upgrade took |
| Back up now, and copy the dump here | `make backup CLIENT=acme` (lands in `deploy/ansible/backups/<host>/`) |
| Restore | `cd deploy/ansible && .venv/bin/ansible-playbook -i inventories/acme restore.yml -e confirm=yes` (the newest dump, or `-e dump=/var/backups/dayshift/<file>`) |
| Rotate a secret | Change it in the vault and run `make site`. A new Postgres password also needs `ALTER ROLE dayshift PASSWORD '...'` in `docker compose exec db psql -U dayshift` first |
| Logs | `ssh deploy@<server>`, then `cd /opt/dayshift && sudo docker compose logs -f bot web` |
| Health | `sudo docker compose ps`; `journalctl -t dayshift-notify` for every alert sent |

How you hear that something is wrong:

- **A container stops or turns unhealthy.** `dayshift-health.timer` posts it to the alert
  webhook, and posts again when everything is healthy.
- **A backup fails.** The unit's failure is posted with its last log lines.
- **The league stops keeping up.** The bot's watchdog checks every minute for timers that stopped
  firing and for Discord work piling up. It posts to the operator's error channel
  (`dayshift_error_log_channel_id`) once when that starts and once when it clears.
- **The whole server goes down.** With `vault_healthcheck_ping_url` set, the bot pings it every
  minute, and the service (healthchecks.io or similar) tells you when the pings stop.

## Before launch

These haven't been confirmed against the real services yet. Check each before a server goes live:

- **Rating convergence.** A strong player seeded as new takes 29 to 81 games to reach mu 30 in
  simulation. Seed known players with `/rating seed`, and see
  [Convergence](../docs/ratings.md#convergence-still-to-check-before-launch) for the `sigma`
  trade-off.
- **The bot's lobby.** deadlock-api's custom lobby start uses the party ID from creation as the
  lobby ID. Confirm it with one real lobby, and that the bot's lobby can be joined and started as
  [described](../docs/integrations.md#lobbies).
- **Discord on every client.** Voice invite links and the report form's screenshot upload on
  desktop, mobile and web.
- **The host checklist.** The current custom-lobby steps in Deadlock, for the host checklist text
  in `bot/renderers/board.py`.
- **Discord's 16 November 2026 channel change.** Every channel the bot creates already grants the
  bot its own `VIEW_CHANNEL`; confirm the behaviour after the change.

## Uninstalling

```bash
ssh deploy@<server> 'cd /opt/dayshift && sudo docker compose down -v'
```

That deletes the database. Take a backup first.
