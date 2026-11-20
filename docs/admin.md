# The admin and staff

This is for whoever runs the bot for a server: what lives in the Django admin, the per-server
settings, adding champions and draft modes, and how staff permissions work.

## The admin and Discord

The Django admin is the host's console, and the only place server configuration changes. Discord
keeps what players and staff do day to day.

| In the admin | In Discord |
|---|---|
| Runtime settings: screenshot reading, lobby region, result checks, the interim, capacity | `/setup` (channels, the PUG role) and `/permissions` |
| The active draft mode (on the server's page) and editing modes | Live and finished matches: `/match`, `/queue_admin`, `/deadlock check` |
| Champions, and **Sync with Deadlock API** on the Champions list | Moderation: `/ban`, `/captain`, `/deadlock unlink`, `/removeprio` |
| The NeatQueue import (**Import NeatQueue CSV** on Interim ratings) | Ratings: `/rating seed\|adjust`, `/match awards` |
| Seasons: the **Start the next season** action on the server's row | Pings and the error channel |
| **Check ledger** on Rating runs, and the [calibration dashboard](ratings.md#calibration-dashboard) | Everything players use |

Saving in the admin goes through the same code the bot uses, so it checks what the bot checks
(screenshot reading must be installed, a region must be one deadlock-api knows, a mode must be
valid) and the queue panel and `#leaderboard` redraw within seconds. The server's channel and role
IDs are shown on its page but can't be edited there: they come from `/setup`, so run it again to
change them.

## Runtime settings

Each server's switches live in **Runtime settings**, on the server's page in the admin (and in a
list of their own). That is the only place they change. Saving applies them at once, with no
restart, and redraws the queue panel. Changing the interim switch, start points or K-factor also
rebuilds the points and the leaderboard.

| Setting | Default | What it does |
|---|---|---|
| Auto Captain | Off | On: captains are appointed by experience and rating, with no vote. Off: players vote. Scrims are unaffected |
| Open match voice | Off | On: anyone in the server can see and join a match's voice channels. Off: only its players and match staff |
| Match channel close minutes | 3 | How long a finished match's text channel stays before it's deleted |
| Max concurrent matches | 12 | Ranked matches at once; the queue waits beyond this |
| Queue idle minutes | 90 | How long a player can sit in the queue without checking in before they're taken out, with no penalty ([idle players](match-flow.md#idle-players)). 0 turns it off |
| Queue warn minutes | 5 | How long before that the "Still queueing?" DM goes out. 0: no DM. Must be less than the idle minutes |
| Score OCR | Off | Reading report screenshots: off, stats only, or on ([Score OCR](integrations.md#score-ocr)) |
| Lobby region | Automatic | Where deadlock-api creates each custom lobby |
| API results | On | Check reported results against Deadlock's match history ([result checks](integrations.md#result-checks)) |
| Interim points, start points, K-factor | Off, 1000, 32 | The [NeatQueue interim](ratings.md#neatqueue-interim) |

## Adding things without code

### A champion

In the admin, add a row under Champions, using the
[Deadlock API](https://api.deadlock-api.com/v1/assets/heroes?only_active=true) hero ID. Or run
**Sync with Deadlock API** on the Champions list, which shows the differences and asks before
applying them. Disable champions rather than deleting them. New lobbies use the change; live
matches keep the pool they started with.

Bebot's custom hero emojis are in `presets/champion_emojis.yaml`. Load them with
`manage.py load_champion_emojis`; the bot must be in the server that owns them. Heroes Bebot
showed with a plain emoji (Apollo 🗡️, Billy 🐐 and so on) are in the same file's `unicode`
section. `load_presets` loads those on every start, filling only heroes that have none, so an edit
in the admin is kept.

### A draft mode

In the admin, open a mode under Draft mode versions, edit the JSON and save. Saving always writes a
new version, and it is refused with a readable error if the format can't work. Then choose it as
the **Active mode** on the server's page, which only offers each mode's latest version. Live
matches keep the version they started with. To ship one with the code, add a YAML file to
`presets/`; `presets/bebot_2ban.yaml` is the reference.

A mode sets the timers, the team size, the player draft order and the champion ban and pick order,
and can exclude champions. The [match flow](match-flow.md) itself isn't configurable. In the steps,
`first` is the team the coinflip made Pick 1.

Version 1 supports sequential bans and picks, with counts and per-step timers. Simultaneous and
blind steps are rejected until the engine implements them.

The modes that ship are listed in [Draft modes](match-flow.md#draft-modes).

## Permissions

Staff commands are grouped into areas, and each server grants areas to its own roles: a main admin
role might hold every area, a junior admin Match control and Scrims, a dispute team Disputes. A
member holds every area any of their roles is granted. The server owner and Administrators hold
every area without a grant, so a new server is never locked out.

`/permissions grant role area` and `/permissions revoke role area` change grants (either takes
"Every area"), and `/permissions list` shows them. Only the owner and Administrators can use
`/permissions`; the grants are also editable under Communities in the Django admin. Match staff
(Match control, Disputes and Ratings) can see every match channel and the scoreboard archive.

Discord can't hide commands by these grants, so staff commands are visible to everyone and
refused when they run without the area. `/permissions` alone is hidden from non-Administrators.

[Commands](commands.md) lists which commands each area unlocks.

## Staff channel

Everything staff should look at arrives as a card in `#staff-alerts`, which only staff roles can
see. Each card is tagged with an area and pings the roles holding it:

| Card | Area | Closed by |
|---|---|---|
| A disputed result, or no result reported | Disputes | Its buttons: either team won, or Void. Any Disputes holder can rule |
| A possible early leave the captains disagree on or didn't answer | Disputes | Dismiss, or the match being voided |
| deadlock-api disagrees with the result, or shows an abandon | Disputes | Dismiss |
| The scoreboard shows the other team won | Disputes | Dismiss |
| A player's award share is frozen | Ratings | Dismiss |
| Discord refused to create a lobby | Setup | Dismiss |

A dispute still open after its re-ping time is posted again at the bottom, pinging again, and the
old card is removed. A closed card stays, edited to say who closed it and how. The match channel
gets a short note for disputes and early leaves, without pinging anyone. On a server whose staff
channel isn't set up yet, cards go to the match channel instead.
