## Acknowledgments
Thank you to \_bacon_ for the base build. This project started from their Bebot draft bot. Without their work, PUGs would be in rigor mortis and none of our current community would be possible.

Thanks to datsir for porting Bebot's standalone draft, priority list, pings and error channel,
which these versions are built from.

A big shout out to the ZA Deadlock community for playing in the inhouses, giving feedback and helping shape how the bot works.

---
# dl-mm-discord

A Discord bot that runs a 6v6 Deadlock inhouse from queue to results: FIFO queue, ready check,
captains and their check-in, player draft and swaps, champion pick/ban, an automatic lobby,
screenshot reporting, OpenSkill ratings with MVP and key-player awards (with NeatQueue's points
carried over while the server cuts over), a leaderboard channel, and optional score OCR.

Python, Django and Postgres. One codebase and one image, running as two processes: `bot`
(discord.py) and `web` (the Django admin and the staff calibration dashboard).

This README is for whoever runs the bot. Players have the
[wiki](https://github.com/VARSITYLUNCHBUG/dl-mm-discord/wiki), a short guide to playing a match,
subs, strikes, ratings and commands. Bugs and ideas go in
[issues](https://github.com/VARSITYLUNCHBUG/dl-mm-discord/issues); the wiki's
[Giving Feedback](https://github.com/VARSITYLUNCHBUG/dl-mm-discord/wiki#giving-feedback) says what
to include.

## Run it

1. Create an application and bot in the
   [Discord Developer Portal](https://discord.com/developers/applications). No privileged intents
   are needed.
2. Invite it, replacing `YOUR_APP_ID`:
   ```
   https://discord.com/oauth2/authorize?client_id=YOUR_APP_ID&scope=bot+applications.commands&permissions=281475298741265
   ```
3. Copy `.env.example` to `.env` and fill in `DISCORD_TOKEN`, `DISCORD_GUILD_ID`,
   `DJANGO_SECRET_KEY` and `POSTGRES_PASSWORD`. Use the same password in `DATABASE_URL`.
   Generate a secret key with:
   ```bash
   uv run python -c "import secrets; print(secrets.token_urlsafe(50))"
   ```
4. Start everything. This also runs migrations and loads the presets:
   ```bash
   docker compose up -d --build
   ```
   To use the published image instead of building, run `docker compose pull` and then
   `docker compose up -d`. The image is `ghcr.io/varsitylunchbug/dl-mm-discord`, listed under the
   repo's Packages. It's built from `main` without score OCR: `latest` and `main` follow `main`,
   and `sha-<commit>` pins one build.
5. In Discord, run `/setup pug_role:@PUGS` as the server owner or an Administrator. It creates
   the queue, Waiting Room, results, leaderboard, archive and staff-alerts channels, and it is
   safe to run again. With a PUG role, only that role sees the queue, Waiting Room, results and
   leaderboard, and only it can use `/leaderboard`; without one, everyone can. Then give your
   staff roles their areas with `/permissions grant` (see [Permissions](#permissions)).
6. Create an admin login for `http://127.0.0.1:8000/admin/`:
   ```bash
   docker compose exec web python manage.py createsuperuser
   ```

The admin binds to localhost. Put a TLS reverse proxy in front of it before exposing it, and set
`BEHIND_TLS_PROXY=true`, `SECURE_COOKIES=true` and `CSRF_TRUSTED_ORIGINS`.

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
| **Check ledger** on Rating runs, and the calibration dashboard | Everything players use |

Saving in the admin goes through the same code the bot uses, so it checks what the bot checks
(screenshot reading must be installed, a region must be one deadlock-api knows, a mode must be
valid) and the queue panel and `#leaderboard` redraw within seconds. The server's channel and role
IDs are shown on its page but can't be edited there: they come from `/setup`, so run it again to
change them.

**Upgrading an older install.** The migrations were squashed into one `0001_initial` when scrims,
staff areas and the staff channel came in. A database created before that can't be migrated
forward: back it up, start a fresh one, and run `/setup` and `/permissions grant` again. Databases
created since migrate normally; the migrate step runs on every `docker compose up`.

## How a match runs

| Step | What happens | Clock and fallback |
|---|---|---|
| Queue | Join and Leave buttons, FIFO. Voice isn't required | Blocked by a cooldown or a live match |
| Pop at 12 | Creates a private text channel, `match-12`. The Waiting Room is the lobby's voice: there's no lobby voice channel | Queue waits at `max_concurrent_matches` |
| Gather | In the Waiting Room: nothing to do. Anywhere else: DM with a Waiting Room invite and Ready button. DMs closed: mention in the match channel | |
| Ready | Ready button on the board and in the "Ready Up" DM. The board is posted right after the lobby ping, before the invites go out. As players ready, the ping is edited to mention only those still to ready (an edit pings nobody) | 180 s. A miss frees the spot, offered down the priority list (the queue, longest wait first). Unfilled in 2 min: cancel, and everyone left goes back to the front of the queue |
| Captain vote | Everyone votes for up to two captains, themselves included, from players with 5 completed matches. Most votes wins; rating breaks ties and fills any gap. Two or fewer eligible, or the Auto Captain setting on: no vote, captains are appointed by experience and rating | 45 s, or closes early once everyone has voted |
| Captain check-in | Each captain presses **I'm here** before anyone is drafted | 60 s (`captains.checkin_seconds`). A captain who misses it is replaced by the next eligible player in vote order, who gets the full time. With nobody eligible left, the draft starts with the captains it has |
| Player draft | `FSSFFSSFFS`, lower-rated captain first. Last player is assigned. No message announces it: the board shows the captains and whose pick it is | 45 s, then highest rated |
| Team voice | Creates `Match 12 · Kestrel's Team` and the other team's channel, and moves anyone in the Waiting Room. Everyone else gets a "Teams picked" DM with the invite | Never blocks the draft |
| Captain coinflip | The winner chooses a side: 🔶 Hidden King or 🔷 Archmother. The Hidden King is always Pick 1 (team 1) and bans and picks first. (Scrims keep Bebot's two-captain coinflip.) | 20 s, then a random side |
| Player swap | From the coinflip until the game starts, a captain can press **Swap players** to offer one of their players for one of the other team's. Captains stay put. The other captain accepts and the two change teams and voice channels, or declines | 60 s to answer, then it lapses. One offer at a time |
| Champion draft | The mode's ban and pick order, from the team the coinflip put first. 🎲 Random takes a champion on purpose | 40 s a turn. A timeout takes a random champion, for bans too |
| Draft summary | Named like "Crimson Wolf", with a GIF from `presets/draft_gifs.json` and GLHF, above the lobby code prompt | |
| Lobby | deadlock-api's bot always creates the custom lobby; its code is posted and a captain presses Start match. Only if that fails is a random captain asked to create one and enter its code, with the settings checklist | No lobby in 3 min counts as a failure. Then 3 min for the host, then the other captain, then cancel |
| Report | Press the team that won, then add the screenshot, and optionally the Deadlock match ID, MVP and key players. With score OCR on, the screenshot is read | 3 h without a report goes to staff |
| Confirm | The other captain confirms, disputes or adds a screenshot | 5 min. Silence confirms |
| Results | First screenshot, the rating table, 🏅 MVP and ⭐ key players, and scoreboard stats go to the results channel. Every screenshot goes to the archive | Effects retry |

This is the flow the server used with Bebot and NeatQueue, and it is the only one: every match
runs it. The timers and the ban and pick order live in the draft mode. These values are starting
judgements, not published standards.

| Mode | Champion draft |
|---|---|
| `draft_3ban` (default) | `B1 B2 B1 B2 P1 P2 P2 P1 P2 P1 B2 B1 P2 P1 P1 P2 P1 P2`: 18 steps, 3 bans a team, 40 s a turn. 1 is the Pick 1 team |
| `bebot_2ban` | Bebot's 16-step, 2-ban order, 40 s a turn |

Switch on the server's page in the admin (**Active mode**). Bebot's custom hero emojis are in
`presets/champion_emojis.yaml`. Load them with `manage.py load_champion_emojis`. The bot must be in
the server that owns them. Heroes Bebot showed with a plain emoji (Apollo 🗡️, Billy 🐐 and so on)
are in the same file's `unicode` section. `load_presets` loads those on every start, filling only
heroes that have none, so an edit in the admin is kept.

### Subs

Any player can press **Request a sub** on the board from the ready check until a result is
reported. There are two separate flows:

| Flow | What happens | Clock and fallback |
|---|---|---|
| Sub out, yourself | Opens the slot straight away | The match pauses until the slot is filled |
| Sub out, a teammate | A captain asks for one of their own players or an undrafted one. Not another captain | The other captain approves within 60 s, or the player stays |
| Sub in, named | The leaving player or their captain picks someone, who gets a DM to accept | 45 s to name someone, 60 s for them to accept |
| Sub in, offered | If nobody is named, or the named person says no, the spot is offered by DM down the priority list: whoever in the queue has waited longest | 60 s each, and it's retried as people join |

While any request is pending, the timer is parked and the board hides the phase's buttons (except
the result buttons once the game is on). The sub takes the leaving player's team, captaincy,
lobby-host role and result. The timer resumes where it stopped, with at least 15 s. Nobody in
3 minutes means the match is cancelled with no rating change, and everyone except the leaving
player goes back into the queue. Once captains are set and before the game, it restarts instead
(see below). At most 4 requests can be pending at once.

Subbing yourself out after the ready check is a dodge, and once the game is on it's a leaver;
cancelling the request costs nothing. See [Captains and dodge strikes](#captains-and-dodge-strikes).
All of these timers live in the draft mode's `subs` section.

### Filling an opening

The queue is the way into matches, and the priority list is the queue in order of wait. An
opening (a missed ready check, a sub out nobody named, or a restart) is offered down the priority
list: whoever in the queue has waited longest, isn't in a match and hasn't stepped out. Being in the
Waiting Room doesn't count: it's a public channel, and not everyone there wants to play. Each offer
is a DM, and only a DM, with **I'll sub in** and **Can't right now**, for 60 s, then the next
person. Someone whose DMs are closed is skipped. Each person is offered one spot at a time.

A missed ready check keeps the lobby: the players who missed it are taken out (with their usual
missed-ready cooldown), their spots are offered for 2 minutes (`ready_check.refill_seconds`), and
once they're filled the captain vote starts. If they aren't, the lobby is cancelled and everyone
still in it goes back to the front of the queue.

A sub out nobody fills after captains are set, but before the game starts, restarts the lobby
rather than cancelling it. The match is voided (its draft history is kept exactly as it was) and
a successor match takes over its channels and everyone who stayed. The empty seats are offered
the same way, and once they're filled a fresh captain vote starts. Unfilled, it's cancelled as
above. Before captains are set, an unfilled sub out still cancels; once the game is on, the
early-leave rules apply.

## The match channel

Players can chat freely, and the board stays at the bottom:

- **Pings** sit just above the board. A status change deletes the earlier ones, and so does a
  new lobby host or a repeat staff request. Chat is never deleted.
- **A state change** edits the board if it's the last message. Otherwise a new board is posted
  at the bottom and the old one deleted.
- **Chat** moves the board once three messages sit below it and chat has been quiet for 5 s, or
  20 s after the third message if chat doesn't stop. A board that moves mid-click could cost a
  captain a wrong ban, so it doesn't move on every message. Change this with the `BOARD_MOVE_*`
  values in `league/services/effects.py`.
- **The champion draft is Bebot's board**: 🏆 Draft #N with its name, 👑 Captains with the
  timer on the captain whose turn it is, 🚫 Bans, each side's heroes one per line ("(random
  choice)" for 🎲, "(randomed)" for a timeout), and the bracketed turn strip, in the acting
  side's colour. Under it, each team's rating and chance to win, and "Ban 3 of 4. Next: Pike
  picks." The finished draft ends in `# GLHF` with a GIF.
- **Choices are buttons**, so everything is visible at once. Champions are red to ban and green
  to pick. Drafted players and taken champions stay in place, greyed out, so nothing shifts under
  a click. The champion grid has messages of
  its own directly below the board, split evenly over two because Discord allows 40 components per
  message, with Random at the end. They are posted afresh each turn rather than edited, so no
  "(edited)" tag splits the grid. A roster above 55 falls back to dropdowns.

The bot only learns that a message was sent. It doesn't have the Message Content intent, so it
can't read chat.

## Runtime settings

Each server's switches live in **Runtime settings**, on the server's page in the admin (and in a
list of their own). That is the only place they change. Saving applies them at once, with no
restart, and redraws the queue panel; changing the interim switch, start points or K-factor also
rebuilds the points and the leaderboard.

| Setting | Default | What it does |
|---|---|---|
| Auto Captain | Off | On: captains are appointed by experience and rating, with no vote. Off: players vote. Scrims are unaffected |
| Open match voice | Off | On: anyone in the server can see and join a match's voice channels. Off: only its players and match staff |
| Match channel close minutes | 3 | How long a finished match's text channel stays before it's deleted |
| Max concurrent matches | 12 | Ranked matches at once; the queue waits beyond this |
| Score OCR | Off | Reading report screenshots: off, stats only, or on |
| Lobby region | Automatic | Where deadlock-api creates each custom lobby |
| API results | On | Check reported results against Deadlock's match history |
| Interim points, start points, K-factor | Off, 1000, 32 | The NeatQueue interim (see [NeatQueue interim](#neatqueue-interim)) |

These used to be fields on the server's row. Migration `0003` moves each server's values across.

## Adding things without code

**A champion.** In admin, add a row under Champions, using the
[Deadlock API](https://api.deadlock-api.com/v1/assets/heroes?only_active=true) hero ID. Or run
**Sync with Deadlock API** on the Champions list, which shows the differences and asks before
applying them. Disable champions rather
than deleting them. New lobbies use the change; live matches keep the pool they started with.

**A draft mode.** In admin, open a mode under Draft mode versions, edit the JSON and save. Saving
always writes a new version, and it is refused with a readable error if the format can't work. Then
choose it as the **Active mode** on the server's page, which only offers each mode's latest version.
Live matches keep the version they started with. To ship one with
the code, add a YAML file to `presets/`; `presets/bebot_2ban.yaml` is the reference.

A mode sets the timers, the team size, the player draft order and the champion ban and pick order,
and can exclude champions. The flow itself isn't configurable. In the steps, `first` is the team the
coinflip made Pick 1.

Version 1 supports sequential bans and picks, with counts and per-step timers. Simultaneous and blind
steps are rejected until the engine implements them.

**Switching an existing server to the default.** A server set up before `draft_3ban` became the
default keeps the mode it had. Choose `draft_3ban` as its Active mode once to move it.

## Ratings

OpenSkill Plackett-Luce (`league/domain/openskill_v1.py`). Each player has a skill estimate (mu,
starting at 25) and an uncertainty (sigma, starting at 8.33). After the library's update:

| Rule | Starting value |
|---|---|
| Placement: a player's first rated matches | 10 |
| During placement, a game moves mu by at most | 3 |
| MVP share of a win / of a loss | ×1.20 / ×0.80 |
| Key player share of a win / of a loss | ×1.10 / ×0.90 |
| Most an award moves one player's mu in a game | 0.5 |
| Awards apply | after placement |
| Sigma never drops below | 2 |
| Sigma grows, in quadrature, per 14 days without a game, up to 6 | 0.5 |

Awards are zero-sum within each team: the MVP and key players take a bigger share of their team's
update, and their teammates a smaller one, so a team's total change is what it would have been
without them. The shown rating is the conservative `max(0, mu − 3 × sigma) × 40`. A new player
shows 0 and climbs as the system becomes sure of them, and a high seed (`/rating seed band:high`,
mu 35) also starts low on purpose. Player lists show only the rating; `/stats` shows how many
placement matches a player has played. Tiers are Bronze, Silver from 10, Gold 18, Platinum 25 and
Diamond 30, on `mu − 3 × sigma` (shown ratings 400, 720, 1000 and 1200).

Captain tie-breaks, the first player pick and auto-picks compare mu, not the shown rating, so a
strong player still in placement isn't treated as weak. After the player draft, each team heading
on the board shows its chance to win, with ⚠️ outside 40–60%. That is information only.

All the values live in each season's `rating_params`, over the defaults, and are fixed once the
season has rated a match. Start a new season with fresh ratings with the **Start the next season**
action on the server's row in the admin, which asks for any new values as JSON. Or from a shell:

```bash
uv run python manage.py start_season --params '{"beta": 3.5}'
```

The values are judgement, not measured. Check them on the staff dashboard, or with:

```bash
uv run python manage.py rating_calibration
```

```bash
uv run python manage.py rating_calibration --params '{"beta": 3.5}'
```

```bash
uv run python manage.py rating_calibration --simulate 300
```

The first prints Brier score and log loss against always saying 50%, calibration bins and the
Hidden King win rate with 95% intervals. The second compares candidate parameters without writing
anything. The third runs a synthetic league.

**Placement counts games, not sigma.** With 12 players a match, sigma shrinks slowly: in a 40-match
synthetic league it was still about 7.1 after 24 games, from 8.33. So the cap and the awards switch
at `placement_games` rated matches instead.

Ratings are a ledger, not a column. `rating_events` is append-only and enforced by database
triggers, and `player_ratings` is a projection that can be rebuilt from it. Rows carry exact
decimal `mu_delta` and `sigma_delta`, so the projection is the start plus the sum. A correction,
including awards that arrive late, appends differences and never rewrites history.
`/match explain` shows the trail. Migrations are generated by `makemigrations` and never edited:
the triggers are installed after every `migrate` by `league/db_guards.py`.

## NeatQueue interim

The server cuts over from NeatQueue, so players' NeatQueue points keep counting until staff
switch to OpenSkill. Export each player's NeatQueue rating, wins and losses to a CSV and import it:

```
discord_id,name,rating,wins,losses
123456789012345678,Kestrel,1240,40,22
```

In the admin, **Import NeatQueue CSV** on the Interim ratings list takes the file, shows a preview
(who is imported, the highest points, any lines it skipped) and imports on Confirm. The header
may name the columns (`discord_id`/`id`, `rating`/`points`/`mmr`, `wins`, `losses`, and `name`
optionally), or leave it out to read them in that order. Importing again replaces the earlier
import. Confirming turns the interim on.

While it's on, each completed match moves every player's points Elo-style on the two teams'
average points: a win gains `K × (1 − expected)` and a loss costs `K × expected`, so an even match
moves 16 with the default K of 32. Players who weren't in the import start at 1000. The
leaderboard channel, `/leaderboard`, `/stats`, the board and the results post show the points and
the NeatQueue record plus matches played here. OpenSkill keeps rating every match underneath and
still drives captain tie-breaks, the first player pick and auto-picks.

The points are rebuilt from the import and the season's completed matches on every result and
correction, so a rescore or a void puts them right by itself. Turning **Interim points** off in
Runtime settings is the cutover: players see the OpenSkill rating from then on. The start points and K-factor are
runtime settings; changing them rebuilds the points as if they had always applied.

## Leaderboard

`#leaderboard` lists every player with a record: rank, rating (points during the interim), wins
and losses, and win rate. The bot keeps it up to date after every result, correction and rating
change, over as many messages as it takes. `/leaderboard` shows a player their own line of it.
With a PUG role set, only that role sees the channel and can use the command.

## deadlock-api: Steam links, result checks and lobbies

[deadlock-api.com](https://deadlock-api.com) is a community-run API for Deadlock match data. It's
unofficial, so everything here degrades to the manual flow when it fails. `DEADLOCK_API_KEY` is
optional and raises its limits. The lobby region and result checks are runtime settings, and the
server's page in the admin shows how checks have gone and how many players are linked.

**Steam links (optional).** `/link` takes a Steam profile link, SteamID64 or friend code and shows
the Steam name to confirm. Custom profile links (`/id/name`) need `STEAM_WEB_API_KEY`. One Steam
account per player and one player per account. A link becomes verified the first time
deadlock-api shows that account on the player's own team. `/unlink` removes it, and staff can
`/deadlock unlink` anyone. Linked Steam names also help score OCR match scoreboard names.

**Result checks** (on by default). When a match has a Deadlock match ID, from the bot's lobby, a
captain's report or the scoreboard, its metadata is fetched once a result is reported. deadlock-api
only has a custom match after someone's game client sends it in, so a miss is retried for about
four hours. Then:

| deadlock-api shows | What happens |
|---|---|
| The other team won | An unconfirmed result goes to disputed; a confirmed one pings staff |
| A linked player on the other team, or none of the linked players | Staff are pinged |
| Everything agrees | Links are verified, and the game's MVP and key players (`mvp_rank` 1 to 3) become the awards when all three are linked players |

Nothing is overturned automatically. Staff can set or correct a match's Deadlock ID, and check it
again at once, with `/deadlock check`. Awards from deadlock-api replace a captain's picks and the
scoreboard's, but never staff's. The results post shows each linked player's hero, K/D/A and
damage from the API when there was no scoreboard read.

**Lobbies** (always; set the region in Runtime settings, such as `south_africa`). When the
champion draft ends, deadlock-api's bot creates the custom lobby and the code is posted. Players
join and sit on their side, then a captain presses **Start match** on the board. The bot leaves
the lobby 15 minutes after creating it, whatever the lobby is doing, so start within that window.
If the lobby can't be made, or isn't made within the lobby code time, the host is asked to create
one and enter its code; the board has no code button until then. Once the match starts, its
Deadlock match ID is fetched, so the result can be checked without anyone typing it. Without an
API key, deadlock-api allows 10 lobbies an hour from one IP.

## Calibration dashboard

`/admin/calibration/`, behind the Django staff login (the header's View site link goes there). It
shows, per season:

- Brier score and log loss against always saying 50%
- a calibration chart of predicted chance against how often it came true, with 95% intervals
- the favourite's and Hidden King's win rates
- how many players are still in placement, and the spread of uncertainty
- whether awards mean anything: how award holders do in their next 5 matches against the
  prediction, next to everyone else
- whose award share is frozen, and how many players left a game early
- awards by source, the most MVPs, score OCR reads and deadlock-api checks

Paste candidate parameters to see what they would have done. Every number is replayed in memory,
so nothing is written.

## MVP and key players

Deadlock's scoreboard marks one MVP and two key players. They reach the rating in four ways, and
a later one replaces an earlier one only if it ranks at least as high:

1. **The report form.** Optional MVP and Key players pickers. The confirming captain's picks
   replace the reporter's. Awards never cause a dispute.
2. **Score OCR**, when it reads all three badges cleanly and has matched each to a player.
3. **deadlock-api**, from the game's own MVP ranking, when all three are linked players.
4. **Staff**, with `/match awards`. Nothing replaces a staff decision except staff.

Before the result is final, awards are only recorded and the result is rated with them. After,
they go through the same refold as a rescore, and the results post is edited in place.

**MVP farming.** A player whose MVP rate, over 20 or more rated matches, is more than twice what
chance gives (1 in 12) keeps playing normally but gets no award share until the rate drops back.
Staff are pinged the first time. It is worked out from the same history on every replay, so a
later award correction can lift or add a freeze. The values are `farming_min_games`,
`farming_ratio` and `mvp_expected` in the season's parameters.

**Do awards mean anything?** The dashboard and `rating_calibration` compare how award holders do in
their next 5 matches against the rating's own prediction, next to everyone else. If award holders
keep beating it, awards carry skill the rating hasn't caught yet and the share could grow a
little. If the interval spans zero, keep it small, or set the multipliers to 1 to turn it off.

## Score OCR

`scoreocr/` reads a report screenshot: winner, Deadlock match ID, duration, and each player's
name, hero, K/D/A, souls, damage, healing and badge. It's optional, because its dependencies are
large. Build with it:

```bash
INSTALL_OCR=true docker compose up -d --build
```

Then choose a mode in Runtime settings (Score OCR), which refuses anything but off when it isn't
installed. The server's page shows how reads have gone.

| Mode | What a read does |
|---|---|
| `off` (default) | Nothing is read |
| `shadow` | Stores the stats and shows them on the results post. Changes nothing else |
| `on` | Also sets the MVP and key players, fills a Deadlock match ID the captain left blank, and disputes the report if the scoreboard shows the other team won |

The read runs after the report, off the board's path. The scoreboard shows in-game names, not
Discord names, so each team's six rows are matched to its six players by name similarity. In-game
names a captain or staff has confirmed before match exactly. When the match isn't clear-cut, those
rows stay unmatched and the match channel gets a **Match names** button for the captains. Staff can
do it later with `/match names`. Every answer is remembered for next time. A read that fails, or
isn't a scoreboard, is recorded and the result stands without it.

## Captains and dodge strikes

**Captains need 5 completed matches** in this server, across seasons, so a newcomer can't be
troll-picked. A player carrying 3 or more strikes can't captain either. Both values are in the draft
mode's `captains` section (`min_games`, `max_strikes`). On the board, players who can't captain show
🔒 and their count, and can't be voted for. With two or fewer eligible players in a lobby, the vote
is skipped: those players captain and any gap is filled by the most completed matches. If a captain
subs out and the sub can't captain, the teammate with the most completed matches takes over. Staff
can `/captain allow`, `/captain bar` or `/captain clear` anyone.

**Strikes** make repeat offences cost more, and playing works them back off. Each offence adds
strikes: missed ready check 1, dodge 2, leaver 3, false report 3. The cooldown comes from the
kind's ladder, one rung higher for every strike the player already carries, from any kind:

| Kind | Cooldown by rung, in minutes |
|---|---|
| Missed ready check | 5, 15, 60, 180, 720 |
| Dodge | 60, 360, 1440, 4320, 10080 |
| Leaver | 120, 720, 2880, 10080 |
| False report | 1440, 4320, 10080 |

Every 3 clean completed matches removes a strike, and so does each 14 days without an offence. The
player is told when a strike comes off, and the queue's refusal and `/stats` say how far they are
from the next. Subbing yourself out after the ready check but before the game starts is a dodge;
during the ready check, or when your captain asks for it, it isn't, and cancelling the request
before it's filled costs nothing. Once the game is on it's a leaver.

**Early leaves.** While the game is on, a captain can press **Someone left in the first 5 min**
and pick who. If the other captain agrees, the match is voided with no rating change: the leaver
gets a leaver penalty and stays out of the queue, and everyone else goes back in. A disagreement,
or no answer in 2 minutes, goes to staff, who can void it with `/match early_leave`. Reports are
open for 20 minutes after the lobby code, or after the bot lobby starts. These timers are the draft
mode's `results` values `early_leave_minutes`, `early_leave_report_minutes` and
`early_leave_answer_seconds`.

**Left early** is marked on a player's match record when they sub out once the game is on, leave
early as above, or show as abandoning in deadlock-api's match data. An abandon inside the first 5
minutes is put to staff.

Strikes are worked out from the facts each time: penalties, completed matches and staff changes. So
voiding a match also takes back the clean game it counted for. `/ban add` puts a player on a queue
cooldown by hand, `/ban revoke` lifts it and removes its strikes too, unless told to keep them,
and `/ban strikes` adds or removes strikes by hand. All the numbers are in each server's `penalty_policy`, editable in admin. They are starting
judgements.

## Scrims and Bebot's tools

Alongside the match flow, the server keeps Bebot's other tools. None of them touches ratings.

### Scrims

`/startdraft` runs a hero ban and pick in any channel, for scrims or anything outside the queue.
Two people press **Become The Hidden King Captain** and **Become The Archmother Captain**, then the
active mode's bans and picks run, The Hidden King first. `/captains_coinflip captain1 captain2`
flips a coin instead: the winner chooses First Pick, Last Pick, 🔶 Hidden King or 🔷 Archmother,
the loser chooses from the other kind, and either captain presses **Start Draft**.

A scrim is a match of its own kind, run by the same engine as a ranked one, so it looks and
behaves the same: Bebot's board, the red-to-ban, green-to-pick grid below it, 🎲 Random, a random
pick when a turn runs out, and the board following the chat. It ends at `# GLHF` with a GIF.

- It's recorded (every ban and pick is kept) and never rated. Its captains aren't held by it, so
  they can queue for ranked meanwhile, and it doesn't count against the server's match capacity.
- Scrims are staff-run: `/startdraft`, `/captains_coinflip` and `/stopdraft` need the Scrims area.
  `/stopdraft` deletes the scrim's messages. `/randomdraft` posts a random ban and pick for both
  sides, for anyone.
- One scrim per channel, and at most 10 at once per server. One whose captains never show up frees
  the channel after 15 minutes.
- The bot never creates, moves or deletes the channel a scrim runs in. It needs View Channel, Send
  Messages and Read Message History there, and Use External Emojis for the hero icons. Without
  that last one, heroes show their plain emoji.

### Priority list

Who in the live match queue has waited longest. Only the queue counts: the Waiting Room is a
public voice channel, so being in it says nothing about wanting to play.

| What happens | The list |
|---|---|
| You join the queue | You go on the back (🟢) |
| You leave the queue | Your place is held for 3 minutes (⏳). Join again in time and you get it back, in the queue too |
| You're put in a match (it pops, you replace someone in the ready check, or you sub in) | You come off |
| Staff take you out of the queue, or clear it | You come off, with no place held |
| A lobby is cancelled | Its ready players go back in the queue and on the list at their old place |
| The match ends | Queue again: you go on the back |

The list isn't posted in any channel. `/prio` tells you, and only you, your place, how long
you've waited and, after leaving the queue, how long your place is held. `/removeprio` takes
someone off (Community area). A match in another server doesn't count.

### Pings

`/pingchannel channel name mention timer [required_role]` sets up a named ping, such as `pugs`
mentioning @PUGS at most every 15 minutes (Community area). Members send it with `/ping message [name]`,
and `/pings` lists a channel's pings and when each is ready. Only the roles and members staff
chose can be pinged: @everyone, @here and anything typed into the message never are. If Discord
refuses a ping, its cooldown isn't used. `/removeping` deletes one.

### Error channel

`/seterrorchannel channel` posts this server's bot errors in a channel, summarised, at most 10 a
minute (Setup area). Only this server's own errors go there. `/clearerrorchannel` stops it. Whoever
runs the bot can also set `ERROR_LOG_CHANNEL_ID` to get every error, from every server, with its
full traceback.

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

### Staff channel

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

## Commands

**Everyone:** `/leaderboard` (needs the PUG role, if one is set), `/stats`, `/queue status`, `/link`, `/unlink`, `/submit` (fallback
for when the report form's upload fails), `/randomdraft`, `/prio`, `/ping`, `/pings`.

**Staff, by area:**

| Area | Commands |
|---|---|
| Setup | `/setup [pug_role]`, `/seterrorchannel`, `/clearerrorchannel` |
| Match control | `/match status`, `/match void\|sub` on a live match, `/match explain`, `/queue_admin kick\|clear` |
| Disputes | Dispute buttons, `/match rescore\|names\|early_leave`, `/match void\|sub` on a finished match, `/match explain`, matching any scoreboard name, `/deadlock check` |
| Ratings | `/rating seed\|adjust`, `/match awards` |
| Moderation | `/ban add\|revoke\|strikes`, `/captain allow\|bar\|clear`, `/deadlock unlink` |
| Community | `/removeprio`, `/pingchannel`, `/removeping` |
| Scrims | `/startdraft`, `/captains_coinflip`, `/stopdraft` |

**Owner and Administrators:** `/permissions grant|revoke|list`.

Server configuration has no commands: it's in the admin (see
[The admin and Discord](#the-admin-and-discord)).

Anything that rewrites past ratings shows a preview and needs Confirm.

## Tables

| Group | Tables |
|---|---|
| Players and ratings | `players`, `seasons`, `player_ratings`, `rating_runs`, `rating_events`, `interim_ratings` and `interim_points_changes` (the NeatQueue interim, rebuilt from the import) |
| Champions and config | `champions`, `draft_mode_versions`, `communities`, `runtime_settings`, `community_role_grants` |
| Queue | `queue_entries` |
| Matches | `matches`, `match_participants`, `match_resources`, `match_transitions`, `draft_actions`, `captain_votes`, `sub_requests`, `sub_offers`, `early_leaves`, `player_swaps` |
| Results | `result_submissions`, `match_results`, `match_awards`, `scoreboard_reads`, `player_match_stats`, `player_aliases`, `api_match_checks` |
| Operations | `penalties`, `strike_adjustments`, `captain_overrides`, `staff_alerts`, `outbox_effects` |
| Bebot's tools | `prio_entries`, `channel_pings` (scrims are `matches` with `kind = scrim`) |

For analytics, start at `result_submissions`. Screenshots are in the archive channel: use
`archive_message_id` and `attachment_id` with the Discord API, because CDN URLs expire. Join
`draft_actions` for picks and bans, `rating_events` for ratings and `player_match_stats` for
scoreboard stats. `deadlock_match_id`, when given, works with
`GET https://api.deadlock-api.com/v1/matches/{id}/metadata`.

## Code layout

```
league/domain/    Pure rules, no Django or Discord: ratings (openskill_v1), strikes and
                  captain eligibility (standing), Steam IDs, mode schema, draft plan, engine
                  (statuses, transitions per kind, the captain coinflip), copy (what players read)
league/models/    The tables
league/services/  Transactions: queue, lobby, draft, results, ratings, corrections, awards,
                  standing, penalties, ocr, steam, api_results, calibration, deadlines,
                  permissions, alerts (the staff channel), runtime (each server's settings),
                  and Bebot's tools: scrims, prio, pings
league/integrations/  The deadlock-api client. Network only, no database
league/web/       The staff calibration dashboard
league/admin/     Django admin
bot/handlers/     Clicks and modals: validate, call a service, acknowledge. permissions.py holds
                  the staff area checks every command and button uses
bot/commands/     Slash commands
bot/renderers/    State to Discord components, with no I/O. style.py is the one look (Bebot's
                  colours, titles and turn strip); board.py renders ranked matches and scrims;
                  names.py names the channels the bot creates
bot/effects/      Runs Discord side effects from the outbox, with retries
bot/error_log.py  Posts ERROR logs to each server's /seterrorchannel channel
scoreocr/         Scoreboard screenshot reader, used through league/services/ocr.py when installed
```

The rules that keep it reliable:

- **Handlers are stateless.** A `custom_id` holds the action, match and step, and the rest comes from
  the database. Old buttons survive a restart, and a stale click gets a polite refusal.
- **Races end in the database.** Row locks, `version` and `step_index` checks, and unique keys.
- **Timers are rows.** A poller applies timeouts through the same path as a click. After downtime,
  past-due deadlines get 60 s of grace.
- **Discord calls happen after commit.** State changes write `outbox_effects` in the same transaction,
  and a worker runs them in order per lane, retrying on server errors. Each match (or scrim) is a
  lane, and other work gets one lane per kind and server, so one that keeps failing never holds up
  another.

## Operations

```bash
docker compose logs -f bot
```

```bash
docker compose exec bot python manage.py check_ledger
```

(The same check is **Check ledger** on the admin's Rating runs list.)

```bash
docker compose exec db pg_dump -U draftbot draftbot > backup.sql
```

`rebuild_ratings` recreates `player_ratings` from the ledger. It never writes to the ledger itself.
Back up the database daily: the volume is the only copy of match history and ratings.

Check the Outbox effects page in admin, filtered to `failed`, if channels aren't being created or
cleaned up. The bot's healthcheck fails if its loops stop updating the heartbeat file.

## Development

Postgres runs in Docker on port 55432. System Python isn't needed; `uv` manages it.

```bash
docker compose up -d db
```

```bash
DEBUG=true uv run pytest
```

```bash
uv run ruff check bot league config tests manage.py && uv run ruff format --check bot league config tests manage.py
```

```bash
DEBUG=true uv run mypy bot league config
```

Run the bot on your machine, without building an image:

```bash
DEBUG=true uv run python manage.py migrate
```

```bash
DEBUG=true uv run python manage.py load_presets
```

```bash
DEBUG=true uv run python manage.py runbot
```

## Check before launch

- Rating convergence. In simulation a strong player seeded as new takes 29 to 81 games to reach
  mu 30. A 6v6 game moves mu well under the 3-point placement cap, so the cap isn't what slows it:
  the per-game step is, and `beta` barely changes it with 12 players. Seeding known players with
  `/rating seed` helps most. A higher starting `sigma` helps a little (12 gave 15 to 72 games) but
  keeps shown ratings at 0 for longer; try it with
  `rating_calibration --simulate 300 --params '{"sigma": 12}'`.
- deadlock-api's custom lobby start uses the party ID from creation as the lobby ID. Confirm it
  with one real lobby, and that the bot's lobby can be joined and started as described.
- Voice invite links and modal screenshot upload on desktop, mobile and web.
- Current custom-lobby steps, for the host checklist text in `bot/renderers/board.py`.
- Behaviour after Discord's 16 November 2026 channel change. Every channel the bot creates already
  grants the bot its own `VIEW_CHANNEL`.
