# Deploying dl-mm-discord for a client

This folder installs the bot on a fresh Ubuntu 24.04 or Debian 12 server with Ansible: HTTPS,
pooled database connections, metrics and alerts, nightly backups and a hardened server, and
upgrades it afterwards. One server per client, one Discord server per install. You run Ansible
from your own machine (the controller); nothing is installed on the server by hand.

Once it's installed, [docs/ops/](../docs/ops/README.md) covers running it: alerts, backups,
upgrades, secrets and capacity. [docs/architecture.md](../docs/architecture.md) explains the
services.

What ends up on the server:

| Piece | What it is |
|---|---|
| `/opt/draftbot/` | The compose project: `compose.yaml` and `compose.observability.yaml` (the repo's), `compose.prod.yaml` (this folder's), `.env` (the app's, from your vault), `.env.observability` (Grafana's and Alertmanager's secrets, which the app never sees), `infra/` (nginx, pgbouncer and observability configuration), `edge/` (the edge's own files, such as the admin access rules), `letsencrypt/` (certificates) |
| `edge` | nginx: the only thing published, on 80 and 443. TLS, HTTP to HTTPS, websockets, 21 MB uploads, security headers and HSTS, rate limits on the admin login and Discord sign-in |
| `certbot` | Gets the certificate from Let's Encrypt over HTTP-01; `draftbot-certbot-renew.timer` renews it twice a day |
| `web` | The admin and the calibration dashboard, and the player web UI once it ships. uvicorn, 1 worker, behind the edge |
| `bot` | `runbot --role gateway`: the Discord connection, interactions and Discord effects |
| `scheduler` | `runbot --role scheduler`: match timers and the daily prune, database only |
| `migrate` | One-shot job: static files for the edge, migrations, presets, and the app's and the exporters' database roles. Runs when the image changes, and when a role's password does |
| `pgbouncer` | Transaction pooling between the app and Postgres, SCRAM logins |
| `db` | Postgres 17. Not published on the host |
| Prometheus, Alertmanager, Grafana, exporters | Metrics, 21 alerts and 5 dashboards. Grafana on the server's 127.0.0.1, reached by SSH tunnel (or optionally its own domain) |
| `draftbot.service` | systemd unit that starts the project at boot |
| `draftbot-backup.timer` | Nightly `pg_dump` to `/var/backups/draftbot`, kept 14 days, optionally copied offsite with rclone, encrypted with age |
| `draftbot-notify@.service` | Logs, and optionally posts to Discord, when a backup, a renewal or the boot unit fails |
| ufw, fail2ban, unattended-upgrades | Only 22, 80 and 443 open; SSH keys only, no root login; security updates daily |

Backups and renewals run on the host from systemd timers rather than in sidecar containers: they
keep working when the compose project is stopped, log to the journal, and report failures.

## What you need

- A VPS with Ubuntu 24.04 or Debian 12, 2 GB of RAM and 20 GB of disk, that you can SSH into as
  root with a key.
- A domain or subdomain you can point at it, such as `play.example.com`.
- A controller: Linux, macOS, or WSL on Windows, with Python 3.12 or later and an SSH key. On WSL,
  clone the repo inside the Linux filesystem (`~/`), not under `/mnt/c`: Ansible ignores
  `ansible.cfg` in a world-writable folder.

## 1. Create the Discord application

1. In the [Discord Developer Portal](https://discord.com/developers/applications), create an
   application and its bot. No privileged intents are needed. Copy the bot token
   (Bot > Reset Token) for the vault.
2. Invite the bot to the client's server, replacing `YOUR_APP_ID` with the application ID:
   ```
   https://discord.com/oauth2/authorize?client_id=YOUR_APP_ID&scope=bot+applications.commands&permissions=281475298741265
   ```
3. For the player web UI's "Sign in with Discord" (it ships after this release; you can do this
   now or then): on the OAuth2 page, copy the client ID (for the inventory) and the client secret
   (for the vault), and add the redirect `https://play.example.com/auth/discord/callback/` with
   your domain, trailing slash included.
