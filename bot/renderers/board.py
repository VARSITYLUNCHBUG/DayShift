"""State to components. Pure: given a BoardState, returns a Components V2 view with no I/O."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import discord
from discord import ButtonStyle, SelectOption
from discord.ui import ActionRow, Container, LayoutView, MediaGallery, Separator, TextDisplay

from bot.renderers import style
from bot.renderers.grid import BUTTONS_PER_ROW, SELECT_LIMIT, hero_emoji
from bot.renderers.grid import chunks as _chunks
from bot.renderers.grid import fits as grid_fits
from bot.renderers.grid import messages as grid_messages
from bot.routing import RouteButton, RouteSelect
from league.domain.engine import (
    ARCHMOTHER,
    COINFLIP_LABELS,
    FIRST_PICK,
    HIDDEN_KING,
    LAST_PICK,
    Status,
)
from league.models.subs import SubStatus
from league.services.boards import (
    BoardState,
    ChampionOption,
    DraftLine,
    PlayerLine,
    SubLine,
    SwapLine,
)
from league.services.subs import OfferInfo

ACCENT_LIVE = style.LOBBY_COLOUR
ACCENT_ATTENTION = style.ATTENTION_COLOUR
ACCENT_DONE = style.DONE_COLOUR
ACCENT_VOID = style.VOID_COLOUR

STATUS_TITLES = {
    Status.READY_CHECK: "Ready check",
    Status.CAPTAIN_PHASE: "Captain vote",
    Status.CAPTAIN_CHECKIN: "Captains check in",
    Status.PLAYER_DRAFT: "Player draft",
    Status.COINFLIP: "Captain coinflip",
    Status.CHAMPION_DRAFT: "Champion draft",
    Status.LOBBY_CODE: "Lobby code",
    Status.IN_PROGRESS: "Game on",
    Status.AWAITING_CONFIRMATION: "Confirm the result",
    Status.DISPUTED: "Disputed: waiting for staff",
    Status.COMPLETED: "Finished",
    Status.VOIDED: "Cancelled",
    Status.CAPTAIN_CLAIM: "Claim a side",
    Status.READY_TO_DRAFT: "Ready to draft",
    Status.DRAFTED: "Drafted",
}

CHECKLIST = "Lobby settings: Normal mode, bots off, cheats off, duplicate heroes off."


def player_mention(discord_user_id: int) -> str:
    return f"<@{discord_user_id}>"


# What happens when each timer runs out. Each reads on from Discord's "in 18 seconds".
TIMER_LABELS = {
    Status.READY_CHECK: "Ready check closes",
    Status.CAPTAIN_PHASE: "Vote closes",
    Status.CAPTAIN_CHECKIN: "Missing captains are replaced",
    Status.PLAYER_DRAFT: "Auto-pick",
    Status.COINFLIP: "Random choice",
    Status.CHAMPION_DRAFT: "Auto-pick",
    Status.LOBBY_CODE: "Code due",
    Status.AWAITING_CONFIRMATION: "Confirms automatically",
}


def _stamp(moment: datetime, fmt: str = "R") -> str:
    return f"<t:{int(moment.timestamp())}:{fmt}>"


def countdown(state: BoardState) -> str:
    if state.on_hold:
        until = state.hold_until
        cancel = (
            f" The match is cancelled {_stamp(until)} if nobody takes the spot." if until else ""
        )
        return f"⏸ **Paused for a sub.**{cancel}"
    # A dispute's timer only re-pings staff, so players don't need to see it. The game-on timer
    # is a footer: it's a fallback, not the first thing players should read as the game starts.
    if state.deadline_at is None or state.status in {Status.DISPUTED, Status.IN_PROGRESS}:
        return ""
    label = TIMER_LABELS.get(state.status, "Ends")
    return f"{label} <t:{int(state.deadline_at.timestamp())}:R>"


def _team(state: BoardState, team: str) -> list[PlayerLine]:
    lines = [player for player in state.players if player.team == team]
    return sorted(lines, key=lambda line: not line.is_captain)


def _team_heading(state: BoardState, team: str, lines: list[PlayerLine]) -> str:
    average = sum(line.rating for line in lines) // len(lines)
    side = ""
    if state.hidden_king_team:
        side = " · Hidden King" if state.hidden_king_team == team else " · The Archmother"
    chance = ""
    if state.win_chance_a is not None:
        value = state.win_chance_a if team == "A" else 1 - state.win_chance_a
        lopsided = " ⚠️" if not 0.4 <= state.win_chance_a <= 0.6 else ""
        chance = f" · {value:.0%} to win{lopsided}"
    return f"**{state.team_name(team)}**{side} · avg {average}{chance}"


def _team_block(state: BoardState, team: str) -> str:
    lines = _team(state, team)
    if not lines:
        return f"**{state.team_name(team)}**\n-"
    rows = [
        f"{'👑 ' if line.is_captain else ''}{line.name} ({line.rating_label})" for line in lines
    ]
    return f"{_team_heading(state, team, lines)}\n" + "\n".join(rows)


def _team_line(state: BoardState, team: str) -> str:
    """A whole team on one line, so the champion grid stays on screen."""
    lines = _team(state, team)
    if not lines:
        return f"**{state.team_name(team)}**"
    names = ", ".join(f"{'👑 ' if line.is_captain else ''}{line.name}" for line in lines)
    return f"{_team_heading(state, team, lines)}: {names}"


def _scrim_header(state: BoardState) -> str:
    """Bebot's titles. The coinflip screens carry their own."""
    if state.status == Status.CAPTAIN_CLAIM:
        return f"## {style.draft_title(state.match_id)}"
    if state.status in {Status.CHAMPION_DRAFT, Status.DRAFTED}:
        return f"## {style.draft_title(state.match_id, state.draft_name)}"
    return ""


