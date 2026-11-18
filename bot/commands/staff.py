"""Staff commands. Anything that rewrites ratings shows a preview and needs a Confirm click."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import discord
from discord import Interaction, app_commands

from bot.db import db
from bot.handlers.common import actor, community_of
from bot.handlers.permissions import require_area
from bot.handlers.results import send_name_picker
from bot.routing import guarded, reply
from league.domain.engine import TERMINAL, Status
from league.domain.errors import InvalidAction
from league.models import (
    Community,
    Match,
    MatchAward,
    Player,
    RatingEvent,
    ScoreboardRead,
    Season,
)
from league.models.matches import MatchKind
from league.models.permissions import Area
from league.models.scoreboards import AwardSource
from league.services import (
    api_results,
    awards,
    boards,
    corrections,
    early_leave,
    lobby,
    ocr,
    penalties,
    queue,
    ratings,
    results,
    standing,
    steam,
)
from league.services.corrections import Preview


class ConfirmView(discord.ui.View):
    """A short-lived ephemeral confirmation. It doesn't need to survive a restart."""

    def __init__(self, on_confirm: Callable[[Interaction[Any]], Awaitable[None]]) -> None:
        super().__init__(timeout=120)
        self.on_confirm = on_confirm

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: Interaction[Any], _button: discord.ui.Button[Any]) -> None:
        self.stop()

        async def run() -> None:
            await interaction.response.edit_message(view=None)
            await self.on_confirm(interaction)

        await guarded(interaction, run)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: Interaction[Any], _button: discord.ui.Button[Any]) -> None:
        self.stop()
        await interaction.response.edit_message(content="Cancelled.", view=None)


async def _staff_start(interaction: Interaction[Any], *areas: Area) -> Community:
    """Answer privately, then refuse unless the member holds one of these areas."""
    await interaction.response.defer(ephemeral=True, thinking=True)
    community = await community_of(interaction)
    await require_area(interaction, community, *areas)
    return community


def _get_match(community: Community, match_id: int) -> Match:
    match = (
        Match.objects.select_related("season", "community", "mode_version")
        .filter(pk=match_id, community=community, kind=MatchKind.RANKED)  # Scrims: no staff tools.
        .first()
    )
    if match is None:
        raise InvalidAction(f"There's no match #{match_id}.")
    return match


def _preview_text(preview: Preview) -> str:
    if not preview.net_by_player:
        return "Nobody's rating changes."
    names = dict(
        Player.objects.filter(pk__in=preview.net_by_player).values_list("pk", "display_name")
    )
    ordered = sorted(preview.net_by_player.items(), key=lambda item: -abs(item[1]))
    rows = [f"{names[player_id][:16]:<16} {delta:+d}" for player_id, delta in ordered[:25]]
    extra = f"\n...and {len(ordered) - 25} more" if len(ordered) > 25 else ""
    return (
        f"This recalculates {preview.events_to_write} rating changes, including later matches "
        "that this one affects.\n"
        "```\n" + "\n".join(rows) + extra + "\n```"
    )


async def _send_confirm(
    interaction: Interaction[Any],
    text: str,
    on_confirm: Callable[[Interaction[Any]], Awaitable[None]],
) -> None:
    await interaction.followup.send(text, view=ConfirmView(on_confirm), ephemeral=True)


match_group = app_commands.Group(name="match", description="Staff: manage matches")


def _status_text(community: Community, match_id: int) -> str:
    match = _get_match(community, match_id)
    deadline = (
        f", next timeout <t:{int(match.deadline_at.timestamp())}:R>" if match.deadline_at else ""
    )
    winner = boards.outcome_label(match, match.winner) if match.winner else "-"
    return f"Match #{match.pk}: **{match.get_status_display()}**{deadline}. Winner: {winner}."


@match_group.command(name="status", description="Where a match is up to")
async def match_status(interaction: Interaction[Any], match_id: int) -> None:
    async def run() -> None:
        community = await _staff_start(interaction, Area.MATCH_CONTROL)
        await reply(interaction, await db(_status_text, community, match_id))

    await guarded(interaction, run)