4. In Discord, turn on Developer Mode (User Settings > Advanced), right-click the server and
   Copy Server ID, for the inventory.

## 2. Point DNS at the server

Create an `A` record for your domain with the server's IPv4 address, and an `AAAA` record if it has
IPv6. Do the same for Grafana's name if you give it one (`draftbot_grafana_domain`). Wait until it
resolves from your machine:

```bash
dig +short play.example.com
```

The first run asks Let's Encrypt for the certificate, and that only works once the name resolves
to the server and port 80 reaches it. If your provider has its own firewall, open 22, 80 and 443
(TCP) there too.

## 3. Prepare the server

A fresh VPS is enough: the playbook installs everything. Check you can log in as root with your
key, which the first run uses:

```bash
ssh root@203.0.113.10
```

If the provider only gave you a password, add your key first with
`ssh-copy-id root@203.0.113.10`.

## 4. Set up the controller

From a clone of this repo, checked out at the release you're deploying:

```bash
cd deploy/ansible
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
ansible-galaxy collection install -r requirements.yml
```

Run every `ansible-playbook` command below from `deploy/ansible`, with the virtualenv active.

## 5. Write the inventory and the vault

Copy the example inventory for the client and fill it in:

```bash
cp -r inventories/example inventories/acme
cp inventories/acme/group_vars/all/vault.yml.example inventories/acme/group_vars/all/vault.yml
```

- `inventories/acme/hosts.yml`: the server's address as `ansible_host`.
- `inventories/acme/group_vars/all/main.yml`: the domain, the image tag, your SSH public key
  (`cat ~/.ssh/id_ed25519.pub`), the Let's Encrypt contact email, the Discord server ID and client
  ID. Every setting is commented. Pin `draftbot_image_tag` to a `sha-<commit>` tag from the repo's
  Packages page so every run installs the same build.
- `inventories/acme/group_vars/all/vault.yml`: every secret. Generate the Django key, the database
  password, the app role's and the monitoring role's passwords and Grafana's admin password with
  the commands in the file.

Then encrypt the vault, and keep its password somewhere safe:

```bash
ansible-vault encrypt inventories/acme/group_vars/all/vault.yml
```

Git ignores every inventory except the example. Keep client inventories in your own private
repository, or in a private fork with that rule removed from `deploy/.gitignore`. To skip typing
the vault password, put it in `.vault-pass` (also ignored, `chmod 600`) and use
`--vault-password-file .vault-pass` instead of `--ask-vault-pass`.

Options worth knowing before the first run:

| Setting | Default | What it does |
|---|---|---|
| `draftbot_observability` | `true` | Prometheus, Alertmanager, Grafana and the exporters. Off removes their containers and keeps their data |
| `draftbot_grafana_domain` | empty | Grafana on the web at this name too, on the same certificate, behind a password prompt (`vault_grafana_basic_auth_users`) and its own login |
| `edge_admin_allow_cidrs`, `edge_admin_basic_auth_users` | empty | Lock down the Django admin at the edge, in front of its own login: only these addresses, and/or a password prompt for these users (`vault_admin_basic_auth_users`). `edge_admin_satisfy: any` lets an allowed address in without the prompt |
| `edge_certificate` | `letsencrypt` | `selfsigned` for a test server without public DNS: a one-year certificate made on the server; browsers warn |
| `edge_acme_server` | Let's Encrypt production | Set it to `https://acme-staging-v02.api.letsencrypt.org/directory` while you try things out. Setting it back and running `site.yml --tags edge` gets a production certificate |
| `vault_alertmanager_discord_webhook_url` | empty | A Discord channel webhook alerts are posted to |
| `vault_notify_discord_webhook_url` | empty | A webhook told when a backup, renewal or the boot unit fails |
| `backups_rclone_remote`, `backups_offsite_age_recipients` | empty | Copy each night's dump offsite, encrypted to your age public key first (a dump holds live sessions and password hashes). Make the key pair with `age-keygen` on your own machine and keep the private key off the server |
| `base_unattended_docker` | `true` | The nightly security updates upgrade Docker (docker-ce, containerd.io and its runc, the compose plugin) too; containers keep running. `false` holds Docker until `site.yml --tags docker -e docker_upgrade=true` |