def _header(state: BoardState) -> str:
    if state.is_scrim:
        return _scrim_header(state)
    if state.status == Status.CHAMPION_DRAFT:
        # Bebot's title. The timer sits on the acting captain's line, unless a sub has paused it.
        title = f"## {style.draft_title(state.match_id, state.draft_name)}"
        return f"{title}\n{countdown(state)}" if state.on_hold else title
    title = STATUS_TITLES.get(state.status, state.status)
    timer = countdown(state)
    line = f"## Match #{state.match_id}: {title}"
    return f"{line}\n{timer}" if timer else line


def _ready(state: BoardState, box: Container[Any]) -> None:
    ready = sum(player.is_ready for player in state.players)
    rows = [f"{'✅' if p.is_ready else '⏳'} {p.name} ({p.rating_label})" for p in state.players]
    box.add_item(TextDisplay(f"{ready}/{len(state.players)} ready\n" + "\n".join(rows)))
    box.add_item(
        ActionRow(RouteButton("ready", state.match_id, label="Ready", style=ButtonStyle.success))
    )


def _vote_row(state: BoardState, player: PlayerLine) -> str:
    mark = "✅" if player.player_id in state.voted_ids else "⏳"
    lock = "" if player.captain_ok else f" 🔒 {player.captain_note}"
    return f"{mark} {player.name} ({player.rating_label}){lock}"


def _captain_vote(state: BoardState, box: Container[Any]) -> None:
    voted = len(state.voted_ids)
    rows = [_vote_row(state, p) for p in state.players]
    rule = (
        f" Captains need {state.captain_min_games} completed matches."
        if state.captain_min_games
        else ""
    )
    box.add_item(
        TextDisplay(
            f"Vote for up to two captains. {voted}/{len(state.players)} voted. "
            f"Most votes wins; rating breaks ties and fills any gap.{rule}\n" + "\n".join(rows)
        )
    )
    able = [p for p in state.players if p.captain_ok]
    options = [
        SelectOption(label=f"{p.name} ({p.rating_label})"[:100], value=str(p.player_id))
        for p in able[:SELECT_LIMIT]
    ]
    if not options:  # Staff barred someone mid-vote. The timeout fills captains by experience.
        return
    box.add_item(
        ActionRow(
            RouteSelect(
                "captain_vote",
                state.match_id,
                options=options,
                placeholder="Vote for up to two captains",
                min_values=1,
                max_values=min(2, len(options)),
            )
        )
    )


def _captain_checkin(state: BoardState, box: Container[Any]) -> None:
    """Both captains confirm they're here before anyone is drafted."""
    rows = []
    for team in ("A", "B"):
        captain = _captain_line(state, team)
        if captain is None:
            continue
        mark = "✅" if captain.player_id in state.checked_in_ids else "⏳"
        rows.append(f"{mark} 👑 {player_mention(captain.discord_user_id)} ({captain.rating_label})")
    box.add_item(
        TextDisplay(
            "Captains: press **I'm here** to start the player draft. A captain who doesn't is "
            "replaced by the next player in line.\n" + "\n".join(rows)
        )
    )
    box.add_item(
        ActionRow(
            RouteButton("checkin", state.match_id, label="I'm here", style=ButtonStyle.success)
        )
    )


