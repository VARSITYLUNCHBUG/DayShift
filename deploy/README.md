# Deploying dl-mm-discord

Ansible installs the bot on a fresh Ubuntu 24.04 or Debian 12 server: Docker, a hardened host, the
compose project with HTTPS, nightly backups and health alerts. Afterwards it upgrades it to new
images. You run it from your own machine (the controller); the server builds nothing, it pulls
the published image. One server per install, one Discord server per install.

What ends up on the server:

| Piece | What it is |
|---|---|
| `/opt/draftbot/` | `compose.yaml`, `compose.prod.yaml` and `infra/caddy/Caddyfile` from this checkout, and `.env`, written from your inventory and vault |
| `edge` | Caddy, on 80 and 443: HTTPS with a certificate it gets and renews from Let's Encrypt by itself |
| `web` | The Django admin and the calibration dashboard, and their static files |
| `bot` | The Discord connection, clicks, the effect worker, the match timers and the health watchdog |
| `migrate` | One-shot: migrations and presets, before web and bot start |
| `db` | Postgres 17, not published on the host |
| `draftbot-backup.timer` | A nightly `pg_dump` to `/var/backups/draftbot`, checked and kept 14 days |
| `draftbot-health.timer` | Every 5 minutes: is every container running and healthy? A change is posted once |
| `draftbot-notify` | Posts to your Discord webhook (`vault_alert_webhook_url`) and logs to the journal |
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
6. Create an admin login:
   ```bash
   ssh deploy@<server> 'cd /opt/draftbot && sudo docker compose exec web python manage.py createsuperuser'
   ```

## Running it

| Task | How |
|---|---|
| Apply a changed inventory or vault, or a newer checkout's compose files | `make site CLIENT=acme` |
| Upgrade to another image | `make deploy CLIENT=acme TAG=sha-<commit>`. It backs up first; set the same tag in `main.yml` afterwards |
| Roll back | Deploy the old tag. If the new one migrated the database, restore the backup the upgrade took |
| Back up now, and copy the dump here | `make backup CLIENT=acme` (lands in `deploy/ansible/backups/<host>/`) |
| Restore | `cd deploy/ansible && .venv/bin/ansible-playbook -i inventories/acme restore.yml -e confirm=yes` (the newest dump, or `-e dump=/var/backups/draftbot/<file>`) |
| Rotate a secret | Change it in the vault and run `make site`. A new Postgres password also needs `ALTER ROLE draftbot PASSWORD '...'` in `docker compose exec db psql -U draftbot` first |
| Logs | `ssh deploy@<server>`, then `cd /opt/draftbot && sudo docker compose logs -f bot web` |
| Health | `sudo docker compose ps`; `journalctl -t draftbot-notify` for every alert sent |

How you hear that something is wrong:

- **A container stops or turns unhealthy.** `draftbot-health.timer` posts it to the alert
  webhook, and posts again when everything is healthy.
- **A backup fails.** The unit's failure is posted with its last log lines.
- **The league stops keeping up.** The bot's watchdog checks every minute for timers that stopped
  firing and for Discord work piling up. It posts to the operator's error channel
  (`draftbot_error_log_channel_id`) once when that starts and once when it clears.
- **The whole server goes down.** With `vault_healthcheck_ping_url` set, the bot pings it every
  minute, and the service (healthchecks.io or similar) tells you when the pings stop.

## Uninstalling

```bash
ssh deploy@<server> 'cd /opt/draftbot && sudo docker compose down -v'
```

That deletes the database. Take a backup first.