Getting a certificate accepts the Let's Encrypt Subscriber Agreement for `edge_acme_email`.

## 6. Install

The first run logs in as root, creates the `deploy` user with your key, and turns root and
password logins off:

```bash
ansible-playbook -i inventories/acme site.yml --ask-vault-pass -e ansible_user=root
```

It takes a few minutes. On a fresh server the edge first starts with a site that answers only
Let's Encrypt's challenge on port 80, certbot gets the certificate, and then the edge switches to
the HTTPS site. Once the edge is up, the run fetches `https://<domain>/readyz` through it, which
answers only when web reaches Postgres through pgbouncer, so a finished run means DNS, the
certificate, the edge, the web process and the database all work.

Every later run logs in as `deploy`, as the inventory says:

```bash
ansible-playbook -i inventories/acme site.yml --ask-vault-pass
```

`site.yml` is safe to run again at any time: it changes only what differs from the inventory.
On an installed server, add `--check --diff` to see what it would change first. Every run first
checks the inventory and the vault, before it changes anything; `--tags checks` runs only that.
Tags run one part: `base`, `docker`, `app`, `edge`, `observability`, `backups`, and finer ones:

| Tag | What it runs |
|---|---|
| `base-packages`, `base-users`, `base-ssh`, `base-firewall`, `base-fail2ban`, `base-upgrades`, `base-notify` | One part of the server's setup |
| `docker-config` | Docker's `daemon.json` (log rotation, live-restore). With `-e docker_upgrade=true`, `docker` upgrades Docker now |
| `checks` | Every check of the inventory and the vault below (`app-check`, `edge-check`, `observability-check`, `backups-check`) |
| `app-check`, `app-files` | Check the app's settings and secrets; install the compose files, `infra/pgbouncer` and `.env` |
| `app-start` | Pull the images, migrate if this image hasn't, then start pgbouncer, web, scheduler and bot one at a time |
| `app-systemd` | The boot unit |
| `edge-check`, `edge-files`, `edge-certificate`, `edge-start`, `edge-renew`, `edge-health` | The edge's settings, nginx configuration, certificate, start and reload, renewal timer, HTTPS check |
| `observability-check` | Check Grafana's admin password and the Alertmanager webhook |
| `backups-check`, `backups-offsite` | Check the backup settings; rclone, age and rclone's configuration |

## 7. Set up the Discord server

In Discord, as the server owner or an Administrator:

1. Run `/setup pug_role:@PUGS`. It creates the queue, Waiting Room, results, leaderboard, archive
   and staff-alerts channels, and it is safe to run again.
2. Give the staff roles their areas with `/permissions grant` (see Permissions in the main
   README).

Server configuration (runtime settings, the draft mode, champions, seasons) is in the admin,
not in Discord: see "The admin and Discord" in the main README.

## 8. Create an admin login

```bash
ssh deploy@203.0.113.10
cd /opt/draftbot
sudo docker compose exec web python manage.py createsuperuser
```

The admin is at `https://<domain>/admin/`. The edge allows 5 password attempts a minute from one
address (then 429), on top of Django's own login. Give each staff member their own login with a
long password.

## Running it

On the server, in `/opt/draftbot`, `docker compose` uses every compose file by itself (`.env` sets
`COMPOSE_FILE`):

```bash
sudo docker compose ps
sudo docker compose logs -f bot scheduler
sudo docker compose exec bot python manage.py check_ledger
sudo systemctl list-timers 'draftbot-*'
```

