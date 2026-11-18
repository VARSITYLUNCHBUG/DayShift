# Backups and restore

The database volume is the only copy of match history, ratings and the ledger. A client install
backs it up every night; this page covers checking those backups, taking one by hand, restoring,
and what else to keep.

Run the playbooks from `deploy/ansible` on your machine, with the client's inventory and the
virtualenv from the [deploy guide](../../deploy/README.md#4-set-up-the-controller) active.

## What runs every night

`draftbot-backup.timer` starts `draftbot-backup.service` at 03:30 server time (UTC by default),
plus up to 15 minutes. It runs `/usr/local/sbin/draftbot-backup`, which:

1. Dumps the database straight from the `db` container (`pg_dump --format=custom`, one consistent
   snapshot; not through pgbouncer) to `/var/backups/draftbot/draftbot-<UTC stamp>.dump`,
   readable by root only.
2. Checks `pg_restore` can read the dump back, and only then keeps it.
3. Deletes dumps older than `backups_retention_days` (14).
4. With `backups_rclone_remote` set, encrypts the new dump with age and copies that offsite
   (never the plain dump), then prunes offsite copies by the same age.

A failed run is logged and, with `vault_notify_discord_webhook_url` set, posted to Discord
([observability.md](observability.md#failure-notices-outside-prometheus)). Check on it with:

```bash
sudo systemctl list-timers draftbot-backup.timer
sudo journalctl -u draftbot-backup --since -2d
ls -lh /var/backups/draftbot
```

Upgrades (`deploy.yml`), secret rotation and a full restore each take a backup first, the same
way.

## Take a backup now

```bash
ansible-playbook -i inventories/acme backup.yml --ask-vault-pass
```

It runs the same service and prints the dump's path. Add `-e backups_fetch_dir=backups` to copy it
to `backups/<host>/` on your machine as well (git ignores that folder). On the server itself,
`sudo systemctl start draftbot-backup` does the same.

## Check a backup restores

A backup you haven't restored isn't proven. This restores the newest dump into a scratch
database, counts its players and matches, and drops it. It fails if the copy holds none while the
live database has some: a dump of an emptied or truncated database restores just as cleanly as a
good one. The live database is only read:

```bash
ansible-playbook -i inventories/acme restore.yml --ask-vault-pass
```

Add `-e backups_restore_file=/var/backups/draftbot/draftbot-<stamp>.dump` to check a particular
one. Do this every month or so, and after changing anything about backups.

## Replace the live database with a dump

Everything since the dump is lost, so the playbook asks for `backups_restore_confirm`:

```bash
ansible-playbook -i inventories/acme restore.yml --ask-vault-pass \
  -e backups_restore_mode=replace -e backups_restore_confirm=true \
  -e backups_restore_file=/var/backups/draftbot/draftbot-20261116T033012Z.dump
```

It takes a backup of the live database first (so a mistaken restore can be undone), stops `web`,
`bot` and `scheduler`, recreates the database empty, restores the dump, runs the migrate job with
the running image, and starts the services again, whatever happened in between. Leave out
`backups_restore_file` for the newest dump, or use `-e backups_restore_upload=<path>` for a dump
on your machine (one fetched from offsite, say).

Discord doesn't roll back with the database. After a restore, live matches the dump doesn't know
about leave their channels behind (delete them by hand), and boards and the leaderboard redraw on
the next change.

## Offsite copies

A dump holds live admin and web sessions, password hashes and every player's Discord ID, so
it only ever leaves the server encrypted, to an [age](https://age-encryption.org) key the server
can't decrypt with:

1. On your machine, make a key pair and keep `draftbot-backups.key` somewhere safe, off the
   server (with the vault's password, say):
   ```bash
   age-keygen -o draftbot-backups.key     # prints the public key, age1...
   ```
2. In the inventory, set `backups_offsite_age_recipients` to that public key (several keys are
   fine), `backups_rclone_remote` to the remote (for example `b2:my-bucket/draftbot`), and put the
   matching `rclone.conf` in `vault_backups_rclone_config`; `rclone config` on your machine writes
   one you can paste. The backups role refuses a remote without a key.
3. Run `site.yml --tags backups`. The next nightly run copies `draftbot-<stamp>.dump.age` there.

To restore from offsite, download the copy with rclone on your machine, decrypt it, then use
`backups_restore_upload` as above:

```bash
age -d -i draftbot-backups.key draftbot-<stamp>.dump.age > draftbot-<stamp>.dump
```

If a dump or the private key gets out, see [secrets.md](secrets.md#if-a-secret-leaked).

## What else to keep

The database is the only thing that can't be rebuilt. To rebuild a server from scratch you also
need:

| What | Where | Why |
|---|---|---|
| The inventory and the vault | Your private repo | Every setting and secret. The vault's password too, somewhere safe |
| The age private key | Your machine, never the server | Without it the offsite copies can't be read |
| `letsencrypt/` | `/opt/draftbot/letsencrypt` | The certificate and the ACME account. Not essential, but Let's Encrypt rate-limits re-issuing the same names, so copy it if you rebuild often |
| Grafana's data | the `grafana-data` volume | Only what you changed in Grafana's UI (users, saved copies). The dashboards are in the repo |

Prometheus's data and the container logs are disposable.

## Rebuilding a server from a backup

1. Point DNS at the new server and run `site.yml` against it as for a new install
   ([deploy guide](../../deploy/README.md)). It starts with an empty database.
2. Copy a dump to your machine (`backup.yml -e backups_fetch_dir=backups` on the old server, or
   from offsite, decrypted) and restore it with `backups_restore_upload`, as above.
3. The bot reconnects to Discord with the same token; channels and roles it made are still there.

## Without Ansible (the self-host quickstart)

In your checkout:

```bash
docker compose exec -T db pg_dump -U draftbot -d draftbot --format=custom > draftbot-$(date -u +%Y%m%dT%H%M%SZ).dump
```

To restore, stop what writes, recreate the database, restore and migrate:

```bash
docker compose stop web bot scheduler
docker compose exec -T db psql -U draftbot -d postgres -v ON_ERROR_STOP=1 \
  -c "DROP DATABASE IF EXISTS draftbot WITH (FORCE)" -c "CREATE DATABASE draftbot OWNER draftbot"
docker compose exec -T db pg_restore -U draftbot -d draftbot --no-owner --exit-on-error < draftbot-<stamp>.dump
docker compose run --rm --no-deps migrate
docker compose up -d
```
