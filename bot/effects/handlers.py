"""What each outbox effect does. Each handler is safe to run again after a crash or retry."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass

from bot.db import db
from bot.effects import flow
from bot.effects.gateway import ChannelGone, Gateway
from bot.renderers import names
from bot.renderers.alerts import match_notice, render_alert
from bot.renderers.board import (
    render_board,
    render_pickers,
    render_ready_dm,
    render_sub_offer_dm,
    render_text_dm,
    render_voice_dm,
)
from bot.renderers.queue import render_queue
from bot.renderers.results import (
    render_correction,
    render_results,
    render_scoreboard_notice,
)
from league.domain.engine import Status
from league.integrations import deadlock_api
from league.models import Community, Match, OutboxEffect
from league.models.alerts import AlertStatus
from league.models.matches import ResourceKind
from league.services import (
    alerts,
    api_results,
    boards,
    draft,
    effects,
    ocr,
    permissions,
    runtime,
    scrims,
    subs,
)
from league.services.common import add_effect
from league.services.common import render_board as request_board

logger = logging.getLogger(__name__)

# Long enough to outlast a ready check and its backfills.
INVITE_MAX_AGE_SECONDS = 1800


class Skip(Exception):
    """Nothing to do, and that's fine: for example, the channel was already deleted."""


@dataclass(frozen=True, slots=True)
class Env:
    gateway: Gateway
    effect: OutboxEffect
    community: Community
    match: Match | None

    @property
    def guild_id(self) -> int:
        return self.community.discord_guild_id

    @property
    def required_match(self) -> Match:
        if self.match is None:
            raise ValueError(f"{self.effect.kind} needs a match")
        return self.match

    @property
    def match_id(self) -> int:
        return self.required_match.pk


Handler = Callable[[Env], Awaitable[None]]
HANDLERS: dict[str, Handler] = {}


def effect(kind: str) -> Callable[[Handler], Handler]:
    def register(handler: Handler) -> Handler:
        HANDLERS[kind] = handler
        return handler

    return register


def _active_user_ids(match: Match) -> list[int]:
    return list(
        match.participants.filter(is_active=True).values_list("player__discord_user_id", flat=True)
    )


def _team_user_ids(match: Match, team: str) -> list[int]:
    return list(
        match.participants.filter(team=team, removed_reason="").values_list(
            "player__discord_user_id", flat=True
        )
    )


async def _text_channel(env: Env) -> int:
    channel_id = await db(effects.resource_id, env.match_id, ResourceKind.TEXT)
    if channel_id is None:
        raise Skip("No lobby text channel.")
    return channel_id


def _reload(match_id: int) -> Match:
    return Match.objects.select_related("community").get(pk=match_id)


async def _notice(
    env: Env, text: str, *, user_ids: Iterable[int] = (), role_ids: Iterable[int] = ()
) -> int:
    """Post a message about the flow. It stays until the match moves on, with the board below it.

    The board moves in its own effect, so a failed move can't retry this and ping people twice.
    """
    message_id = await env.gateway.send_text(
        await _text_channel(env), text, user_ids=user_ids, role_ids=role_ids
    )
    await db(effects.record_notice, env.match_id, message_id)
    await db(_request_board, env.match_id)
    return message_id


READY_PING_TEXT = (
    "your lobby is ready. Press **Ready** on the board below, and wait in the Waiting Room."
)


def _open_voice(community_id: int) -> bool:
    return runtime.of(community_id).open_match_voice


def _match_staff_roles(community_id: int) -> list[int]:
    """Roles that see every match's channels: whoever looks after matches."""
    return permissions.role_ids_with(community_id, permissions.MATCH_STAFF_AREAS)


def _request_board(match_id: int) -> None:
    request_board(_reload(match_id))


# --- Lobby -----------------------------------------------------------------------------------


@effect("create_lobby")
async def create_lobby(env: Env) -> None:
    existing = await db(effects.resources, env.match_id)
    members = await db(_active_user_ids, env.required_match)
    community = env.community
    if ResourceKind.TEXT not in existing:
        text_id = await env.gateway.create_text_channel(
            env.guild_id,
            community.match_category_id,
            names.match_text(env.match_id),
            members,
            await db(_match_staff_roles, community.pk),
        )
        await db(effects.record_resource, env.match_id, ResourceKind.TEXT, text_id)
    # No lobby voice of its own: the Waiting Room is the lobby until teams have their channels.
    message_id = await _notice(env, READY_PING_TEXT, user_ids=members)
    await db(effects.record_ready_ping, env.match_id, message_id)