Grafana and Prometheus are on the server's 127.0.0.1:

```bash
ssh -L 13000:127.0.0.1:13000 -L 19090:127.0.0.1:19090 deploy@203.0.113.10
```

then open http://127.0.0.1:13000 and sign in as `admin` with `vault_grafana_admin_password`.
[docs/ops/](../docs/ops/README.md) has the rest: what each dashboard and alert means, and the
incident checklist.

## Upgrading

Set the new tag in `draftbot_image_tag` in the inventory, check out the same release of this repo,
then:

```bash
ansible-playbook -i inventories/acme deploy.yml --ask-vault-pass
```

It takes a backup, pulls the images, runs the migrate job, and recreates pgbouncer, `web`,
`scheduler` and `bot` one at a time, each healthy before the next, then the edge and the
observability services. To roll back, deploy the old tag, and if the new release migrated the
database, restore the backup it took. [docs/ops/upgrades.md](../docs/ops/upgrades.md) has the
details.

## Backups and restore

```bash
ansible-playbook -i inventories/acme backup.yml --ask-vault-pass      # take one now
ansible-playbook -i inventories/acme restore.yml --ask-vault-pass     # prove the newest restores
```

Replacing the live database, offsite copies and rebuilding a server are in
[docs/ops/backups.md](../docs/ops/backups.md).

## Rotating secrets

Change the value in the vault (`ansible-vault edit inventories/acme/group_vars/all/vault.yml`),
then:

```bash
ansible-playbook -i inventories/acme rotate-secrets.yml --ask-vault-pass
```

It checks the new values, takes a backup, sets new database, app role, monitoring role and Grafana
passwords inside Postgres and Grafana, rewrites `.env`, `.env.observability` and the edge's
password files, and recreates the containers whose settings
changed.
[docs/ops/secrets.md](../docs/ops/secrets.md) says where each new value comes from and what it
changes.

## Testing the deploy

`.github/workflows/deploy-lint.yml` runs on every change under `deploy/` or `infra/` and to the
compose files. To run the same checks yourself:

```bash
cd deploy/ansible
pip install -r requirements-dev.txt
ansible-galaxy collection install -r requirements.yml
yamllint -s . && ansible-lint
for p in site deploy backup restore rotate-secrets; do
  ansible-playbook -i inventories/example --syntax-check $p.yml
done
molecule test
```

