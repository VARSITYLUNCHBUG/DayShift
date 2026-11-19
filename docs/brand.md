# Brand

How DayShift looks and sounds, for anyone adding a page, a Discord message or a graphic. The
files are in [assets/brand/](assets/brand/). This page is the short version of the DayShift
identity guide (version 1.0, November 2026).

<p>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/brand/dayshift-lockup-ink.svg">
    <img src="assets/brand/dayshift-lockup-paper.svg" alt="DayShift" width="360">
  </picture>
</p>

## The idea

DayShift is the home of a league's Deadlock inhouse: one queue, captains draft the teams, the
heroes get banned and picked, and every result lands on the ladder. It runs in Discord and on the
web, and should feel like the same room in both. The name is for the hours after the day shift,
when the league logs on and the night starts.

**The line:** *League night, every night.* Use it under the logo on a sign-in page, a share card
or a poster. Never as a button label, and never with exclamation marks.

**Platform first, the game is a guest.** DayShift owns its name, logo, colours, type, icons and
voice. Deadlock brings only its team colours, hero art and names. The game's logo never sits next
to ours.

## The logo

A mark of three kit stripes (bubblegum, cream, bubblegum) and the DAYSHIFT wordmark, drawn as one
and leaning 14 degrees. The wordmark is a drawing, not a font: always use the files.

| Version | Use it for | Files |
|---|---|---|
| Primary lockup | Wherever there's room: a page header, a banner, a share card, this README | `dayshift-lockup-{ink,paper,ink-bg,bubblegum,cream,black}.svg` |
| Stacked lockup | Square and portrait spaces: a splash screen, a social square | `dayshift-stacked-{ink,paper}.svg` |
| Mark | Where the name is already said or space is tight: icons, avatars, favicons | `dayshift-mark.svg`, `dayshift-mark-{paper,cream}.svg` |
| Wordmark | Only beside the mark, or in a one-line credit | `dayshift-wordmark-{cream,ink}.svg` |
| App icon, favicon | Browser tabs and installed apps | `app-icon.svg`, `app-icon-maskable.svg`, `favicon.svg` |
| Discord avatar | The bot's profile picture: the mark in plum on bubblegum | `avatar-discord.svg` |

The suffix is the background a file is for: `ink` on the dark ground, `paper` on light, `ink-bg`
and `bubblegum` carry their own ground, `cream` and `black` are one-colour versions.

### Colourways

| Background | Use |
|---|---|
| Ink and DayShift surfaces | Full colour (`-ink`) |
| Paper and white | Full colour on paper (`-paper`), or black one-colour |
| Bubblegum | Plum one-colour only (`-bubblegum`) |
| Team amber or blue | Never. The brand doesn't take sides: put it on ink beside the team colour |
| Photos and hero art | Cream one-colour or full colour, over an ink scrim, on the art's quiet side |

### Don't

- Recolour it in team colours, straighten the lean, add more lean, or rotate it like a sticker.
- Stretch it on one axis, rearrange the mark and the word, or type the name in a font instead.
- Add a glow, shadow, gradient, bevel or outline.
- Put it on busy art without the scrim, or crowd it: keep clear space around it, and keep other
  names outside that space, behind a divider.

## Colour

Three colours are ours: ink, cream and bubblegum. Bubblegum is the brand itself, never an action:
buttons are cream on ink. Dark is the default theme.

| Token | Dark | Light | Use |
|---|---|---|---|
| `--ds-ink` | `#111019` | `#F6F2EA` | The ground: most of every screen |
| `--ds-surface` | `#1A1824` | `#FFFFFF` | Panels and cards |
| `--ds-raised` | `#232031` | `#ECE6DA` | Pressed, selected, inputs on a surface |
| `--ds-line` | `#322E44` | `#DDD5C7` | Dividers only |
| `--ds-line-strong` | `#6E6789` | `#8A8297` | Control edges |
| `--ds-cream` | `#F3EFE6` | `#16141F` | Text and the main button |
| `--ds-muted` | `#A8A2B5` | `#625C6E` | Secondary text |
| `--ds-faint` | `#948EA3` | | Labels and meta |
| `--ds-bubblegum` | `#FF8DC3` | `#B33A75` | DayShift itself: identity only |
| `--ds-plum` | `#2A0A19` | | Ink on bubblegum |
| `--ds-danger` | `#FF6B6B` | `#B8323F` | Leaving, bans, voids, disputes |
| `--ds-ok` | `#7FD1A8` | | A success tick only |

**The game layer** (Deadlock's, inside a match only): The Hidden King `--team-a` `#E3A23B`, The
Archmother `--team-b` `#5E92E8`, each with soft, line, light and ink shades. Outside a match there
is no team colour at all.

Roughly: ink 64%, surfaces 16%, cream 10%, bubblegum 4%, and the two teams 3% each inside a match.
Name tokens by role, never by hue (no `--pink`).

## Type

Two open-source families from Google Fonts, plus the drawn wordmark:

- **Bricolage Grotesque, 800**, for short loud lines: page titles, team names, the clock, the
  match number. Tight (-3% tracking), never for paragraphs.
- **Figtree, 400 to 800**, for everything people read: buttons, labels, chat, tables.

Numbers that sit in columns or tick use tabular figures. Thousands take a comma (1,512), big
numbers are short (238.4k), and scores use an en dash (41–27). Lobby codes are Figtree 800 with
+8% tracking.

## Voice

Plain, friendly, quick and fair: talk like the person running the night, not a system.

| Say | Not |
|---|---|
| Your place is held for 2:00. | Queue position unavailable. |
| Rook's Team win · +17 | Victory achieved! |
| Wrecking ball: 16.9k objective damage | Amazing play!! |

Name the rule and say how it ends; never scold. One big moment per night (Doors open), and the fun
lives in small facts.

## Where it applies

| Place | What to use |
|---|---|
| The bot's Discord avatar | `avatar-discord.svg` |
| Discord messages | The mark in the footer; a bubblegum edge for a DayShift moment such as the queue popping, the winner's team colour on a result |
| Web pages | `favicon.svg`, `theme-color` `#111019`, the primary lockup in the header |
| Icons | `dayshift-icons.svg`: one sprite of 48 icons with ids `ds-<name>`, drawn in `currentColor` |
