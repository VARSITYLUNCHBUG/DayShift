# Captains and strikes

Who can captain, how strikes and queue cooldowns work, and what happens when someone leaves early.
Every number here is in the draft mode or the server's `penalty_policy`, and they are starting
judgements. The player-facing version is the wiki's
[Captains and Strikes](https://github.com/VARSITYLUNCHBUG/DayShift/wiki/Captains-and-Strikes).

## Who can captain

**Captains need 5 completed matches** in this server, across seasons, so a newcomer can't be
troll-picked. A player carrying 3 or more strikes can't captain either. Both values are in the
draft mode's `captains` section (`min_games`, `max_strikes`).

- On the board, players who can't captain show 🔒 and their count, and can't be voted for.
- With two or fewer eligible players in a lobby, the vote is skipped: those players captain and
  any gap is filled by the most completed matches.
- If a captain subs out and the sub can't captain, the teammate with the most completed matches
  takes over.
- Staff can `/captain allow`, `/captain bar` or `/captain clear` anyone.

## Strikes

Strikes make repeat offences cost more, and playing works them back off. Each offence adds strikes:
missed ready check 1, dodge 2, leaver 3, false report 3. The cooldown comes from the kind's ladder,
one rung higher for every strike the player already carries, from any kind:

| Kind | Cooldown by rung, in minutes |
|---|---|
| Missed ready check | 5, 15, 60, 180, 720 |
| Dodge | 60, 360, 1440, 4320, 10080 |
| Leaver | 120, 720, 2880, 10080 |
| False report | 1440, 4320, 10080 |

Every 3 clean completed matches removes a strike, and so does each 14 days without an offence. The
player is told when a strike comes off, and the queue's refusal and `/stats` say how far they are
from the next.

Subbing yourself out after the ready check but before the game starts is a dodge. During the ready
check, or when your captain asks for it, it isn't, and cancelling the request before it's filled
costs nothing. Once the game is on it's a leaver. See [Subs](match-flow.md#subs).

## Early leaves

When someone leaves in the first minutes of the game, a captain can press **Someone left early** and
pick who. If the other captain agrees, the match is voided with no rating change: the leaver gets a
leaver penalty and stays out of the queue, and everyone else goes back in. A disagreement, or no
answer in 2 minutes, goes to staff, who can void it with `/match early_leave`. Reports are open for
20 minutes after the lobby code, or after the bot lobby starts. These timers are the draft mode's
`results` values `early_leave_minutes`, `early_leave_report_minutes` and
`early_leave_answer_seconds`.

**Left early** is marked on a player's match record when they sub out once the game is on, leave
early as above, or show as abandoning in deadlock-api's match data. An abandon early in the game,
inside the early-leave window, is put to staff.

## How strikes are worked out

Strikes are worked out from the facts each time: penalties, completed matches and staff changes.
So voiding a match also takes back the clean game it counted for.

| Command | What it does |
|---|---|
| `/ban add` | Puts a player on a queue cooldown by hand |
| `/ban revoke` | Lifts it and removes its strikes too, unless told to keep them |
| `/ban strikes` | Adds or removes strikes by hand |

All the numbers are in each server's `penalty_policy`, editable in the admin.