@match_group.command(name="void", description="Cancel a live match, or void a finished one")
async def match_void(interaction: Interaction[Any], match_id: int, reason: str) -> None:
    async def run() -> None:
        community = await _staff_start(interaction, Area.MATCH_CONTROL, Area.DISPUTES)
        match = await db(_get_match, community, match_id)
        await require_area(
            interaction,
            community,
            Area.MATCH_CONTROL if match.status not in TERMINAL else Area.DISPUTES,
        )
        staff = await actor(interaction)
        if match.status not in TERMINAL:

            async def void_live(confirmed: Interaction[Any]) -> None:
                await db(lobby.staff_void, match_id, staff, reason)
                await reply(confirmed, f"Match #{match_id} cancelled. No ratings changed.")

            await _send_confirm(
                interaction, f"Cancel live match #{match_id}? Nobody's rating changes.", void_live
            )
            return

        preview = await db(corrections.preview_outcome, match, "void")

        async def void_finished(confirmed: Interaction[Any]) -> None:
            await db(corrections.apply_outcome_correction, match_id, "void", staff, reason)
            await reply(confirmed, f"Match #{match_id} voided and ratings corrected.")

        text = f"Void finished match #{match_id}?\n{await db(_preview_text, preview)}"
        await _send_confirm(interaction, text, void_finished)

    await guarded(interaction, run)


def _team_of_player(match: Match, player: Player) -> str:
    row = match.participants.roster().filter(player=player).first()
    if row is None:
        raise InvalidAction(f"{player.display_name} isn't on this match's roster.")
    return row.team


@match_group.command(name="rescore", description="Set or change a match's winner")
@app_commands.describe(winning_captain="The captain of the team that won")
async def match_rescore(
    interaction: Interaction[Any], match_id: int, winning_captain: discord.Member, reason: str
) -> None:
    async def run() -> None:
        community = await _staff_start(interaction, Area.DISPUTES)
        match = await db(_get_match, community, match_id)
        staff = await actor(interaction)
        captain = await db(
            Player.objects.from_discord, winning_captain.id, winning_captain.display_name
        )
        winner = await db(_team_of_player, match, captain)
        label = await db(boards.outcome_label, match, winner)
        if match.status == Status.DISPUTED:
            await db(results.resolve_dispute, match_id, winner, staff, reason)
            await reply(interaction, f"Match #{match_id}: {label} recorded as the winner.")
            return
        if match.status not in TERMINAL:
            raise InvalidAction("That match is still being played.")
        preview = await db(corrections.preview_outcome, match, winner)

        async def apply(confirmed: Interaction[Any]) -> None:
            await db(corrections.apply_outcome_correction, match_id, winner, staff, reason)
            await reply(confirmed, f"Match #{match_id} corrected: {label} won.")

        details = await db(_preview_text, preview)
        await _send_confirm(
            interaction, f"Make {label} the winner of #{match_id}?\n{details}", apply
        )

    await guarded(interaction, run)


@match_group.command(name="sub", description="Replace a player. The substitute takes the result")
async def match_sub(
    interaction: Interaction[Any],
    match_id: int,
    out: discord.Member,
    replacement: discord.Member,
    reason: str,
) -> None:
    async def run() -> None:
        community = await _staff_start(interaction, Area.MATCH_CONTROL, Area.DISPUTES)
        match = await db(_get_match, community, match_id)
        await require_area(
            interaction,
            community,
            Area.MATCH_CONTROL if match.status not in TERMINAL else Area.DISPUTES,
        )
        staff = await actor(interaction)
        out_player = await db(Player.objects.from_discord, out.id, out.display_name)
        in_player = await db(Player.objects.from_discord, replacement.id, replacement.display_name)
        if match.status not in TERMINAL:
            await db(lobby.substitute_live, match_id, out_player, in_player, staff)
            await reply(interaction, f"{replacement.display_name} is in for {out.display_name}.")
            return
        preview = await db(corrections.preview_sub, match, out_player, in_player)

        async def apply(confirmed: Interaction[Any]) -> None:
            await db(
                corrections.apply_sub_correction, match_id, out_player, in_player, staff, reason
            )
            await reply(confirmed, "Roster corrected and ratings recalculated.")

        text = (
            f"Replace {out.display_name} with {replacement.display_name} on #{match_id}?\n"
            f"{await db(_preview_text, preview)}"
        )
        await _send_confirm(interaction, text, apply)

    await guarded(interaction, run)


