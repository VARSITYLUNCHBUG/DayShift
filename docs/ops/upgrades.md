# Upgrades and rollbacks

An upgrade moves a client's server to another app image, and ships whatever changed in the
compose files and in `infra/` with it. Run it from a checkout of the same release: the compose
files and the edge, pgbouncer and observability configuration are copied from your checkout.

## What gets released

CI builds the app image once, scans it, and publishes that same image to
`ghcr.io/varsitylunchbug/dl-mm-discord` once every check (the browser suite included) has passed
on a push to `main` or a version tag:

| Tag | Moves | Use |
|---|---|---|
| `sha-<commit>` | never | What a deploy pins: one build of one commit on `main` |
| `latest`, `main` | with every push to `main` | Trying things; never pin a client to it |
| `1.2.3`, `1.2` | from a `v1.2.3` git tag | Releases, if you tag them |

Each image carries an SBOM and build provenance. The infrastructure images (Postgres, pgbouncer,
nginx, certbot, the observability stack) are pinned to exact versions in the compose files;
Dependabot proposes their minor and patch updates weekly, and they reach a server with the
release that merges them.

## Before you upgrade

1. Read what changed since the server's commit (the `sha-<commit>` tag names it):
   `git log --oneline <old>..<new>`. Look for new migrations
   (`git diff --stat <old>..<new> -- league/migrations`) and new settings in `.env.example` or
   the example inventory's `main.yml`.
2. Pick a quiet time. Each service restarts for a few seconds, and a live match keeps its state
   (timers get 60 seconds of grace after the scheduler restarts), but players notice a bot that
   doesn't answer clicks.
3. Check out the new release on your machine.

## Migrations and the running release

The migrate job runs with the new image while the old `web`, `bot` and `scheduler` are still
serving, and they are only replaced afterwards, one at a time. So each release's migrations have to
work with the code before them as well as after: columns are added before the code that needs
them, and dropped or renamed only a release after the code stops using them
([the developer guide](../dev/README.md#writing-a-migration) asks this of every migration). A
failed rollout leaves the old services running on the new schema, which is safe for the same
reason.

If a release's notes say a migration can't work that way, stop the bot and the scheduler first
(`sudo docker compose stop bot scheduler` on the server), deploy, and the rollout starts them
again.

## Upgrade

Set the new tag in `draftbot_image_tag` in the inventory, then:

```bash
ansible-playbook -i inventories/acme deploy.yml --ask-vault-pass
```

`-e draftbot_image_tag=sha-<commit>` deploys a tag without editing the inventory (put it in the
inventory afterwards, or the next `site.yml` moves the server back). `deploy.yml`:

1. Prints the tag the server runs now and the one it moves to.
2. Takes a backup and prints its path (`-e deploy_backup_first=false` skips it). Note the path:
   it is your way back if the release migrates the database.
3. Installs the compose files and `infra/` from your checkout and rewrites `.env`.
4. Pulls every image again.
5. Runs the migrate job, if this image hasn't migrated the database before. If it fails, the
   playbook stops here and the running services are untouched: fix it and run again
   (`-e app_force_migrate=true` runs the job even if it succeeded once).
6. Recreates `pgbouncer`, `web`, `scheduler` and `bot` one at a time, each healthy before the next,
   so a broken image stops the rollout at the first service it can't start.
7. Updates the edge (checking its configuration with `nginx -t` before reloading) and fetches
   `https://<domain>/readyz` through it, then updates the observability services.

Then check:

```bash
ssh deploy@<server>
cd /opt/draftbot
sudo docker compose ps
sudo docker compose logs --since 10m bot scheduler web | grep '"level": "ERROR"'
```

and the Overview dashboard: everything up, no overdue timers, the outbox draining.

`site.yml` does all of this too, without the backup and with `missing` instead of `always` for
pulls, so use `deploy.yml` for upgrades.

## Roll back

Deploy the previous tag:

```bash
ansible-playbook -i inventories/acme deploy.yml --ask-vault-pass -e draftbot_image_tag=sha-<old>
```

Migrations only go forward. If the release you're leaving migrated the database, the old image
may not work with it: after deploying the old tag, restore the backup `deploy.yml` printed before
the upgrade:

```bash
ansible-playbook -i inventories/acme restore.yml --ask-vault-pass \
  -e backups_restore_mode=replace -e backups_restore_confirm=true \
  -e backups_restore_file=/var/backups/draftbot/draftbot-<stamp>.dump
```

That discards everything played since the upgrade, so prefer fixing forward when the problem is
small. Check out the old release on your machine before rolling back, so the compose files match
the image.

## The server itself

- **Security updates** install every day by themselves (unattended-upgrades). With
  `base_unattended_reboot: true` the server reboots at 04:00 when one needs it, and the boot unit
  (`draftbot.service`) starts the stack again. `sudo systemctl status draftbot` shows it.
- **Docker** comes from Docker's own apt repository, and the nightly unattended-upgrades run
  upgrades it too (`base_unattended_docker: true`, the default). Running containers survive the
  daemon restart (`live-restore`). With `base_unattended_docker: false`, Docker stays put until you
  run `site.yml --tags docker -e docker_upgrade=true`.
- **Ansible's own tools** are pinned in `deploy/ansible/requirements.txt`; update them with the
  repo.

## The self-host quickstart

In your checkout, on the release you want:

```bash
git pull
docker compose pull          # or, building from source (DRAFTBOT_IMAGE_TAG=local): docker compose build
docker compose up -d
```

`up` runs the migrate job before anything else starts. Take a backup first
([backups.md](backups.md#without-ansible-the-self-host-quickstart)), and set
`DRAFTBOT_IMAGE_TAG` in `.env` to pin a build.