def _player_draft(state: BoardState, box: Container[Any]) -> None:
    box.add_item(TextDisplay(_team_block(state, "A") + "\n\n" + _team_block(state, "B")))
    box.add_item(Separator())
    progress = f" ({state.turn_position} of {state.turn_total})" if state.turn_total > 1 else ""
    box.add_item(
        TextDisplay(f"**{state.acting_captain_name}** is picking{progress}.{_next_up(state)}")
    )
    # Drafted players stay in place, greyed out: a double click can't land on the next name.
    pool = [player for player in state.players if not player.is_captain]
    if not any(not player.team for player in pool):
        return
    for chunk in _chunks(pool, BUTTONS_PER_ROW):
        box.add_item(ActionRow(*[_player_button(state, player) for player in chunk]))


_COIN_STYLE = {
    FIRST_PICK: ButtonStyle.primary,
    LAST_PICK: ButtonStyle.primary,
    HIDDEN_KING: ButtonStyle.danger,
    ARCHMOTHER: ButtonStyle.primary,
}
_COIN_EMOJI = {
    HIDDEN_KING: style.HK_EMOJI,
    ARCHMOTHER: style.AM_EMOJI,
}


def coin_buttons(action: str, target_id: int, options: tuple[str, ...]) -> ActionRow[Any]:
    """The coinflip buttons: the two sides for ranked, Bebot's four for scrims."""
    return ActionRow(
        *(
            RouteButton(
                action,
                target_id,
                choice,
                label=COINFLIP_LABELS[choice],
                style=_COIN_STYLE[choice],
                emoji=(
                    discord.PartialEmoji(name=_COIN_EMOJI[choice])
                    if choice in _COIN_EMOJI
                    else None
                ),
            )
            for choice in options
        )
    )


def _coinflip(state: BoardState, box: Container[Any]) -> None:
    winner = state.coinflip_winner
    loser = "B" if winner == "A" else "A"
    if not state.is_scrim:
        box.add_item(TextDisplay(_team_block(state, "A") + "\n\n" + _team_block(state, "B")))
        box.add_item(Separator())
    who = state.captains.get(winner, "-") if state.is_scrim else state.team_name(winner)
    lines = [f"### {style.COIN_EMOJI} Captain Coinflip", f"**{who}** wins the flip!"]
    if not state.is_scrim:
        lines.append(
            f"{state.captains.get(winner, 'Their captain')}, choose your side. "
            "The Hidden King bans and picks first."
        )
    elif not state.coinflip_winner_choice:
        lines.append(f"{state.captains.get(winner, 'Their captain')}, choose your preference:")
    else:
        lines.append(f"Chose: {COINFLIP_LABELS[state.coinflip_winner_choice]}")
        lines.append(f"{state.captains.get(loser, 'Their captain')}, choose your preference:")
    box.add_item(TextDisplay("\n".join(lines)))
    box.add_item(coin_buttons("coin_choice", state.match_id, state.coinflip_options))


def _next_up(state: BoardState) -> str:
    if not state.next_captain_name:
        return ""
    verb = {"ban": " bans", "pick": " picks"}.get(state.next_action, "")
    return f" Next: **{state.next_captain_name}**{verb}."


def _player_button(state: BoardState, player: PlayerLine) -> RouteButton:
    return RouteButton(
        "pick_player",
        state.match_id,
        f"{state.step_index}.{player.player_id}",
        label=f"{player.name} ({player.rating_label})"[:80],
        style=ButtonStyle.secondary if player.team else ButtonStyle.primary,
        disabled=bool(player.team),
    )


def _champion_emoji(champion: ChampionOption) -> discord.PartialEmoji | None:
    return hero_emoji(champion.emoji_id, champion.unicode_emoji)


def _champion_button(state: BoardState, champion: ChampionOption) -> RouteButton:
    # The colour says what a click does. Taken champions stay in place, so the grid never shifts.
    available = ButtonStyle.danger if state.step_action == "ban" else ButtonStyle.success
    return RouteButton(
        "choose_champion",
        state.match_id,
        f"{state.step_index}.{champion.id}",
        label=champion.name[:80],
        style=ButtonStyle.secondary if champion.taken else available,
        disabled=champion.taken,
        emoji=_champion_emoji(champion),
    )


def _champion_rows(state: BoardState, champions: list[ChampionOption]) -> list[ActionRow[Any]]:
    return [
        ActionRow(*[_champion_button(state, champion) for champion in chunk])
        for chunk in _chunks(champions, BUTTONS_PER_ROW)
    ]