@effect(effects.READY_PING_KIND)
async def refresh_ready_ping(env: Env) -> None:
    """Someone pressed Ready: the ping now mentions only those who haven't. An edit pings nobody."""
    channel_id, message_id, unready = await db(effects.ready_ping, env.match_id)
    if channel_id is None or message_id is None:
        raise Skip("The ready check is over.")
    if not unready:  # Everyone still here is ready (the rest missed it): nobody left to call.
        with contextlib.suppress(ChannelGone):
            await env.gateway.delete_message(channel_id, message_id)
        await db(effects.mark_notice_deleted, env.match_id, message_id)
        return
    await env.gateway.edit_text(channel_id, message_id, READY_PING_TEXT, user_ids=unready)


def channel_url(guild_id: int, channel_id: int | None) -> str | None:
    """A link that opens the channel, for DMs where a <#channel> mention may not resolve."""
    return f"https://discord.com/channels/{guild_id}/{channel_id}" if channel_id else None


@effect("gather_player")
async def gather_player(env: Env) -> None:
    """The Waiting Room is the lobby. Already there: nothing to do, the board's ping calls them.
    Anywhere else: DM an invite to it with a Ready button. They choose when to join."""
    user_id = int(env.effect.payload["discord_user_id"])
    is_sub = bool(env.effect.payload.get("sub"))
    resources = await db(effects.resources, env.match_id)
    link = channel_url(env.guild_id, resources.get(ResourceKind.TEXT))
    if is_sub:
        await _gather_sub(env, user_id, resources, link)
        return
    waiting_room = env.community.waiting_room_channel_id
    if waiting_room and user_id in env.gateway.voice_member_ids(env.guild_id, waiting_room):
        return
    invite = (
        await env.gateway.create_invite(env.guild_id, waiting_room, INVITE_MAX_AGE_SECONDS)
        if waiting_room
        else None
    )
    view = render_ready_dm(env.match_id, invite, heading="Ready Up", channel_url=link)
    if not await env.gateway.send_dm(user_id, view):
        await _notice(
            env,
            "I couldn't DM you. Join the Waiting Room and press Ready on the board.",
            user_ids=[user_id],
        )


async def _gather_sub(env: Env, user_id: int, resources: dict[str, int], link: str | None) -> None:
    """A sub joins wherever the match is now: their team's voice once teams are set, the
    Waiting Room before that."""
    team = await db(_team_of, env.match_id, user_id)
    waiting_room = env.community.waiting_room_channel_id
    team_voice = resources.get(_team_voice_kind(team))
    target = team_voice or waiting_room
    if team_voice is not None and waiting_room:
        here = user_id in env.gateway.voice_member_ids(env.guild_id, waiting_room)
        if here and await env.gateway.move_member(env.guild_id, user_id, team_voice):
            return
    elif target is not None and user_id in env.gateway.voice_member_ids(env.guild_id, target):
        target = None  # Already in the Waiting Room: no invite needed.
    invite = (
        await env.gateway.create_invite(env.guild_id, target, INVITE_MAX_AGE_SECONDS)
        if target is not None
        else None
    )
    if await db(_needs_ready, env.match_id, user_id):
        view = render_ready_dm(env.match_id, invite, heading="You're subbing in", channel_url=link)
    else:
        view = render_voice_dm(
            env.match_id,
            invite,
            heading="You're subbing in",
            body="Join voice and keep an eye on the board.",
            channel_url=link,
            voice_label="Join voice",
        )
    if not await env.gateway.send_dm(user_id, view):
        await _notice(env, "you're in. Join voice and check the board.", user_ids=[user_id])


def _needs_ready(match_id: int, user_id: int) -> bool:
    match = Match.objects.get(pk=match_id)
    return (
        match.status == Status.READY_CHECK
        and match.participants.filter(
            player__discord_user_id=user_id, is_active=True, ready_at__isnull=True
        ).exists()
    )


@effect("sub_offer")
async def sub_offer(env: Env) -> None:
    """Offer an open spot by DM, which is the only place it goes. If the DM can't reach them,
    the next person is asked."""
    offer_id = int(env.effect.payload["offer_id"])
    info = await db(subs.offer_info, offer_id)
    if not info.pending:
        raise Skip("The offer has closed.")
    team = await db(_team_label, env.match_id, info.team)
    if not await env.gateway.send_dm(info.discord_user_id, render_sub_offer_dm(info, team)):
        await db(subs.fail_offer, offer_id)


