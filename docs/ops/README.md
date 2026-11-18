# Running a client install

This is for whoever keeps a client's server running after it's installed. The
[deploy guide](../../deploy/README.md) covers the install itself;
[../architecture.md](../architecture.md) explains what runs where.

| Page | When you need it |
|---|---|
| [incident.md](incident.md) | Something is broken right now |
| [alerts.md](alerts.md) | An alert fired: what it means and what to do, one section per alert |
| [observability.md](observability.md) | Getting to Grafana and Prometheus, the dashboards, alert routing, logs |
| [backups.md](backups.md) | Checking backups, taking one, restoring, rebuilding a server |
| [upgrades.md](upgrades.md) | Deploying a new release, rolling back, server updates |
| [secrets.md](secrets.md) | Rotating a token, password or key |
| [capacity.md](capacity.md) | Memory, CPU, database connections and disk: the limits and the math |

## On the server

Everything lives in `/opt/draftbot`. Its `.env` sets `COMPOSE_FILE`, so a plain
`sudo docker compose` there uses every compose file the install has:

```bash
ssh deploy@<server>
cd /opt/draftbot
sudo docker compose ps
sudo docker compose logs -f bot scheduler
sudo docker compose exec bot python manage.py check_ledger
sudo docker compose exec web python manage.py createsuperuser
```

The host's own units:

| Unit | What it does | Logs |
|---|---|---|
| `draftbot.service` | Starts the compose project at boot | `journalctl -u draftbot` |
| `draftbot-backup.timer` | The nightly backup ([backups.md](backups.md)) | `journalctl -u draftbot-backup` |
| `draftbot-certbot-renew.timer` | Certificate renewal, twice a day | `journalctl -u draftbot-certbot-renew` |
| `draftbot-notify@.service` | Reports a failure of the three above | `journalctl -t draftbot-notify` |

```bash
sudo systemctl list-timers 'draftbot-*'
```

Never edit `.env`, `.env.observability`, the compose files or anything under `infra/` or
`edge/` on the server: the next Ansible run puts them back. Change the inventory, the vault or
the repo, and deploy.

## A routine

- **Every day, if you can:** a glance at the Overview dashboard, or trust the alerts channel.
- **Every week:** `journalctl -t draftbot-notify --since -7d` shows any failed backup or renewal.
- **Every month:** run `restore.yml` to prove the newest backup restores, and apply any
  infrastructure updates Dependabot merged by deploying the latest release.