def _champion_selects(state: BoardState) -> list[ActionRow[Any]]:
    """Only for a roster too big for the grid: dropdowns take far fewer components."""
    placeholder = "Ban" if state.step_action == "ban" else "Pick"
    options = [
        SelectOption(label=c.name[:100], value=str(c.id), emoji=_champion_emoji(c))
        for c in state.available_champions
    ]
    return [
        ActionRow(
            RouteSelect(
                "pick_champion",
                state.match_id,
                f"{state.step_index}.{index}",
                options=chunk,
                placeholder=f"{placeholder} a champion: {chunk[0].label} to {chunk[-1].label}"[
                    :150
                ],
            )
        )
        for index, chunk in enumerate(_chunks(options))
    ]


def _hero_text(line: DraftLine) -> str:
    """Bebot's hero line: plain emoji, name, and "(random choice)" or "(randomed)"."""
    emoji = style.hero_emoji_text(line.emoji)
    return style.hero_line(emoji, line.label, random_choice=line.random_choice, auto=line.auto)


def _captain_line(state: BoardState, team: str) -> PlayerLine | None:
    return next((p for p in state.players if p.is_captain and p.team == team), None)


def _captains_block(state: BoardState, *, final: bool) -> list[str]:
    rows = [f"{style.CAPTAIN_EMOJI} **Captains**"]
    for team in state.side_order:
        emoji = style.side_emoji(state.side_of(team))
        captain = _captain_line(state, team)
        name = captain.name if captain else "-"
        if not final and team == state.acting_team and captain is not None:
            # Bebot's "@Pike ban a hero!". Board mentions never ping, but they stand out.
            timer = "" if state.on_hold else style.countdown(state.deadline_at)
            mention = player_mention(captain.discord_user_id)
            rows.append(f"{emoji} {mention} {state.step_action} a hero!{timer}")
        else:
            rows.append(f"{emoji} {name}")
    return rows


def draft_summary(state: BoardState, *, final: bool) -> str:
    """Bebot's draft: captains, bans, then each side's heroes, one per line."""
    bans = [_hero_text(line) for line in state.actions if line.action == "ban"]
    parts = [*_captains_block(state, final=final), "", f"{style.BAN_EMOJI} **Bans**"]
    parts.append(style.hero_list(bans))
    for team in state.side_order:
        side = state.side_of(team)
        picks = [
            _hero_text(line)
            for line in state.actions
            if line.action == "pick" and line.team == team
        ]
        parts += [
            "",
            f"{style.side_emoji(side)} **{style.side_name(side)}**: {state.team_name(team)}",
        ]
        parts.append(style.hero_list(picks))
    return "\n".join(parts)


def _champion_draft(state: BoardState, box: Container[Any]) -> None:
    box.add_item(TextDisplay(draft_summary(state, final=False)))
    box.add_item(TextDisplay(style.timeline_block(state.champion_steps, state.champion_step)))
    if state.is_scrim:
        return  # Bebot's board alone: a scrim has no ratings to show.
    # Our extras: each team's rating, and where the draft is up to.
    ratings = "\n".join(
        f"-# {_team_heading(state, team, _team(state, team))}"
        for team in state.side_order
        if _team(state, team)
    )
    noun = "Ban" if state.step_action == "ban" else "Pick"
    progress = f"{noun} {state.turn_position} of {state.turn_total}." if state.turn_total else ""
    box.add_item(
        TextDisplay(f"{progress}{_next_up(state)}".strip() + (f"\n{ratings}" if ratings else ""))
    )


def _random_button(state: BoardState) -> RouteButton:
    return RouteButton(
        "random_champion",
        state.match_id,
        state.step_index,
        label="Random",
        style=ButtonStyle.primary,
        emoji=discord.PartialEmoji(name="🎲"),
    )


def render_pickers(state: BoardState) -> list[LayoutView]:
    """The champion grid, in messages of its own directly below the board.

    They hold nothing else, so they stack into one grid. Each turn they are posted afresh rather
    than edited, so no "(edited)" tag splits the grid.
    """
    if state.status != Status.CHAMPION_DRAFT or state.on_hold:
        return []
    rows = [*_champion_rows(state, state.champions), ActionRow(_random_button(state))]
    if not grid_fits(rows):
        rows = [*_champion_selects(state), ActionRow(_random_button(state))]
    return grid_messages(rows)


def _final_draft_summary(state: BoardState) -> str:
    """Bebot's finished draft, then who's on each team for the lobby."""
    teams = "\n".join(_team_line(state, team) for team in state.side_order)
    return f"{draft_summary(state, final=True)}\n\n{teams}"


