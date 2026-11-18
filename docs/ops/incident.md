# Incident checklist

When players say the bot is broken, or an alert fires. Work down the list; most incidents end
at step 3.

## 1. Look

- [ ] Which alerts are firing? Grafana's Overview (SSH tunnel,
      [observability.md](observability.md)), Prometheus's **Alerts** page, or the alerts
      channel. Open each one's section in [alerts.md](alerts.md).
- [ ] Is Discord itself having trouble? https://discordstatus.com. If so, wait: effects retry,
      and timers resume with grace when things recover.
- [ ] On the server, in `/opt/draftbot`:
      ```bash
      sudo docker compose ps
      ```
      Every service it lists should be `healthy`. The one-shot `migrate` and `certbot` don't
      run all the time, so only `ps -a` shows them (`migrate` exited 0).

## 2. Say so

- [ ] Tell the community's staff what you see and that you're on it. If matches are stuck, ask
      them not to void anything yet.
- [ ] Note the time it started: you'll want it for the logs.

## 3. Find the broken piece

| Symptom | Look at |
|---|---|
| "This interaction failed" on every click | `bot`: `sudo docker compose logs --tail 200 bot` |
| Clicks work but boards and DMs lag | The outbox: [OutboxBacklog](alerts.md#outboxbacklog), the admin's Outbox effects |
| Timers don't move on | `scheduler`: [DeadlinesOverdue](alerts.md#deadlinesoverdue) |
| The web UI or admin doesn't load | `edge`, then `web`: [EdgeDown](alerts.md#edgedown), [WebErrorRateHigh](alerts.md#weberrorratehigh) |
| Everything fails at once | The database: [PostgresDown](alerts.md#postgresdown), [PgbouncerDown](alerts.md#pgbouncerdown), then `df -h` |
| Certificate warning in the browser | [CertificateExpiringSoon](alerts.md#certificateexpiringsoon) |
| One match stuck, the rest fine | That match's lines: `sudo docker compose logs bot scheduler \| grep '"match": <id>'`; staff can `/match status` and `/match void` |

Useful everywhere:

```bash
sudo docker compose logs --since 30m bot scheduler web | grep '"level": "ERROR"'
sudo docker compose exec bot python manage.py check_ledger
sudo journalctl -t draftbot-notify --since today
```

## 4. Fix

- [ ] A stuck or crashed service: `sudo docker compose restart <service>`. State lives in the
      database, so restarting the bot or scheduler is safe at any time; the scheduler gives
      past-due timers 60 seconds of grace.
- [ ] A bad upgrade: roll back ([upgrades.md](upgrades.md#roll-back)).
- [ ] A bad secret: rotate it ([secrets.md](secrets.md)).
- [ ] A full disk: [DiskSpaceLow](alerts.md#diskspacelow).
- [ ] Damaged data: stop `web`, `bot` and `scheduler` and restore the newest good backup
      ([backups.md](backups.md#replace-the-live-database-with-a-dump)). Take one of the broken
      state first, for later.
- [ ] Anything that rewrites results or ratings is done by staff in Discord (`/match rescore`,
      `/match void`), never by editing the database: the ledger is append-only.

## 5. Check it's over

- [ ] `sudo docker compose ps`: all healthy.
- [ ] The Overview dashboard: alerts resolved, overdue timers 0, the outbox drained.
- [ ] A staff member clicks through the queue panel or a live match.
- [ ] `check_ledger` passes.

## 6. Afterwards

- [ ] Write down what happened, when, what fixed it, and what would have caught it sooner.
- [ ] If a code bug caused it, open an issue with the log lines and the match ID.
- [ ] If an alert was missing or its runbook wrong, fix the rule in
      `infra/observability/prometheus/rules/` and its section in [alerts.md](alerts.md).
