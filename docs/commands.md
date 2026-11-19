# Commands

Most of a match runs on buttons. Slash commands cover everything else. Players' commands are
explained in the wiki's [Commands](https://github.com/VARSITYLUNCHBUG/DayShift/wiki/Commands)
page.

## Everyone

`/leaderboard` (needs the PUG role, if one is set), `/stats`, `/queue status`, `/link`,
`/unlink [account]`,
`/submit` (fallback for when the report form's upload fails), `/randomdraft`, `/prio`, `/ping`,
`/pings`.

## Staff, by area

Each area is granted to roles with `/permissions grant`; see [Permissions](admin.md#permissions).

| Area | Commands |
|---|---|
| Setup | `/setup [pug_role]`, `/seterrorchannel`, `/clearerrorchannel` |
| Match control | `/match status`, `/match void\|sub` on a live match, `/match explain`, `/queue_admin kick\|clear` |
| Disputes | Dispute buttons, `/match rescore\|names\|early_leave`, `/match void\|sub` on a finished match, `/match explain`, matching any scoreboard name, `/deadlock check` |
| Ratings | `/rating seed\|adjust`, `/match awards` |
| Moderation | `/ban add\|revoke\|strikes`, `/captain allow\|bar\|clear`, `/deadlock unlink player [account]` |
| Community | `/removeprio`, `/pingchannel`, `/removeping` |
| Scrims | `/startdraft`, `/captains_coinflip`, `/stopdraft` |

## Owner and Administrators

`/permissions grant|revoke|list`.

Server configuration has no commands: it's in the admin (see
[The admin and Discord](admin.md#the-admin-and-discord)). Anything that rewrites past ratings shows
a preview and needs Confirm.