@effect("close_sub_offer")
async def close_sub_offer(env: Env) -> None:
    info = await db(subs.offer_info, int(env.effect.payload["offer_id"]))
    if info.notice_channel_id is None or info.notice_message_id is None:
        raise Skip("No mention was posted.")
    with contextlib.suppress(ChannelGone):
        await env.gateway.delete_message(info.notice_channel_id, info.notice_message_id)
    await db(subs.record_offer_notice, info.offer_id, None, None)


def _team_label(match_id: int, team: str) -> str:
    captains = boards.captain_names(Match.objects.get(pk=match_id))
    return boards.team_name(captains[team]) if team in captains else ""


@effect("grant_access")
async def grant_access(env: Env) -> None:
    user_id = int(env.effect.payload["discord_user_id"])
    resources = await db(effects.resources, env.match_id)
    team = await db(_team_of, env.match_id, user_id)
    kinds = (ResourceKind.TEXT, _team_voice_kind(team))
    for kind in kinds:
        channel_id = resources.get(kind)
        if channel_id:
            await env.gateway.grant_member(channel_id, user_id)


def _team_of(match_id: int, user_id: int) -> str:
    participant = (
        Match.objects.get(pk=match_id)
        .participants.filter(player__discord_user_id=user_id, is_active=True)
        .first()
    )
    return participant.team if participant else ""


def _team_voice_kind(team: str) -> str:
    return {"A": ResourceKind.TEAM_A_VOICE, "B": ResourceKind.TEAM_B_VOICE}.get(team, "")


@effect("remove_player")
async def remove_player(env: Env) -> None:
    user_id = int(env.effect.payload["discord_user_id"])
    resources = await db(effects.resources, env.match_id)
    voice_kinds = {
        ResourceKind.LOBBY_VOICE,
        ResourceKind.TEAM_A_VOICE,
        ResourceKind.TEAM_B_VOICE,
    }
    waiting = env.community.waiting_room_channel_id
    for kind, discord_id in resources.items():
        if (
            kind in voice_kinds
            and user_id in env.gateway.voice_member_ids(env.guild_id, discord_id)
            and waiting
        ):
            await env.gateway.move_member(env.guild_id, user_id, waiting)
        if kind in voice_kinds or kind == ResourceKind.TEXT:
            await env.gateway.revoke_member(discord_id, user_id)


# --- Boards ----------------------------------------------------------------------------------


# The champion grid's messages, top to bottom. They sit directly below the board.
GRID_KINDS = (ResourceKind.PICKER_MESSAGE, ResourceKind.PICKER_MESSAGE_2)


def _match_flow(resources: dict[str, int], text_id: int) -> flow.FlowMessages:
    return flow.FlowMessages(
        text_id,
        resources.get(ResourceKind.BOARD_MESSAGE),
        tuple(resources.get(kind) for kind in GRID_KINDS),
    )


@dataclass(frozen=True, slots=True)
class _MatchFlowStore:
    """A match's board and grid messages live in its resources."""

    match_id: int

    async def save_board(self, message_id: int) -> None:
        await db(effects.record_resource, self.match_id, ResourceKind.BOARD_MESSAGE, message_id)

    async def save_grid(self, index: int, message_id: int | None) -> None:
        kind = GRID_KINDS[index]
        if message_id is None:
            await db(effects.mark_resource_deleted, self.match_id, kind)
        else:
            await db(effects.record_resource, self.match_id, kind, message_id)

    async def delete_later(self, channel_id: int, message_id: int) -> None:
        await db(_queue_delete, channel_id, message_id, match_id=self.match_id)


async def _render_board(env: Env) -> None:
    resources = await db(effects.resources, env.match_id)
    channel_id = await db(effects.board_channel, env.match_id)
    if channel_id is None:
        raise Skip("Lobby channel isn't up yet; creating it renders the board.")
    state = await db(boards.board_state, env.match_id)
    try:
        reposted = await flow.render(
            env.gateway,
            _MatchFlowStore(env.match_id),
            _match_flow(resources, channel_id),
            render_board(state),
            render_pickers(state),
            log_extra={"match": env.match_id},
        )
    except ChannelGone:
        if state.is_scrim:
            # Its channel is gone, or was never ours to post in: free it rather than block it.
            await db(scrims.close_gone, env.match_id)
        raise
    if reposted:
        await db(effects.cancel_board_moves, env.match_id)  # Chat now starts counting afresh.


