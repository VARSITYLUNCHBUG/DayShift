# Scrims and Bebot's tools

Alongside the ranked match flow, the bot keeps Bebot's other tools: scrim drafts, the priority
list, named pings and the error channel. None of them touches ratings.

## Scrims

`/startdraft` runs a hero ban and pick in any channel, for scrims or anything outside the queue.
Two people press **Become The Hidden King Captain** and **Become The Archmother Captain**, then the
active mode's bans and picks run, The Hidden King first. `/captains_coinflip captain1 captain2`
flips a coin instead: the winner chooses First Pick, Last Pick, 🔶 Hidden King or 🔷 Archmother,
the loser chooses from the other kind, and either captain presses **Start Draft**.

A scrim is a match of its own kind, run by the same engine as a ranked one, so it looks and behaves
the same: Bebot's board, the red-to-ban, green-to-pick grid below it, 🎲 Random, a random pick when
a turn runs out, and the board following the chat. It ends at `# GLHF` with a GIF.

- It's recorded (every ban and pick is kept) and never rated. Its captains aren't held by it, so
  they can queue for ranked meanwhile, and it doesn't count against the server's match capacity.
- Scrims are staff-run: `/startdraft`, `/captains_coinflip` and `/stopdraft` need the Scrims area.
  `/stopdraft` deletes the scrim's messages. `/randomdraft` posts a random ban and pick for both
  sides, for anyone.
- One scrim per channel, and at most 10 at once per server. One whose captains never show up frees
  the channel after 15 minutes.
- The bot never creates, moves or deletes the channel a scrim runs in. It needs View Channel, Send
  Messages and Read Message History there, and Use External Emojis for the hero icons. Without that
  last one, heroes show their plain emoji.

## Priority list

Who in the live match queue has waited longest. Only the queue counts: the Waiting Room is a public
voice channel, so being in it says nothing about wanting to play. Openings in a match are
[offered down this list](match-flow.md#filling-an-opening).

| What happens | The list |
|---|---|
| You join the queue | You go on the back (🟢) |
| You leave the queue | Your place is held for 3 minutes (⏳). Join again in time and you get it back, in the queue too |
| You're put in a match (it pops, you replace someone in the ready check, or you sub in) | You come off |
| Staff take you out of the queue, or clear it | You come off, with no place held |
| A lobby is cancelled | Its ready players go back in the queue and on the list at their old place |
| The match ends | Queue again: you go on the back |

The list isn't posted in any channel. `/prio` tells you, and only you, your place, how long you've
waited and, after leaving the queue, how long your place is held. A held place comes with **Let
it go**, here and on the web's Play page, to give it up at once: joining again later puts you on
the back. `/removeprio` takes someone off (Community area).
A match in another server doesn't count.

## Pings

`/pingchannel channel name mention timer [required_role]` sets up a named ping, such as `pugs`
mentioning @PUGS at most every 15 minutes (Community area). Members send it with
`/ping message [name]`, and `/pings` lists a channel's pings and when each is ready.

- Only the roles and members staff chose can be pinged: @everyone, @here and anything typed into
  the message never are.
- If Discord refuses a ping, its cooldown isn't used.
- `/removeping` deletes one.

## Error channel

`/seterrorchannel channel` posts this server's bot errors in a channel, summarised, at most 10 a
minute (Setup area). Only this server's own errors go there. `/clearerrorchannel` stops it.

Whoever runs the bot can also set `ERROR_LOG_CHANNEL_ID` to get every error, from every server,
with its full traceback.