def _explain_text(community: Community, match_id: int) -> str:
    match = _get_match(community, match_id)
    lines = [f"**Match #{match.pk}**: {match.status}, pinned to {match.mode_version}"]
    for result in match.results.order_by("revision"):
        label = boards.outcome_label(match, result.outcome)
        lines.append(f"Result rev {result.revision}: {label} ({result.source}) {result.reason}")
    for transition in match.transitions.order_by("id"):
        lines.append(
            f"<t:{int(transition.created_at.timestamp())}:T> {transition.from_status or 'new'} "
            f"-> {transition.to_status} ({transition.source})"
        )
    events = RatingEvent.objects.filter(match=match).select_related("player", "run").order_by("id")
    rows = [
        f"{event.player.display_name[:14]:<14} {event.delta:+4d} -> {event.rating_after} "
        f"[{event.run.kind}]"
        for event in events[:24]
    ]
    names = dict(match.participants.values_list("player_id", "player__display_name"))
    for award in MatchAward.objects.filter(match=match).order_by("revision", "id"):
        who = names.get(award.player_id, "nobody") if award.player_id else "cleared"
        lines.append(f"Awards rev {award.revision}: {award.kind or '-'} {who} ({award.source})")
    for read in ScoreboardRead.objects.filter(match=match).order_by("id"):
        lines.append(
            f"Scoreboard read {read.pk}: {read.status}, winner {read.ocr_winner or '?'}, "
            f"badges {'clean' if read.badges_clean else 'unclear'}"
        )
    text = "\n".join(lines)
    if rows:
        text += "\n```\n" + "\n".join(rows) + "\n```"
    return text[:1900]


@match_group.command(name="explain", description="The audit trail for a match")
async def match_explain(interaction: Interaction[Any], match_id: int) -> None:
    async def run() -> None:
        community = await _staff_start(interaction, Area.MATCH_CONTROL, Area.DISPUTES)
        await reply(interaction, await db(_explain_text, community, match_id))

    await guarded(interaction, run)


async def _member_player(member: discord.Member | None) -> Player | None:
    if member is None:
        return None
    return await db(Player.objects.from_discord, member.id, member.display_name)


@match_group.command(name="awards", description="Set a match's MVP and key players")
@app_commands.describe(
    mvp="The MVP", key1="A key player", key2="Another key player", clear="Remove all awards"
)
async def match_awards(
    interaction: Interaction[Any],
    match_id: int,
    reason: str,
    mvp: discord.Member | None = None,
    key1: discord.Member | None = None,
    key2: discord.Member | None = None,
    clear: bool = False,
) -> None:
    async def run() -> None:
        community = await _staff_start(interaction, Area.RATINGS)
        match = await db(_get_match, community, match_id)
        staff = await actor(interaction)
        mvp_player = await _member_player(mvp)
        keys = [p for p in [await _member_player(key1), await _member_player(key2)] if p]
        if clear:
            picked: dict[int, str] = {}
        else:
            picked = awards.from_picks(mvp_player.pk if mvp_player else None, [p.pk for p in keys])
            if not picked:
                raise InvalidAction("Name an MVP or key player, or set clear.")
        preview = await db(corrections.preview_awards, match, picked)

        async def apply(confirmed: Interaction[Any]) -> None:
            await db(
                corrections.apply_award_correction,
                match_id,
                picked,
                AwardSource.STAFF,
                staff,
                reason,
            )
            await reply(confirmed, f"Awards for #{match_id} set. Staff awards beat the scoreboard.")

        text = f"Set the awards for #{match_id}?\n{await db(_preview_text, preview)}"
        await _send_confirm(interaction, text, apply)

    await guarded(interaction, run)


def _latest_read_id(community: Community, match_id: int) -> int:
    read = ocr.latest_read(_get_match(community, match_id))
    if read is None:
        raise InvalidAction("That match has no scoreboard read.")
    return read.pk


@match_group.command(name="names", description="Match scoreboard names to players")
async def match_names(interaction: Interaction[Any], match_id: int) -> None:
    async def run() -> None:
        community = await _staff_start(interaction, Area.DISPUTES)
        read_id = await db(_latest_read_id, community, match_id)
        await send_name_picker(interaction, match_id, read_id)

    await guarded(interaction, run)


@match_group.command(
    name="early_leave", description="Void a match because someone left in its first minutes"
)
@app_commands.describe(leaver="Who left. They get a leaver penalty; nobody's rating changes")
async def match_early_leave(
    interaction: Interaction[Any], match_id: int, leaver: discord.Member
) -> None:
    async def run() -> None:
        community = await _staff_start(interaction, Area.DISPUTES)
        match = await db(_get_match, community, match_id)
        staff = await actor(interaction)
        target = await db(Player.objects.from_discord, leaver.id, leaver.display_name)

        async def apply(confirmed: Interaction[Any]) -> None:
            await db(early_leave.staff_void, match.pk, target, staff)
            await reply(confirmed, f"Match #{match_id} voided: {leaver.display_name} left early.")

        await _send_confirm(
            interaction,
            f"Void match #{match_id} because {leaver.display_name} left early? Nobody's rating "
            "changes, they get a leaver penalty and everyone else goes back in the queue.",
            apply,
        )

    await guarded(interaction, run)