def _lobby_code(state: BoardState, box: Container[Any]) -> None:
    # The draft ends with a name, the summary, a GIF and GLHF.
    box.add_item(TextDisplay(f"### {style.draft_title(state.match_id, state.draft_name)}"))
    box.add_item(TextDisplay(_final_draft_summary(state)))
    if state.gif_url:
        box.add_item(MediaGallery(discord.MediaGalleryItem(state.gif_url)))
    box.add_item(TextDisplay("# GLHF"))
    box.add_item(Separator())
    if not state.api_lobby_failed:
        box.add_item(
            TextDisplay(
                "The bot is creating the lobby. Its code shows here when it's ready. If it can't, "
                f"**{state.host_name}** is asked to create one."
            )
        )
        return
    box.add_item(
        TextDisplay(
            f"The bot couldn't create the lobby. **{state.host_name}** hosts: create the custom "
            f"lobby, then enter its code.\n{CHECKLIST}"
        )
    )
    box.add_item(
        ActionRow(
            RouteButton(
                "code_open", state.match_id, label="Enter lobby code", style=ButtonStyle.primary
            )
        )
    )


def _in_progress(state: BoardState, box: Container[Any]) -> None:
    box.add_item(TextDisplay(f"### Lobby code: `{state.lobby_code}`"))
    if state.api_lobby and not state.api_started:
        leaves = (
            f" The bot leaves the lobby <t:{int(state.api_leaves_at.timestamp())}:R>."
            if state.api_leaves_at
            else ""
        )
        box.add_item(
            TextDisplay(
                "The bot is hosting. Join with the code and sit on your team's side, then a "
                f"captain presses Start match.{leaves}"
            )
        )
        box.add_item(
            ActionRow(
                RouteButton(
                    "api_start", state.match_id, label="Start match", style=ButtonStyle.success
                )
            )
        )
    box.add_item(Separator())
    box.add_item(TextDisplay(_final_draft_summary(state)))
    box.add_item(Separator())
    box.add_item(TextDisplay("Captains: when the game ends, press the team that won."))
    box.add_item(
        ActionRow(
            *[
                RouteButton(
                    "report_open",
                    state.match_id,
                    team,
                    label=f"{state.team_name(team)} won"[:80],
                    style=ButtonStyle.primary,
                )
                for team in ("A", "B")
            ]
        )
    )
    if state.deadline_at is not None:
        box.add_item(
            TextDisplay(f"-# Report by {_stamp(state.deadline_at, 't')}, or staff will step in.")
        )
    _early_leave(state, box)


def _early_leave(state: BoardState, box: Container[Any]) -> None:
    """Someone left in the first minutes: report it, or answer a report."""
    if state.early_leave_name:
        box.add_item(Separator())
        box.add_item(
            TextDisplay(
                f"**{state.early_leave_by}** says **{state.early_leave_name}** left in the first "
                f"{state.early_leave_minutes} minutes. The other captain: agree to void the "
                "match with no rating change, or disagree and staff decide."
            )
        )
        box.add_item(
            ActionRow(
                RouteButton(
                    "early_yes", state.match_id, label="Agree: void", style=ButtonStyle.danger
                ),
                RouteButton("early_no", state.match_id, label="Disagree"),
            )
        )
    elif state.early_leave_open:
        box.add_item(
            ActionRow(
                RouteButton(
                    "early_open",
                    state.match_id,
                    label=f"Someone left in the first {state.early_leave_minutes} min",
                )
            )
        )


def _awaiting(state: BoardState, box: Container[Any]) -> None:
    box.add_item(
        TextDisplay(
            f"**{state.reported_by}** reported **{state.team_name(state.reported_winner)}** won.\n"
            "The other captain can confirm, dispute or add a screenshot. "
            "Silence confirms when the timer runs out."
        )
    )
    box.add_item(
        ActionRow(
            RouteButton("confirm", state.match_id, label="Confirm", style=ButtonStyle.success),
            RouteButton("report_open", state.match_id, label="Add my screenshot"),
            RouteButton("dispute_open", state.match_id, label="Dispute", style=ButtonStyle.danger),
        )
    )


def _disputed(state: BoardState, box: Container[Any]) -> None:
    reported = (
        f"{state.reported_by} reported {state.team_name(state.reported_winner)} won.\n"
        if state.reported_by
        else "No result was reported.\n"
    )
    box.add_item(
        TextDisplay(reported + "Sent to staff, who will decide. Ratings are unchanged until then.")
    )


def _closing(state: BoardState) -> str:
    if state.closes_at is None:
        return ""
    return f"\nThis channel closes <t:{int(state.closes_at.timestamp())}:R>."


