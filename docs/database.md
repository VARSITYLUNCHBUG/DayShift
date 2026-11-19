# Database tables

What each table holds, and where to start for analytics. [Architecture](architecture.md) explains
the services around the database, and [Ratings](ratings.md#the-ledger) the rating ledger.

| Group | Tables |
|---|---|
| Players and logins | `players` (Django's user model: one row per Discord account, admin logins included, with `players_groups` and `players_user_permissions`), `steam_accounts` (any number per player, each account linked to one player) |
| Ratings | `seasons`, `player_ratings`, `rating_runs`, `rating_events`, `interim_ratings` and `interim_points_changes` (the NeatQueue interim, rebuilt from the import) |
| Champions and config | `champions`, `draft_mode_versions`, `communities`, `runtime_settings`, `community_role_grants` |
| Queue | `queue_entries` |
| Matches | `matches`, `match_participants`, `match_resources`, `match_transitions`, `draft_actions`, `captain_votes`, `sub_requests`, `sub_offers`, `early_leaves`, `player_swaps` |
| Results | `result_submissions`, `match_results`, `match_awards`, `scoreboard_reads`, `player_match_stats`, `player_aliases`, `api_match_checks` |
| Operations | `penalties`, `strike_adjustments`, `captain_overrides`, `staff_alerts`, `outbox_effects` |
| Bebot's tools | `prio_entries`, `channel_pings` (scrims are `matches` with `kind = scrim`) |

## Analytics

Start at `result_submissions`. Then join:

- `draft_actions` for picks and bans,
- `rating_events` for ratings,
- `player_match_stats` for scoreboard stats.

Screenshots are in the archive channel: use `archive_message_id` and `attachment_id` with the
Discord API, because CDN URLs expire. `deadlock_match_id`, when given, works with
`GET https://api.deadlock-api.com/v1/matches/{id}/metadata`.
