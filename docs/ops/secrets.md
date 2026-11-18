# Rotating secrets

Every secret of a client install lives in its vault
(`inventories/<client>/group_vars/all/vault.yml`, encrypted with ansible-vault;
`vault.yml.example` lists them all). The server's files are written from it on every run, so
never edit them by hand: change the vault and put it in service.

| File on the server (`/opt/draftbot`) | Holds | Read by |
|---|---|---|
| `.env` (0600) | The Discord token and client secret, `DJANGO_SECRET_KEY`, the API keys, and the three database passwords: `POSTGRES_PASSWORD`, `DB_APP_PASSWORD`, `DB_MONITOR_PASSWORD` | migrate, web, bot and scheduler. compose blanks the database passwords that aren't each service's own: web, bot and scheduler see only `DB_APP_PASSWORD` |
| `.env.observability` (0600) | `GRAFANA_ADMIN_PASSWORD`, `ALERTMANAGER_DISCORD_WEBHOOK_URL` | Grafana and Alertmanager only; the app's containers never see it |
| `edge/grafana.htpasswd`, `edge/admin-access/htpasswd` | The hashes of the Grafana and admin password prompts' passwords, never the passwords | The edge |

## How

1. Get the new value (the table below says where), and change it in the vault:
   ```bash
   ansible-vault edit inventories/acme/group_vars/all/vault.yml
   ```
2. Put it in service:
   ```bash
   ansible-playbook -i inventories/acme rotate-secrets.yml --ask-vault-pass
   ```

`rotate-secrets.yml` first checks every value (below), so a bad one stops it before anything
changes. Then it takes a backup, sets the new passwords where they are stored (Postgres keeps its
superuser's, the app role's and the monitoring role's; Grafana its admin's), rewrites `.env`,
`.env.observability`, the edge's password files and the failure-notice webhook, and recreates
every container whose settings changed. `site.yml` does the same without the backup.

| Secret | Where the new value comes from | What changes |
|---|---|---|
| `vault_discord_token` | Developer Portal > Bot > Reset Token. The old token stops working at once, so run the playbook straight after | The bot reconnects |
| `vault_discord_client_secret` | Developer Portal > OAuth2 > Reset Secret | Web sign-in uses the new one |
| `vault_django_secret_key` | `python3 -c "import secrets; print(secrets.token_urlsafe(50))"` | Everyone is signed out of the admin and the web UI |
| `vault_postgres_password` | `openssl rand -hex 32` | The superuser (`draftbot`, for migrate, backups and you) gets it inside Postgres, over stdin, then `db`, pgbouncer and migrate are recreated with it |
| `vault_db_app_password` | `openssl rand -hex 32`, not the Postgres password | `draftbot_app`, the role web, bot and scheduler log in as, is re-keyed; pgbouncer and the three services are recreated with it |
| `vault_db_monitor_password` | `openssl rand -hex 32`: letters and digits only, and not either other database password | `draftbot_monitor`, the read-only role the exporters log in as, is re-keyed; pgbouncer and the two database exporters are recreated |
| `vault_grafana_admin_password` | `openssl rand -base64 24` | Grafana's `admin` password is reset in place |
| `vault_grafana_basic_auth_users` | `{username, password}` entries; `openssl rand -base64 24` for each password | The edge hashes them on the server and reloads |
| `vault_admin_basic_auth_users` | The same, for the prompt in front of the Django admin (`edge_admin_basic_auth_users`) | The same |
| `vault_alertmanager_discord_webhook_url` | The Discord channel's Integrations > Webhooks | Alertmanager is recreated with it |
| `vault_notify_discord_webhook_url` | The same, or another channel's | The next failure notice uses it |
| `vault_backups_rclone_config` | Your storage provider, then `rclone config` | The next backup uses it |
| `vault_deadlock_api_key`, `vault_steam_web_api_key` | deadlock-api.com, Steam | The bot and web pick them up |

Each check that fails names the setting to fix. They refuse:

- a placeholder (`REPLACE_ME`), and a Django key under 40 characters;
- a Postgres or app role password that isn't 16 or more letters, digits, `-` or `_` (they go into
  URLs), or the two being the same;
- a monitoring role password that isn't 16 or more letters and digits, or equals either other;
- a Grafana admin password under 12 characters;
- a password prompt entry without a username of letters, digits, `_`, `.` or `-`, or with a
  password under 12 characters;
- any secret with a quote or a line break.

The age key that offsite backups are encrypted to isn't in the vault: only its public half is, in
`backups_offsite_age_recipients` ([backups.md](backups.md#offsite-copies)).

## The vault's own password

```bash
ansible-vault rekey inventories/acme/group_vars/all/vault.yml
```

Update `.vault-pass` too if you use one.

## If a secret leaked

Rotate it as above, straight away, then:

- **Bot token**: Discord resets it the moment you press Reset Token, so the leaked one is already
  dead. Check the server's audit log for anything the bot didn't do.
- **Django secret key**: rotating it signs everyone out. Change the admin passwords too if the key
  may have been used to forge a session.
- **A database password**: Postgres isn't published on the host and pgbouncer only on the
  container network, so the password alone doesn't get anyone in. Rotate it anyway. The app
  role's is in web's, bot's and scheduler's environment, so a leak from one of them means that
  one; the monitoring role's can read no table, but it can see the text of running queries.
- **A password prompt's password**: Django's own login is still behind it. Rotate it, and check
  the edge's log for `/admin/` requests from addresses you don't know.
- **A webhook URL**: anyone holding it can post to that channel. Delete the webhook in the
  channel's Integrations, make a new one and rotate.
- **A backup**: a dump holds live sessions, password hashes and every player's Discord ID. Rotate
  `vault_django_secret_key` (it signs everyone out) and the admin passwords. If the age private
  key leaked, make a new pair, set the new public key, run `site.yml --tags backups`, and delete
  the offsite copies made for the old one.
- **The vault itself**: rotate every secret in it, and `rekey`.

## The self-host quickstart

The quickstart keeps its secrets in `.env` (from `.env.example`) and, with the observability
overlay, `.env.observability`. Change them there, then run `docker compose up -d`, which
recreates what uses them.

- `DB_APP_PASSWORD` and `DB_MONITOR_PASSWORD` need nothing else: migrate runs on every `up` and
  sets both roles' passwords from `.env` (`config/app_role.py`,
  `league/observability/monitoring_role.py`).
- A new `POSTGRES_PASSWORD` must be set inside Postgres first:
  `docker compose exec db psql -U draftbot -c '\password draftbot'` asks for it, so it stays out
  of your shell history.
- Grafana only reads `GRAFANA_ADMIN_PASSWORD` when it first creates its data:
  `docker compose exec grafana grafana cli admin reset-admin-password <new>` changes it.