`molecule test` (scenario `molecule/default`) runs `site.yml` against two throwaway systemd servers,
each with its own Docker daemon: Ubuntu 24.04, with a Let's Encrypt certificate from Pebble (Let's
Encrypt's test CA), Grafana's vhost and the admin behind an allowlist and a password prompt, and
Debian 12, with a self-signed certificate and the admin open. It runs `site.yml` a second time and
fails if anything changed, then checks the result: every service healthy and only the edge
published; the production settings (`DEBUG` off, pgbouncer in front, proxy headers trusted from the
edge's address only); no observability secret in the app's containers; SCRAM through pgbouncer in
transaction mode; web, bot and scheduler logged in as `draftbot_app`, which is no superuser and
can't create tables, without the superuser's password; `nginx -t`; a changed site template served
after a reload, by the same container; `/readyz` through the edge with HSTS and the security headers; a
static file from the edge's volume; the HTTP redirect; `/metrics` and `/nginx_status` refused; a
websocket upgrade; 20 MB uploads allowed and 23 MB refused; the admin's password prompt and
allowlist (or none); the certificate's issuer and names, an unknown name refused, and a forced
renewal reloading the edge; all 10 Prometheus jobs up, both database exporters logged in, the
certificate's expiry scraped, the rules loaded; Grafana on 127.0.0.1 and through its vhost; sshd and
ufw; the NTP client enabled; unattended-upgrades allowing Docker's repository, as its own matching
sees it; the failure notices; a backup, a restore check and a full restore; the restore check
refusing a dump of an emptied table; an offsite copy that is only ever age-encrypted and decrypts
to the dump; an upgrade; database, app role, monitoring role and Grafana password rotation; and a
restart through the boot unit.

A small stand-in image (`molecule/default/stub-app/`) plays the app, so no Discord token is
needed; everything else is the real images. Its migrate job runs the app's own database role
commands (`config/app_role.py`, `league/observability/monitoring_role.py`, copied in by
`prepare.yml`) over a psycopg stand-in for the little of Django they use, so the role and rotation
checks test the real code. It needs Docker with privileged containers. The inner
Docker daemons keep their storage in named volumes (`draftbot-molecule-<platform>-docker` and
`-containerd`, or `MOLECULE_PLATFORM_PREFIX`); remove them after `molecule destroy`.

## Troubleshooting

- **The run stops at "Ask the ACME server for the certificate".** Let's Encrypt couldn't reach the
  challenge. Check `dig +short <domain>` returns the server, that the provider's firewall allows
  port 80, and `sudo docker compose logs edge`. Let's Encrypt rate-limits repeated failures; while
  you fix DNS, use the staging server (`edge_acme_server`, above).
- **The run stops at "Wait for the site to answer over HTTPS".** `sudo docker compose ps` shows
  which service isn't healthy, and `sudo docker compose exec edge nginx -t` checks the edge's
  configuration. `/readyz` answers 503 while web can't reach the database.
- **A service never becomes healthy.** `sudo docker compose ps` shows which; its logs say why. The
  bot is unhealthy until it has connected to Discord, so check the token and that the bot is in
  the server.
- **A check of the inventory or the vault fails.** Each failure names the setting and says what
  it must be; [docs/ops/secrets.md](../docs/ops/secrets.md) lists every rule. `--tags checks`
  runs only the checks.
- **Locked out of SSH.** The base role refuses to run without a key in
  `base_deploy_authorized_keys`, but a wrong key still locks you out. Use the provider's web
  console, fix `/home/deploy/.ssh/authorized_keys`, and run `site.yml` with the right key.
  fail2ban bans an address for an hour after 5 failed logins; `sudo fail2ban-client unban <ip>`.
- **Ports look open that shouldn't be.** Docker publishes container ports ahead of ufw's rules.
  Only the edge publishes on every interface; Grafana and Prometheus bind 127.0.0.1 and nothing
  else is published. Don't add `ports:` to other services.
- **Discord shows "This interaction failed".** The bot is down or restarting: check
  `sudo docker compose logs bot`, and the Outbox effects page in the admin, filtered to `failed`.
- **The migrate job failed.** `deploy.yml` stops before touching the running services. Read the
  output, fix, and run it again; the job runs until it succeeds once for that image.
  `-e app_force_migrate=true` runs it again anyway.
- **Something else.** [docs/ops/incident.md](../docs/ops/incident.md) is the checklist.

## Uninstalling

On the server, stop the project and remove its containers, keeping the data:

```bash
sudo systemctl disable --now draftbot draftbot-backup.timer draftbot-certbot-renew.timer
cd /opt/draftbot && sudo docker compose down
```

To delete everything, including the database and certificates, take a backup first and copy it
off the server, then:

```bash
cd /opt/draftbot && sudo docker compose down --volumes --rmi all
sudo rm -rf /opt/draftbot /var/backups/draftbot /etc/draftbot \
  /usr/local/sbin/draftbot-backup /usr/local/sbin/draftbot-certbot-renew /usr/local/sbin/draftbot-notify \
  /etc/systemd/system/draftbot.service /etc/systemd/system/draftbot-backup.* \
  /etc/systemd/system/draftbot-certbot-renew.* /etc/systemd/system/draftbot-notify@.service \
  /root/.config/rclone/rclone.conf
sudo systemctl daemon-reload
```

Remove the bot from the Discord server, and delete the application in the Developer Portal if
nothing else uses it.