@effect("render_board")
async def render_board_effect(env: Env) -> None:
    await _render_board(env)


@effect("move_board")
async def move_board(env: Env) -> None:
    """Chat has built up below the board, unless a state change has already moved it since."""
    resources = await db(effects.resources, env.match_id)
    channel_id = await db(effects.board_channel, env.match_id)
    if channel_id is None or ResourceKind.BOARD_MESSAGE not in resources:
        raise Skip("The channel has closed.")
    try:
        bottom = await flow.at_bottom(env.gateway, _match_flow(resources, channel_id))
    except ChannelGone:
        if await db(scrims.is_host_channel, channel_id):
            await db(scrims.close_gone, env.match_id)
        raise
    if bottom:
        raise Skip("The board is already last.")
    await _render_board(env)


@effect("clear_notices")
async def clear_notices(env: Env) -> None:
    text_id = await db(effects.resource_id, env.match_id, ResourceKind.TEXT)
    if text_id is None:
        raise Skip("The channel has closed.")
    for message_id in await db(effects.live_notices, env.match_id):
        await env.gateway.delete_message(text_id, message_id)
        await db(effects.mark_notice_deleted, env.match_id, message_id)


@effect("render_queue")
async def render_queue_effect(env: Env) -> None:
    community = env.community
    if not community.queue_channel_id:
        raise Skip("Queue channel isn't set up.")
    view = render_queue(await db(boards.queue_view, community))
    if community.queue_message_id:
        try:
            await env.gateway.edit_view(
                community.queue_channel_id, community.queue_message_id, view
            )
            return
        except ChannelGone:
            logger.warning("Queue message is gone; posting a new one")
    from league.services import community as community_service

    message_id = await env.gateway.send_view(community.queue_channel_id, view)
    await db(community_service.save_wiring, community.pk, queue_message_id=message_id)


def _leaderboard_pages(community_id: int) -> tuple[int | None, list[int], list[str]]:
    from bot.renderers.leaderboard import pages
    from league.services import common, leaderboards

    community = Community.objects.get(pk=community_id)
    season = common.open_season(community)
    title = f"Leaderboard · {season.name}"
    rows = leaderboards.table(season)
    return (
        community.leaderboard_channel_id,
        list(community.leaderboard_message_ids),
        pages(rows, leaderboards.label(community), title),
    )


@effect("render_leaderboard")
async def render_leaderboard_effect(env: Env) -> None:
    """Every player's rating and win rate, over as many messages as it takes. Edits the ones
    already there, posts any more it needs and deletes any it no longer does."""
    from league.services import leaderboards

    channel_id, message_ids, texts = await db(_leaderboard_pages, env.community.pk)
    if not channel_id:
        raise Skip("Leaderboard channel isn't set up.")
    kept: list[int] = []
    for index, text in enumerate(texts):
        if index < len(message_ids):
            try:
                await env.gateway.edit_text(channel_id, message_ids[index], text)
                kept.append(message_ids[index])
                continue
            except ChannelGone:
                # A message was deleted: start again from here, so the pages stay in order.
                for stale in message_ids[index:]:
                    with contextlib.suppress(ChannelGone):
                        await env.gateway.delete_message(channel_id, stale)
                message_ids = message_ids[:index]
        kept.append(await env.gateway.send_text(channel_id, text))
        await db(leaderboards.save_messages, env.community.pk, kept + message_ids[len(kept) :])
    for stale in message_ids[len(texts) :]:
        with contextlib.suppress(ChannelGone):
            await env.gateway.delete_message(channel_id, stale)
    await db(leaderboards.save_messages, env.community.pk, kept)


# --- Messages --------------------------------------------------------------------------------


@effect("ping")
async def ping(env: Env) -> None:
    await _notice(
        env,
        str(env.effect.payload["text"]),
        user_ids=[int(uid) for uid in env.effect.payload["user_ids"]],
    )


@effect("dm_player")
async def dm_player(env: Env) -> None:
    """A note for one player only. It never goes to a channel: if their DMs are closed, it's
    dropped."""
    payload = env.effect.payload
    view = render_text_dm(env.match_id, str(payload["heading"]), str(payload["text"]))
    if not await env.gateway.send_dm(int(payload["discord_user_id"]), view):
        raise Skip("DMs are closed.")