rating_group = app_commands.Group(name="rating", description="Staff: ratings")


@rating_group.command(name="seed", description="Staff: set a player's starting skill band")
@app_commands.describe(band="Where their rating starts, before their games settle it")
@app_commands.choices(
    band=[
        app_commands.Choice(name="New", value="new"),
        app_commands.Choice(name="Mid", value="mid"),
        app_commands.Choice(name="High", value="high"),
    ]
)
async def rating_seed(
    interaction: Interaction[Any], player: discord.Member, band: app_commands.Choice[str]
) -> None:
    async def run() -> None:
        community = await _staff_start(interaction, Area.RATINGS)
        staff = await actor(interaction)
        target = await db(Player.objects.from_discord, player.id, player.display_name)
        season = await db(Season.objects.open_for, community)
        event = await db(ratings.seed_player, season, target, band.value, staff)
        await reply(
            interaction,
            f"{player.display_name} is seeded {band.value}. Their shown rating is "
            f"{event.rating_after} until games confirm it.",
        )

    await guarded(interaction, run)


@rating_group.command(name="adjust", description="Staff: change a player's rating, with a reason")
async def rating_adjust(
    interaction: Interaction[Any], player: discord.Member, delta: int, reason: str
) -> None:
    async def run() -> None:
        community = await _staff_start(interaction, Area.RATINGS)
        staff = await actor(interaction)
        target = await db(Player.objects.from_discord, player.id, player.display_name)
        season = await db(Season.objects.open_for, community)
        event = await db(ratings.adjust_player, season, target, delta, staff, reason)
        await reply(interaction, f"{player.display_name} is now {event.rating_after}.")

    await guarded(interaction, run)


queue_admin_group = app_commands.Group(name="queue_admin", description="Staff: the match queue")


@queue_admin_group.command(name="kick", description="Remove a player from the queue")
async def queue_kick(interaction: Interaction[Any], player: discord.Member) -> None:
    async def run() -> None:
        community = await _staff_start(interaction, Area.MATCH_CONTROL)
        target = await db(Player.objects.from_discord, player.id, player.display_name)
        removed = await db(queue.kick, community.pk, target)
        await reply(interaction, "Removed." if removed else "They weren't in the queue.")

    await guarded(interaction, run)


@queue_admin_group.command(name="clear", description="Empty the queue")
async def queue_clear(interaction: Interaction[Any]) -> None:
    async def run() -> None:
        community = await _staff_start(interaction, Area.MATCH_CONTROL)
        removed = await db(queue.clear, community.pk)
        await reply(interaction, f"Cleared {removed} players from the queue.")

    await guarded(interaction, run)


ban_group = app_commands.Group(name="ban", description="Staff: queue bans (cooldowns) and strikes")


@ban_group.command(name="add", description="Ban a player from the queue for a while")
@app_commands.choices(
    kind=[
        app_commands.Choice(name="Dodge", value="dodge"),
        app_commands.Choice(name="Leaver", value="leaver"),
        app_commands.Choice(name="False report", value="false_report"),
        app_commands.Choice(name="Manual", value="manual"),
    ]
)
@app_commands.describe(minutes="Leave empty to use the escalating ladder for this kind")
async def ban_add(
    interaction: Interaction[Any],
    player: discord.Member,
    kind: app_commands.Choice[str],
    reason: str,
    minutes: app_commands.Range[int, 1, 525600] | None = None,
) -> None:
    async def run() -> None:
        community = await _staff_start(interaction, Area.MODERATION)
        staff = await actor(interaction)
        target = await db(Player.objects.from_discord, player.id, player.display_name)
        penalty = await db(
            penalties.issue,
            community,
            target,
            kind.value,
            reason=reason,
            issued_by=staff,
            minutes=minutes,
        )
        await reply(
            interaction,
            f"{player.display_name} can't queue until <t:{int(penalty.expires_at.timestamp())}:f>.",
        )

    await guarded(interaction, run)