def _finished(state: BoardState, box: Container[Any]) -> None:
    if state.status == Status.COMPLETED:
        delta = next(
            (
                abs(state.deltas[player.player_id])
                for player in state.players
                if player.player_id in state.deltas
            ),
            0,
        )
        box.add_item(
            TextDisplay(
                f"**{state.team_name(state.winner)} won** (±{delta}). "
                f"Results are posted.{_closing(state)}"
            )
        )
    else:
        box.add_item(TextDisplay(f"No rating changes.{_closing(state)}"))


def _captain_claim(state: BoardState, box: Container[Any]) -> None:
    """Bebot's /startdraft: two Become Captain buttons. The Hidden King bans and picks first."""
    lines = ["Captains: claim a side."]
    for side, team in (("hk", "A"), ("am", "B")):
        captain = _captain_line(state, team)
        lines.append(
            f"{style.side_emoji(side)} {style.side_name(side)}: {captain.name if captain else '-'}"
        )
    box.add_item(TextDisplay("\n".join(lines)))
    box.add_item(
        ActionRow(
            *(
                RouteButton(
                    "claim_captain",
                    state.match_id,
                    side,
                    label=f"Become {style.side_name(side)} Captain",
                    style=button_style,
                    disabled=_captain_line(state, team) is not None,
                    emoji=discord.PartialEmoji(name=style.side_emoji(side)),
                )
                for side, team, button_style in (
                    ("hk", "A", ButtonStyle.danger),
                    ("am", "B", ButtonStyle.primary),
                )
            )
        )
    )


def _ready_to_draft(state: BoardState, box: Container[Any]) -> None:
    """Bebot's "Captain Coinflip - Complete", with the Start Draft button."""
    winner = state.coinflip_winner
    loser = "B" if winner == "A" else "A"
    first_side = state.side_of(state.champion_first_pick)
    lines = [
        f"### {style.COIN_EMOJI} Captain Coinflip - Complete",
        f"**{state.captains.get(winner, '-')}** chose: "
        f"{COINFLIP_LABELS[state.coinflip_winner_choice]}",
        f"**{state.captains.get(loser, '-')}** chose: "
        f"{COINFLIP_LABELS[state.coinflip_loser_choice]}",
        "",
        *(
            f"{style.side_emoji(state.side_of(team))} {style.side_name(state.side_of(team))}: "
            f"{state.captains.get(team, '-')}"
            for team in state.side_order
        ),
        f"{style.side_name(first_side)} bans and picks first. Ready to start the draft!",
    ]
    box.add_item(TextDisplay("\n".join(lines)))
    box.add_item(
        ActionRow(
            RouteButton(
                "start_draft", state.match_id, label="Start Draft", style=ButtonStyle.success
            )
        )
    )


def _drafted(state: BoardState, box: Container[Any]) -> None:
    """A scrim's end: Bebot's finished draft, a GIF and GLHF."""
    box.add_item(TextDisplay(draft_summary(state, final=True)))
    if state.gif_url:
        box.add_item(MediaGallery(discord.MediaGalleryItem(state.gif_url)))
    box.add_item(TextDisplay("# GLHF"))


def _stopped(state: BoardState, box: Container[Any]) -> None:
    box.add_item(TextDisplay("Draft stopped."))


_SECTIONS = {
    Status.READY_CHECK: _ready,
    Status.CAPTAIN_PHASE: _captain_vote,
    Status.CAPTAIN_CHECKIN: _captain_checkin,
    Status.PLAYER_DRAFT: _player_draft,
    Status.COINFLIP: _coinflip,
    Status.CHAMPION_DRAFT: _champion_draft,
    Status.LOBBY_CODE: _lobby_code,
    Status.IN_PROGRESS: _in_progress,
    Status.AWAITING_CONFIRMATION: _awaiting,
    Status.DISPUTED: _disputed,
    Status.COMPLETED: _finished,
    Status.VOIDED: _finished,
    Status.CAPTAIN_CLAIM: _captain_claim,
    Status.READY_TO_DRAFT: _ready_to_draft,
    Status.DRAFTED: _drafted,
}


def _accent(state: BoardState) -> int:
    if state.on_hold:
        return ACCENT_ATTENTION
    if state.status in {Status.COINFLIP, Status.READY_TO_DRAFT}:
        return style.COINFLIP_COLOUR
    if state.status == Status.CAPTAIN_CLAIM:
        return style.HK_COLOUR
    if state.status == Status.CHAMPION_DRAFT and state.acting_team:
        return style.side_colour(state.side_of(state.acting_team))
    if state.status == Status.DRAFTED and state.champion_steps:
        return style.side_colour(state.champion_steps[-1][1])  # Bebot: the last side's colour.
    if state.status == Status.COMPLETED:
        return ACCENT_DONE
    if state.status == Status.VOIDED:
        return ACCENT_VOID
    if state.status in {Status.DISPUTED, Status.AWAITING_CONFIRMATION}:
        return ACCENT_ATTENTION
    return ACCENT_LIVE