@effect("ping_lobby")
async def ping_lobby(env: Env) -> None:
    await _notice(env, str(env.effect.payload["text"]))


# --- Staff alerts --------------------------------------------------------------------------


@effect(alerts.POST_KIND)
async def post_staff_alert(env: Env) -> None:
    """Post the card, pinging the roles that hold its area. A re-ping posts it again at the
    bottom and only then deletes the old one, so the card is never missing."""
    alert_id = int(env.effect.payload["alert_id"])
    reping = bool(env.effect.payload.get("reping"))
    card = await db(alerts.card, alert_id)
    if card.status != AlertStatus.OPEN:
        raise Skip("Alert already closed.")
    target, old_channel, old_message = await db(alerts.where_to_post, alert_id)
    if target is None:
        raise Skip("No staff channel and no match channel to post the alert in.")
    if reping or old_message is None:
        message_id = await env.gateway.send_view(
            target, render_alert(card), ping_role_ids=card.ping_role_ids
        )
        await db(alerts.record_card, alert_id, target, message_id)
        if old_channel is not None and old_message is not None:
            with contextlib.suppress(ChannelGone):
                await env.gateway.delete_message(old_channel, old_message)
    if not reping and card.kind in alerts.MATCH_NOTICE_KINDS and env.match is not None:
        staff_channel = env.community.staff_channel_id
        if staff_channel is not None and staff_channel == target:
            with contextlib.suppress(Skip):
                await _notice(env, match_notice(card))


@effect(alerts.REFRESH_KIND)
async def refresh_staff_alert(env: Env) -> None:
    alert_id = int(env.effect.payload["alert_id"])
    _target, channel_id, message_id = await db(alerts.where_to_post, alert_id)
    if channel_id is None or message_id is None:
        raise Skip("The card was never posted.")
    try:
        await env.gateway.edit_view(
            channel_id, message_id, render_alert(await db(alerts.card, alert_id))
        )
    except ChannelGone as exc:
        raise Skip("The card is gone.") from exc


@effect("announce_lobby_code")
async def announce_lobby_code(env: Env) -> None:
    match = await db(_reload, env.match_id)
    members = await db(_active_user_ids, match)
    await _notice(env, f"Lobby code: `{match.lobby_code}`", user_ids=members)
    resources = await db(effects.resources, env.match_id)
    for kind in (ResourceKind.TEAM_A_VOICE, ResourceKind.TEAM_B_VOICE):
        channel_id = resources.get(kind)
        if channel_id:
            await env.gateway.set_voice_status(channel_id, f"Lobby code: {match.lobby_code}")


@effect("report_reminder")
async def report_reminder(env: Env) -> None:
    match = await db(_reload, env.match_id)
    if match.status != Status.IN_PROGRESS:
        raise Skip("The result is already in.")
    captains = await db(_captain_ids, match)
    await _notice(
        env,
        "if your game has ended, press the team that won on the board and add the scoreboard.",
        user_ids=captains,
    )


def _captain_ids(match: Match) -> list[int]:
    return list(
        match.participants.filter(is_captain=True, is_active=True).values_list(
            "player__discord_user_id", flat=True
        )
    )


# --- Team voice ------------------------------------------------------------------------------


def _enqueue_team_moves(match_id: int, user_ids: list[tuple[int, str]]) -> None:
    match = Match.objects.select_related("community").get(pk=match_id)
    for user_id, team in user_ids:
        add_effect(
            match.community,
            "team_move_player",
            {"discord_user_id": user_id, "team": team},
            match=match,
            dedupe_key=f"team_move:{match_id}:{user_id}",
        )
    add_effect(
        match.community,
        "delete_lobby_voice",
        match=match,
        dedupe_key=f"delete_lobby_voice:{match_id}",
    )


@effect("create_team_voice")
async def create_team_voice(env: Env) -> None:
    resources = await db(effects.resources, env.match_id)
    community = env.community
    assignments: list[tuple[int, str]] = []
    captains = await db(boards.captain_names, env.required_match)
    for team, kind in (("A", ResourceKind.TEAM_A_VOICE), ("B", ResourceKind.TEAM_B_VOICE)):
        members = await db(_team_user_ids, env.required_match, team)
        assignments.extend((user_id, team) for user_id in members)
        if kind in resources:
            continue
        channel_id = await env.gateway.create_voice_channel(
            env.guild_id,
            community.match_category_id,
            names.team_voice(env.match_id, captains.get(team, "")),
            members,
            await db(_match_staff_roles, community.pk),
            open_to_everyone=await db(_open_voice, community.pk),
        )
        await db(effects.record_resource, env.match_id, kind, channel_id)
    await db(_enqueue_team_moves, env.match_id, assignments)