@ban_group.command(name="revoke", description="Lift a player's active queue ban")
@app_commands.describe(keep_strikes="Keep the strikes it added. By default they go too")
async def ban_revoke(
    interaction: Interaction[Any], player: discord.Member, keep_strikes: bool = False
) -> None:
    async def run() -> None:
        community = await _staff_start(interaction, Area.MODERATION)
        target = await db(Player.objects.from_discord, player.id, player.display_name)
        count = await db(penalties.revoke_active, community, target, keep_strikes=keep_strikes)
        strikes = "kept" if keep_strikes else "removed"
        await reply(interaction, f"Lifted {count} cooldown(s); their strikes are {strikes}.")

    await guarded(interaction, run)


@ban_group.command(name="strikes", description="Add or remove dodge strikes by hand")
@app_commands.describe(delta="Positive adds strikes, negative removes them")
async def ban_strikes(
    interaction: Interaction[Any],
    player: discord.Member,
    delta: app_commands.Range[int, -20, 20],
    reason: str,
) -> None:
    async def run() -> None:
        community = await _staff_start(interaction, Area.MODERATION)
        staff = await actor(interaction)
        target = await db(Player.objects.from_discord, player.id, player.display_name)
        now_standing = await db(standing.adjust_strikes, community, target, delta, staff, reason)
        policy = await db(standing.strike_policy, community)
        await reply(
            interaction, f"{player.display_name}: {standing.describe(now_standing, policy)}"
        )

    await guarded(interaction, run)


captain_group = app_commands.Group(name="captain", description="Staff: who may captain")


async def _set_captain(
    interaction: Interaction[Any], player: discord.Member, status: str, reason: str
) -> None:
    community = await _staff_start(interaction, Area.MODERATION)
    staff = await actor(interaction)
    target = await db(Player.objects.from_discord, player.id, player.display_name)
    await db(standing.set_override, community, target, status, staff, reason)
    text = {
        "allow": f"{player.display_name} can captain, whatever their games.",
        "bar": f"{player.display_name} can't captain until staff clear it.",
        "clear": f"{player.display_name} is back on the normal captain rule.",
    }[status]
    await reply(interaction, text)


@captain_group.command(name="allow", description="Let a player captain before the match rule")
async def captain_allow(interaction: Interaction[Any], player: discord.Member, reason: str) -> None:
    await guarded(interaction, lambda: _set_captain(interaction, player, "allow", reason))


@captain_group.command(name="bar", description="Stop a player from captaining")
async def captain_bar(interaction: Interaction[Any], player: discord.Member, reason: str) -> None:
    await guarded(interaction, lambda: _set_captain(interaction, player, "bar", reason))


@captain_group.command(name="clear", description="Put a player back on the normal captain rule")
async def captain_clear(interaction: Interaction[Any], player: discord.Member, reason: str) -> None:
    await guarded(interaction, lambda: _set_captain(interaction, player, "clear", reason))


deadlock_group = app_commands.Group(
    name="deadlock", description="Staff: deadlock-api result checks and Steam links"
)


def _set_match_id(community: Community, match_id: int, deadlock_match_id: int) -> None:
    api_results.correct_deadlock_match_id(_get_match(community, match_id).pk, deadlock_match_id)


@deadlock_group.command(name="check", description="Set a match's Deadlock ID and check it now")
async def deadlock_check(
    interaction: Interaction[Any], match_id: int, deadlock_match_id: int
) -> None:
    async def run() -> None:
        community = await _staff_start(interaction, Area.DISPUTES)
        await db(_set_match_id, community, match_id, deadlock_match_id)
        await reply(
            interaction, f"Checking match #{match_id} against Deadlock {deadlock_match_id}."
        )

    await guarded(interaction, run)


@deadlock_group.command(name="unlink", description="Remove a player's linked Steam account")
async def deadlock_unlink(interaction: Interaction[Any], player: discord.Member) -> None:
    async def run() -> None:
        await _staff_start(interaction, Area.MODERATION)
        target = await db(Player.objects.from_discord, player.id, player.display_name)
        removed = await db(steam.unlink, target)
        await reply(interaction, "Unlinked." if removed else "They had no Steam account linked.")

    await guarded(interaction, run)


GROUPS: tuple[app_commands.Group, ...] = (
    match_group,
    rating_group,
    queue_admin_group,
    ban_group,
    captain_group,
    deadlock_group,
)
COMMANDS: tuple[app_commands.Command[Any, Any, Any], ...] = ()
