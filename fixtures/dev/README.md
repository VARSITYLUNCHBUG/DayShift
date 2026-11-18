# Dev fixtures

The league a local dev stack starts with. Load them with `manage.py dev_seed`, after
`migrate` and `load_presets`, with `DEBUG=true` and `DEV_CONTROL=true` (the last file is a
devtools model). They load in file name order:

| File | Rows |
|---|---|
| `10_community.json` | The community "Dev League" (pk 1) and its runtime settings: API result checks, score OCR and the NeatQueue interim off, match channels closing 1 minute after a match. Its channels and PUG role are empty: `dev_seed` fills them in |
| `15_staff_grants.json` | Every staff area for the simulator's Staff role (`1100000000000000004`), as `/permissions grant` would give them |
| `20_season.json` | Season 1, open |
| `30_players.json` | 14 players, pks 1 to 14 |
| `40_dev_profiles.json` | Each player's dev profile: the rating `dev_seed` gives them (1600 down to 400), and some champion preferences and bans the autopilot follows |

The IDs match the Discord simulator's seeded world: the guild is `1100000000000000001`, the
Staff role `1100000000000000004`, and the players are `1100000000000000100` to
`1100000000000000113`, the members the simulator makes with `SIM_SEED_USERS=14`.

What fixtures can't hold, `dev_seed` does after loading (see `devtools/README.md`):

- **The draft mode.** The community names draft mode pk 2, which is `draft_3ban` v1 on a fresh
  database after `load_presets`. `dev_seed` loads it pointing at the latest `draft_3ban`
  version instead, whatever its pk.
- **The guild.** When the simulator is up, `dev_seed` lays out its guild the way `/setup`
  does, because the simulator's channel and role IDs only exist once it makes them: the `PUGS`
  role, the `Deadlock` category, the Waiting Room, `#queue`, `#results` and `#leaderboard` for
  the PUG role only, `#scoreboard-archive` for match staff and `#staff-alerts` for all staff.
  It wires their IDs into the community, as `/setup` does, and asks the bot for the queue
  panel and the leaderboard. Anything already there is kept, so running it again changes
  nothing, and so does `/setup` run in the simulator later.
- **Members.** Each fixture player becomes a simulator member with the fixture's name and the
  PUG role. A player who isn't a member yet (the simulator was started with fewer seed users)
  gets one made, and their Discord ID is updated to it.
- **Ratings.** A rating is a projection of the append-only ledger, so it is seeded through
  `ratings.seed_player`, once per player per season, never written as a row.
- **Captains.** The presets let only players with 5 completed matches captain. `dev_seed` gives
  each fixture player a staff `allow` override, so a dev lobby still holds a real vote.

The rows carry explicit pks and timestamps, because fixtures skip `auto_now` and
`auto_now_add`. Loading again over a used database (`dev_seed --reload`) updates these rows in
place; to start clean, use `POST /_control/api/reset` or drop the database.