@effect("team_move_player")
async def team_move_player(env: Env) -> None:
    """In the Waiting Room: move them. Anywhere else: DM an invite to their team's channel."""
    user_id = int(env.effect.payload["discord_user_id"])
    resources = await db(effects.resources, env.match_id)
    team_channel = resources.get(_team_voice_kind(str(env.effect.payload["team"])))
    if team_channel is None:
        raise Skip("Team channel is gone.")
    # A lobby voice only exists for a match that popped before the Waiting Room became the lobby.
    lobbies = (env.community.waiting_room_channel_id, resources.get(ResourceKind.LOBBY_VOICE))
    in_lobby = any(
        user_id in env.gateway.voice_member_ids(env.guild_id, channel)
        for channel in lobbies
        if channel
    )
    if in_lobby and await env.gateway.move_member(env.guild_id, user_id, team_channel):
        return
    invite = await env.gateway.create_invite(env.guild_id, team_channel, INVITE_MAX_AGE_SECONDS)
    view = render_voice_dm(
        env.match_id,
        invite,
        heading="Teams picked",
        subtitle=False,
        channel_url=channel_url(env.guild_id, resources.get(ResourceKind.TEXT)),
    )
    if not await env.gateway.send_dm(user_id, view):
        await _notice(env, "teams are set. Join your team's voice channel.", user_ids=[user_id])


@effect("swap_team_voice")
async def swap_team_voice(env: Env) -> None:
    """Two players changed teams: each gets their new team's voice and loses the old one, and
    anyone in their old team's voice is moved across."""
    resources = await db(effects.resources, env.match_id)
    for move in env.effect.payload["moves"]:
        user_id = int(move["discord_user_id"])
        team = str(move["team"])
        new_channel = resources.get(_team_voice_kind(team))
        old_channel = resources.get(_team_voice_kind("B" if team == "A" else "A"))
        if new_channel is None or old_channel is None:
            continue  # Team voice isn't up: creating it reads the teams as they are now.
        await env.gateway.grant_member(new_channel, user_id)
        if user_id in env.gateway.voice_member_ids(env.guild_id, old_channel):
            await env.gateway.move_member(env.guild_id, user_id, new_channel)
        await env.gateway.revoke_member(old_channel, user_id)


@effect("delete_lobby_voice")
async def delete_lobby_voice(env: Env) -> None:
    channel_id = await db(effects.resource_id, env.match_id, ResourceKind.LOBBY_VOICE)
    if channel_id is None:
        raise Skip("Already deleted.")
    await env.gateway.delete_channel(channel_id)
    await db(effects.mark_resource_deleted, env.match_id, ResourceKind.LOBBY_VOICE)


# --- Results ---------------------------------------------------------------------------------


@effect("post_results")
async def post_results(env: Env) -> None:
    results_channel = env.community.results_channel_id
    if not results_channel:
        raise Skip("Results channel isn't set up.")
    if await db(effects.resource_id, env.match_id, ResourceKind.RESULTS_MESSAGE):
        raise Skip("Already posted.")  # A retry after a crash must not post twice.
    view_model = await db(boards.results_view, env.match_id)
    file = None
    shot = view_model.screenshot
    if shot is not None and shot.archive_channel_id and shot.archive_message_id:
        fetched = await env.gateway.fetch_attachment(
            shot.archive_channel_id, shot.archive_message_id, shot.attachment_id or 0
        )
        if fetched is not None:
            suffix = fetched[0].rsplit(".", 1)[-1] if "." in fetched[0] else "png"
            file = (f"match-{env.match_id}.{suffix}", fetched[1])
    view = render_results(view_model, attachment_name=file[0] if file else None)
    message_id = await env.gateway.send_view(results_channel, view, file=file)
    await db(effects.record_resource, env.match_id, ResourceKind.RESULTS_MESSAGE, message_id)


async def _results_attachment_name(env: Env, view_model: boards.ResultsView) -> str | None:
    shot = view_model.screenshot
    if shot is None or not shot.archive_channel_id or not shot.archive_message_id:
        return None
    fetched = await env.gateway.fetch_attachment(
        shot.archive_channel_id, shot.archive_message_id, shot.attachment_id or 0
    )
    if fetched is None:
        return None
    suffix = fetched[0].rsplit(".", 1)[-1] if "." in fetched[0] else "png"
    return f"match-{env.match_id}.{suffix}"