def _sub_buttons(state: BoardState, line: SubLine) -> list[RouteButton]:
    if line.status == SubStatus.AWAITING_APPROVAL:
        return [
            RouteButton(
                "sub_approve", state.match_id, line.id, label="Approve", style=ButtonStyle.success
            ),
            RouteButton(
                "sub_reject", state.match_id, line.id, label="Keep them", style=ButtonStyle.danger
            ),
        ]
    cancel = RouteButton("sub_cancel", state.match_id, line.id, label="Cancel sub")
    if line.offer_name:
        return [cancel]
    name = RouteButton(
        "sub_invite_open", state.match_id, line.id, label="Name a sub", style=ButtonStyle.primary
    )
    if line.name_until is None:
        return [name, cancel]
    return [name, RouteButton("sub_queue", state.match_id, line.id, label="Ask the queue"), cancel]


def _sub_text(state: BoardState, line: SubLine) -> str:
    team = f" ({state.team_name(line.team)})" if line.team else ""
    who = f"**{line.leaving_name}**{team}"
    if line.status == SubStatus.AWAITING_APPROVAL:
        return (
            f"🔁 **{line.requested_by_name}** wants to sub out {who}. "
            f"The other captain can approve or refuse {_stamp(line.deadline_at)}."
        )
    head = f"🔁 **{line.leaving_name}** is subbing out."
    if line.offer_name:
        answer = f" {_stamp(line.offer_deadline_at)}" if line.offer_deadline_at else ""
        return f"{head} Waiting for **{line.offer_name}**.{answer}"
    if line.name_until is not None:
        return f"{head} Name a sub, or the queue is asked {_stamp(line.name_until)}."
    return f"{head} Waiting for someone to join the queue, or name a sub."


# Spots the bot opened itself, offered for players to accept: nobody names a sub for these.
OPENED_BY_BOT = ("missed_ready", "restart")


def _open_spots_text(lines: list[SubLine]) -> str:
    """Every spot the bot opened (a missed ready check, or a restart), in two short lines.
    They're offered to players by DM, so there's nothing to click here."""
    waiting = [f"**{line.offer_name}**" for line in lines if line.offer_name]
    subs = f"{len(lines)} Sub{'' if len(lines) == 1 else 's'}"
    asked = (
        f"Waiting on response from {', '.join(waiting)}"
        if waiting
        else "Waiting for someone to join the queue"
    )
    return f"🔁 **Need {subs}**\n{asked}"


def _subs(state: BoardState, box: Container[Any]) -> None:
    opened = [line for line in state.subs if line.reason in OPENED_BY_BOT]
    if opened:
        box.add_item(TextDisplay(_open_spots_text(opened)))
    for line in state.subs:
        if line.reason in OPENED_BY_BOT:
            continue
        box.add_item(TextDisplay(_sub_text(state, line)))
        box.add_item(ActionRow(*_sub_buttons(state, line)))


def _swap(state: BoardState, box: Container[Any], line: SwapLine) -> None:
    box.add_item(
        TextDisplay(
            f"🔄 **{line.requested_by_name}** offers **{line.give_name}** for "
            f"**{line.take_name}**. The other captain can accept {_stamp(line.deadline_at)}."
        )
    )
    box.add_item(
        ActionRow(
            RouteButton(
                "swap_yes", state.match_id, line.id, label="Accept swap", style=ButtonStyle.success
            ),
            RouteButton("swap_no", state.match_id, line.id, label="Decline"),
        )
    )


def _strip_buttons(box: Container[Any], start: int) -> None:
    """While paused, the phase's own buttons would only be refused, so the board leaves them out."""
    for item in list(box.children)[start:]:
        if isinstance(item, ActionRow):
            box.remove_item(item)


def render_board(state: BoardState) -> LayoutView:
    box: Container[Any] = Container(accent_colour=_accent(state))
    header = _header(state)
    if header:
        box.add_item(TextDisplay(header))
    start = len(box.children)
    if state.is_scrim and state.status == Status.VOIDED:
        _stopped(state, box)
    else:
        _SECTIONS[state.status](state, box)
    # A result can still come in while a sub is on the way: the game may have ended anyway.
    if state.on_hold and state.status != Status.IN_PROGRESS:
        _strip_buttons(box, start)
    if state.subs:
        box.add_item(Separator())
        _subs(state, box)
    if state.swap is not None and not state.on_hold:
        box.add_item(Separator())
        _swap(state, box, state.swap)
    footer: list[RouteButton] = []
    if state.can_request_sub:
        footer.append(RouteButton("sub_open", state.match_id, label="Request a sub"))
    if state.can_swap and state.swap is None and not state.on_hold:
        footer.append(RouteButton("swap_open", state.match_id, label="Swap players"))
    if footer:
        box.add_item(ActionRow(*footer))
    view = LayoutView(timeout=None)
    view.add_item(box)
    return view


