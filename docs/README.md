# Documentation

Everything past the [README](../README.md). Players have their own short guide in the
[wiki](https://github.com/VARSITYLUNCHBUG/DayShift/wiki).

## Running the bot for a server

| Page | What it covers |
|---|---|
| [Quick start](quickstart.md) | The whole stack on one machine, and setting up the Discord server |
| [How a match runs](match-flow.md) | Every step and its timer, draft modes, subs, filling openings, the match channel |
| [Captains and strikes](captains-and-strikes.md) | Who can captain, the strike ladders and cooldowns, early leaves |
| [Ratings](ratings.md) | OpenSkill, placement, tiers, awards, seasons, the NeatQueue interim, the leaderboard, calibration |
| [deadlock-api and score OCR](integrations.md) | Steam links, result checks, the bot's custom lobby, reading scoreboard screenshots |
| [Scrims and Bebot's tools](scrims-and-tools.md) | Scrim drafts, the priority list, named pings, the error channel |
| [The admin and staff](admin.md) | What's in the admin, runtime settings, champions and draft modes, permissions, the staff channel |
| [Commands](commands.md) | Every slash command, by who can use it |
| [The player web UI](web-ui.md) | Playing on the web: sign-in and privacy, live updates, running and testing it locally, deploying it |

## Hosting it

| Page | What it covers |
|---|---|
| [Deploy guide](../deploy/README.md) | Installing it on a client's server with Ansible, and running it: upgrades, backups, restores, secrets, health alerts, launch checks |

## Working on the code

| Page | What it covers |
|---|---|
| [Architecture](architecture.md) | The services, how a click and a timer reach Discord, the code layout, design decisions |
| [Developer guide](dev/README.md) | The local stack against a Discord simulator, the control panel, checks and tests |
| [Database tables](database.md) | What each table holds, and where to start for analytics |
| [Contributing](../CONTRIBUTING.md) | How to propose a change and get it merged |
| [Brand](brand.md) | The logo and its files, colour tokens, type and voice |