@effect("refresh_results")
async def refresh_results(env: Env) -> None:
    """Awards or stats arrived after the results were posted: edit the post in place."""
    results_channel = env.community.results_channel_id
    message_id = await db(effects.resource_id, env.match_id, ResourceKind.RESULTS_MESSAGE)
    if not results_channel or not message_id:
        raise Skip("No results post to refresh.")
    view_model = await db(boards.results_view, env.match_id)
    name = await _results_attachment_name(env, view_model)
    await env.gateway.edit_view(
        results_channel, message_id, render_results(view_model, attachment_name=name)
    )


# --- Score OCR -------------------------------------------------------------------------------


@effect("read_scoreboard")
async def read_scoreboard(env: Env) -> None:
    """Read a report screenshot. A failed read is recorded, never retried in a loop: the result
    stands without it, and staff can still set awards by hand."""
    submission_id = int(env.effect.payload["submission_id"])
    where = await db(ocr.submission_image, submission_id)
    if where is None:
        raise Skip("The screenshot isn't archived.")
    if not ocr.available():
        await db(ocr.record_failure, submission_id, "failed", "Score OCR isn't installed here.")
        raise Skip("Score OCR isn't installed.")
    fetched = await env.gateway.fetch_attachment(*where)
    if fetched is None:
        raise Skip("The archived screenshot is gone.")
    try:
        result = await asyncio.to_thread(ocr.read_image, fetched[1])
    except Exception as exc:
        status = "rejected" if ocr.is_not_a_scoreboard(exc) else "failed"
        if status == "failed":
            logger.exception("Scoreboard read failed", extra={"match": env.match_id})
        await db(ocr.record_failure, submission_id, status, f"{type(exc).__name__}: {exc}")
        return
    await db(ocr.ingest, submission_id, result)


@effect("create_api_lobby")
async def create_api_lobby(env: Env) -> None:
    """Ask deadlock-api's bot to host the lobby. Any failure hands it back to the captain."""
    region = (await db(runtime.of, env.community.pk)).lobby_region
    try:
        lobby_ = await asyncio.to_thread(deadlock_api.create_custom_match, region, "normal")
    except deadlock_api.ApiError as exc:
        await db(draft.api_lobby_failed, env.match_id, str(exc))
        return
    await db(draft.accept_api_lobby, env.match_id, lobby_.party_id, lobby_.party_code)


@effect("fetch_api_match_id")
async def fetch_api_match_id(env: Env) -> None:
    """Deadlock's match ID for a started API lobby, so the result can be checked later."""
    match = await db(_reload, env.match_id)
    if not match.api_party_id or match.deadlock_match_id is not None:
        raise Skip("Nothing to fetch.")
    attempt = int(env.effect.payload.get("attempt", 1))
    try:
        found = await asyncio.to_thread(deadlock_api.custom_match_id, match.api_party_id)
    except deadlock_api.ApiError:
        found = None
    await db(draft.record_api_match_id, env.match_id, found, attempt)


@effect("check_match_api")
async def check_match_api(env: Env) -> None:
    """Fetch the match from deadlock-api and compare. A miss is recorded and retried later by
    its own new effect, never by failing this one."""
    deadlock_match_id = int(env.effect.payload["deadlock_match_id"])
    try:
        data = await asyncio.to_thread(deadlock_api.match_metadata, deadlock_match_id)
    except deadlock_api.ApiError as exc:
        await db(
            api_results.record_miss, env.match_id, deadlock_match_id, "error", exc.status, str(exc)
        )
        return
    if data is None:
        await db(api_results.record_miss, env.match_id, deadlock_match_id, "not_found", 404, "")
        return
    await db(api_results.record_metadata, env.match_id, deadlock_match_id, data)


@effect("scoreboard_notice")
async def scoreboard_notice(env: Env) -> None:
    """Ask the captains to match the scoreboard names the reader couldn't place."""
    read_id = int(env.effect.payload["read_id"])
    unmapped = int(env.effect.payload.get("unmapped", 0))
    channel_id = await _text_channel(env)
    view = render_scoreboard_notice(env.match_id, read_id, unmapped)
    message_id = await env.gateway.send_view(channel_id, view)
    await db(effects.record_notice, env.match_id, message_id)
    await db(_request_board, env.match_id)