def render_ready_dm(
    match_id: int, invite_url: str | None, *, heading: str, channel_url: str | None = None
) -> LayoutView:
    """The DM sent to players who weren't in the Waiting Room when their lobby popped."""
    buttons: list[discord.ui.Item[Any]] = []
    if invite_url:
        buttons.append(discord.ui.Button(label="Join the Waiting Room", url=invite_url))
    buttons.append(RouteButton("ready", match_id, label="Ready", style=ButtonStyle.success))
    if channel_url:
        buttons.append(discord.ui.Button(label="Open match channel", url=channel_url))
    box: Container[Any] = Container(
        TextDisplay(f"## {heading}\nMatch #{match_id}. Join the Waiting Room, then press Ready."),
        ActionRow(*buttons),
        accent_colour=ACCENT_LIVE,
    )
    view = LayoutView(timeout=None)
    view.add_item(box)
    return view


def render_voice_dm(
    match_id: int,
    invite_url: str | None,
    *,
    heading: str,
    body: str = "",
    channel_url: str | None = None,
    voice_label: str = "Join team voice",
    subtitle: bool = True,
) -> LayoutView:
    """A voice invite with no ready step: teams moving to their own channels, or a sub arriving.
    Without `subtitle` it's the heading and the buttons alone."""
    intro = f"Match #{match_id}." + (f" {body}" if body else "")
    text = f"## {heading}\n{intro}" if subtitle else f"## {heading}"
    items: list[discord.ui.Item[Any]] = [TextDisplay(text)]
    links: list[discord.ui.Item[Any]] = []
    if invite_url:
        links.append(discord.ui.Button(label=voice_label, url=invite_url))
    if channel_url:
        links.append(discord.ui.Button(label="Open match channel", url=channel_url))
    if links:
        items.append(ActionRow(*links))
    view = LayoutView(timeout=None)
    view.add_item(Container(*items, accent_colour=ACCENT_LIVE))
    return view


def render_text_dm(match_id: int, heading: str, text: str) -> LayoutView:
    """A note for one player only, such as their standing after a match."""
    view = LayoutView(timeout=None)
    body: TextDisplay[Any] = TextDisplay(f"## {heading}\nMatch #{match_id}. {text}")
    view.add_item(Container(body, accent_colour=ACCENT_LIVE))
    return view


def _offer_intro(info: OfferInfo, team_name: str) -> str:
    team = f" on **{team_name}**" if team_name else ""
    if info.invited_by:
        return f"**{info.invited_by}** asked you to take **{info.leaving_name}**'s spot{team}."
    spot = "A spot opened in the ready check" if info.missed_ready else f"A spot opened{team}"
    if info.source == "prio":
        return f"{spot}, and you've waited longest in the queue."
    return f"{spot}, and you're next in the queue."


def _offer_buttons(info: OfferInfo) -> ActionRow[Any]:
    return ActionRow(
        RouteButton(
            "sub_accept",
            info.match_id,
            info.offer_id,
            label="I'll sub in",
            style=ButtonStyle.success,
        ),
        RouteButton("sub_decline", info.match_id, info.offer_id, label="Can't right now"),
    )


def render_sub_offer_dm(info: OfferInfo, team_name: str) -> LayoutView:
    """Asks someone outside the match to take an open spot."""
    phase = STATUS_TITLES.get(info.status, info.status)
    lines = [
        f"## Can you sub in?\nMatch #{info.match_id} ({phase}). {_offer_intro(info, team_name)}",
        f"Answer {_stamp(info.deadline_at)}.",
    ]
    if info.status == Status.IN_PROGRESS:
        lines.append("-# The game is already running. You take this team's result.")
    view = LayoutView(timeout=None)
    view.add_item(
        Container(TextDisplay("\n".join(lines)), _offer_buttons(info), accent_colour=ACCENT_LIVE)
    )
    return view


def render_offer_answered(match_id: int, text: str) -> LayoutView:
    """What an answered offer turns into, so its buttons can't be pressed again."""
    view = LayoutView(timeout=None)
    view.add_item(
        Container(TextDisplay(f"## Match #{match_id}\n{text}"), accent_colour=ACCENT_VOID)
    )
    return view
