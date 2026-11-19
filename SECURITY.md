# Security policy

## Reporting a vulnerability

Please don't open a public issue, pull request or discussion for a security problem.

Report it privately on GitHub:
[report a vulnerability](https://github.com/VARSITYLUNCHBUG/DayShift/security/advisories/new)
(the repository's Security tab, then "Report a vulnerability"). Only the maintainer sees it.

Say what you found, how to reproduce it, which image tag or commit you tested, and what an
attacker could do with it. If you have a fix, describe it in the report rather than in a public
pull request: the advisory gets a private fork where we can work on it together.

## What to expect

This is a volunteer project with one maintainer, so these are aims rather than promises:

- An acknowledgement within 7 days.
- An assessment and a plan within 14 days.
- A fix released as soon as it is ready, and a published advisory that credits you unless you'd
  rather not be named.

Please allow a reasonable time for a fix before you disclose publicly; 90 days is the default.

## Supported versions

Fixes land on `main` and ship in the next published image, `ghcr.io/varsitylunchbug/dayshift`
(the `latest` tag, and the newest `v*` tag once there are releases). Older images get no fixes:
upgrade as [deploy/README.md](deploy/README.md#running-it) describes.

## Scope

In scope:

- The bot, the web app and the Django admin.
- The container images, the Compose files and the Caddy edge's configuration.
- The Ansible deploy in `deploy/`.

Out of scope:

- The dev-only tools (the Discord simulator, the control panel and devtools' `/_control/` API).
  They refuse to start without `DEBUG`, so they are only in scope if you can turn them on in a
  production configuration.
- Discord, Valve and deadlock-api themselves.
- Anything that needs an already compromised server or admin account.

## Running it safely

[deploy/README.md](deploy/README.md) covers the secrets and how to rotate them, and
[docs/architecture.md](docs/architecture.md) explains the networks that keep the services apart.
