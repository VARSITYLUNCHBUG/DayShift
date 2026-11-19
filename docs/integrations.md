# deadlock-api and score OCR

Two optional ways the bot learns about a game without anyone typing it in: the community
deadlock-api (Steam links, result checks and the custom lobby) and score OCR (reading the
scoreboard screenshot). Both degrade to the manual flow when they fail.

## deadlock-api

[deadlock-api.com](https://deadlock-api.com) is a community-run API for Deadlock match data. It's
unofficial, so everything here degrades to the manual flow when it fails. `DEADLOCK_API_KEY` is
optional and raises its limits. The lobby region and result checks are
[runtime settings](admin.md#runtime-settings), and the server's page in the admin shows how checks
have gone and how many players are linked.

### Steam links

Optional. `/link` takes a Steam profile link, SteamID64 or friend code and shows the Steam name to
confirm. Custom profile links (`/id/name`) need `STEAM_WEB_API_KEY`.

- A player can link several Steam accounts, a main and an alt say. Each account belongs to one
  player.
- A link becomes verified the first time deadlock-api shows that account on the player's own team.
- A player counts as in a match if any one of their accounts is.
- `/unlink account` removes one, and `/unlink` alone removes them all. Staff can do the same for
  anyone with `/deadlock unlink`.
- Linked Steam names also help score OCR match scoreboard names.

### Result checks

On by default. When a match has a Deadlock match ID, from the bot's lobby, a captain's report or
the scoreboard, its metadata is fetched once a result is reported. deadlock-api only has a custom
match after someone's game client sends it in, so a miss is retried for about four hours. Then:

| deadlock-api shows | What happens |
|---|---|
| The other team won | An unconfirmed result goes to disputed; a confirmed one pings staff |
| A linked player on the other team, or none of the linked players | Staff are pinged |
| Everything agrees | Links are verified, and the game's MVP and key players (`mvp_rank` 1 to 3) become the awards when all three are linked players |

Nothing is overturned automatically. Staff can set or correct a match's Deadlock ID, and check it
again at once, with `/deadlock check`. Awards from deadlock-api replace a captain's picks and the
scoreboard's, but never staff's. The results post shows each linked player's hero, K/D/A and damage
from the API when there was no scoreboard read.

### Lobbies

Always on; set the region in Runtime settings, such as `south_africa`. When the champion draft
ends, deadlock-api's bot creates the custom lobby and the code is posted. Players join and sit on
their side, then a captain presses **Start match** on the board.

- The bot leaves the lobby 15 minutes after creating it, whatever the lobby is doing, so start
  within that window.
- If the lobby can't be made, or isn't made within the lobby code time, the host is asked to create
  one and enter its code. The board has no code button until then.
- Once the match starts, its Deadlock match ID is fetched, so the result can be checked without
  anyone typing it.
- Without an API key, deadlock-api allows 10 lobbies an hour from one IP.

## Score OCR

`scoreocr/` reads a report screenshot: winner, Deadlock match ID, duration, and each player's name,
hero, K/D/A, souls, damage, healing and badge. It's optional, because its dependencies are large,
and the published image doesn't include it. Build with it:

```bash
INSTALL_OCR=true DAYSHIFT_IMAGE_TAG=local docker compose up -d --build
```

Then choose a mode in [Runtime settings](admin.md#runtime-settings) (Score OCR), which refuses
anything but off when it isn't installed. The server's page shows how reads have gone.

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