@effect("post_correction")
async def post_correction(env: Env) -> None:
    results_channel = env.community.results_channel_id
    if not results_channel:
        raise Skip("Results channel isn't set up.")
    run_id = env.effect.payload.get("run_id")
    view_model = await db(
        boards.correction_view,
        env.match_id,
        int(run_id) if run_id else None,
        str(env.effect.payload.get("outcome", "")),
        str(env.effect.payload.get("reason", "")),
    )
    await env.gateway.send_view(results_channel, render_correction(view_model))


# --- Cleanup ---------------------------------------------------------------------------------


@effect("restart_voice")
async def restart_voice(env: Env) -> None:
    """A restart: teams are gone, so everyone goes back to the Waiting Room and the old match's
    team channels are deleted. Runs in the successor's lane, before anyone new is gathered."""
    old_id = int(env.effect.payload["old_id"])
    waiting_room = env.community.waiting_room_channel_id
    resources = await db(effects.resources, old_id)
    for kind in (ResourceKind.TEAM_A_VOICE, ResourceKind.TEAM_B_VOICE):
        channel_id = resources.get(kind)
        if channel_id is None:
            continue
        if waiting_room:
            for user_id in env.gateway.voice_member_ids(env.guild_id, channel_id):
                await env.gateway.move_member(env.guild_id, user_id, waiting_room)
        await env.gateway.delete_channel(channel_id)
        await db(effects.mark_resource_deleted, old_id, kind)


@effect("cleanup_voice")
async def cleanup_voice(env: Env) -> None:
    resources = await db(effects.resources, env.match_id)
    waiting = env.community.waiting_room_channel_id
    for kind in (ResourceKind.LOBBY_VOICE, ResourceKind.TEAM_A_VOICE, ResourceKind.TEAM_B_VOICE):
        channel_id = resources.get(kind)
        if channel_id is None:
            continue
        if waiting:
            for user_id in env.gateway.voice_member_ids(env.guild_id, channel_id):
                await env.gateway.move_member(env.guild_id, user_id, waiting)
        await env.gateway.delete_channel(channel_id)
        await db(effects.mark_resource_deleted, env.match_id, kind)


@effect("delete_text_channel")
async def delete_text_channel(env: Env) -> None:
    channel_id = await db(effects.resource_id, env.match_id, ResourceKind.TEXT)
    if channel_id is None:
        raise Skip("Already deleted.")
    if await db(scrims.is_host_channel, channel_id):
        raise Skip("A public channel a scrim ran in: never the bot's to delete.")
    await env.gateway.delete_channel(channel_id)
    await db(effects.mark_resource_deleted, env.match_id, ResourceKind.TEXT)


# --- Scrims ------------------------------------------------------------------------------------


@effect(scrims.DELETE_KIND)
async def delete_board(env: Env) -> None:
    """A stopped scrim: delete its board and grid, as Bebot did. Runs after any render in flight,
    so it reads the message IDs that render recorded."""
    channel_id = await db(effects.board_channel, env.match_id)
    if channel_id is None:
        raise Skip("No channel.")
    resources = await db(effects.resources, env.match_id)
    store = _MatchFlowStore(env.match_id)
    for index, kind in reversed(list(enumerate(GRID_KINDS))):
        message_id = resources.get(kind)
        if message_id is not None:
            with contextlib.suppress(ChannelGone):
                await env.gateway.delete_message(channel_id, message_id)
            await store.save_grid(index, None)
    board_id = resources.get(ResourceKind.BOARD_MESSAGE)
    if board_id is not None:
        with contextlib.suppress(ChannelGone):
            await env.gateway.delete_message(channel_id, board_id)
        await db(effects.mark_resource_deleted, env.match_id, ResourceKind.BOARD_MESSAGE)


def _queue_delete(channel_id: int, message_id: int, *, match_id: int) -> None:
    """A delete that failed mid-render, retried as a job of its own in the match's lane."""
    match = Match.objects.select_related("community").get(pk=match_id)
    add_effect(
        match.community,
        "delete_message",
        {"channel_id": channel_id, "message_id": message_id},
        match=match,
    )


@effect("delete_message")
async def delete_message_effect(env: Env) -> None:
    payload = env.effect.payload
    await env.gateway.delete_message(int(payload["channel_id"]), int(payload["message_id"]))
