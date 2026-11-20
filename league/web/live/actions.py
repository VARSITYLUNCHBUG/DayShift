"""What a player can do from the web page: each action's name, its arguments and its service call.

Every action calls the same `league.services` function as the Discord button, as the signed-in
player, and is checked there exactly as a click is. A refusal (`DomainError`) goes back as its
message in plain text; arguments that don't parse, and failures nobody expected, get a fixed
sentence and never a traceback.

Ids arrive as strings and are checked here. An action on a match, sub request, offer or
scoreboard read outside the web's server is refused as if it didn't exist, as the snapshots do.

Each action names the database topics it changes, so the socket can send the player's own fresh
snapshots before the ack (`hub.refresh`).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, WithJsonSchema, create_model

from league.domain.errors import DomainError, InvalidAction, NotAllowed, StaleAction
from league.integrations import deadlock_api
from league.models import Community, Match, Player, ScoreboardRead, SubOffer, SubRequest
from league.models.moderation import PenaltyKind
from league.services import (
    chat,
    draft,
    early_leave,
    live,
    lobby,
    ocr,
    queue,
    results,
    scrims,
    standing,
    subs,
    swaps,
    wishes,
)
from league.web.live import schema as s
from league.web.live.dbpool import web_db
from league.web.text import plain

logger = logging.getLogger(__name__)

BAD_REQUEST = "That didn't work. Refresh and try again."
FAILED = "Something went wrong on our side. Please try again."
SIGNED_OUT = "Sign in again to do that."

MAX_ID = 2**63 - 1


@dataclass(frozen=True, slots=True)
class Actor:
    """Who is acting, and the server the web serves."""

    player: Player
    community_id: int


@dataclass(frozen=True, slots=True)
class Done:
    topics: tuple[str, ...]  # The `league.services.live` topics the action changes.
    result: s.ActionResult | None = None


@dataclass(frozen=True, slots=True)
class Reply:
    """How an action went: what the ack says, and what to refresh before sending it."""

    ok: bool
    error: str | None = None
    result: s.ActionResult | None = None
    topics: tuple[str, ...] = ()


type Run = Callable[[Actor, Any], Done]
type RunAsync = Callable[[int, int, Any], Awaitable[Done]]


@dataclass(frozen=True, slots=True)
class Action:
    name: str
    args: type[BaseModel]
    run: Run | None = None  # On a database thread, all at once.
    # For an action that waits on something other than the database between its steps: it
    # takes the player and server ids and runs its own database steps.
    run_async: RunAsync | None = None


REGISTRY: dict[str, Action] = {}


def _action[A: BaseModel](
    name: str, args: type[A]
) -> Callable[[Callable[[Actor, A], Done]], Callable[[Actor, A], Done]]:
    def register(fn: Callable[[Actor, A], Done]) -> Callable[[Actor, A], Done]:
        REGISTRY[name] = Action(name, args, run=fn)
        return fn

    return register


# --- Arguments --------------------------------------------------------------------------------

# A row id. The page sends it as a string, as every id on the wire is.
PkId = Annotated[
    int,
    Field(ge=1, le=MAX_ID),
    WithJsonSchema({"type": "string", "pattern": "^[1-9][0-9]{0,18}$"}),
]
Index = Annotated[int, Field(ge=0, le=10_000)]


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class NoArgs(_Args):
    pass


class MatchArgs(_Args):
    match_id: PkId


class VoteArgs(MatchArgs):
    candidate_ids: Annotated[list[PkId], Field(min_length=1, max_length=12)]


class PickPlayerArgs(MatchArgs):
    step_index: Index
    player_id: PkId


class CoinflipArgs(MatchArgs):
    choice: s.CoinflipChoice


class ChampionArgs(MatchArgs):
    step_index: Index
    champion_id: PkId


class StepArgs(MatchArgs):
    step_index: Index


class LobbyCodeArgs(MatchArgs):
    code: Annotated[str, Field(min_length=1, max_length=32)]


class DisputeArgs(MatchArgs):
    note: Annotated[str, Field(max_length=500)] = ""


class MapRowArgs(_Args):
    read_id: PkId
    row: Index
    player_id: PkId


class PlayerInMatchArgs(MatchArgs):
    player_id: PkId


class AnswerArgs(MatchArgs):
    agree: bool


class RequestArgs(_Args):
    request_id: PkId


class AnswerRequestArgs(RequestArgs):
    approve: bool


class InviteArgs(RequestArgs):
    player_id: PkId


class AnswerOfferArgs(_Args):
    offer_id: PkId
    accept: bool


class ClaimArgs(MatchArgs):
    side: s.Side


class SwapProposeArgs(MatchArgs):
    give_id: PkId  # One of the asking captain's players.
    take_id: PkId  # One of the other team's.


class SwapAnswerArgs(MatchArgs):
    swap_id: PkId
    accept: bool


class WishArgs(MatchArgs):
    # Most wanted first. The service refuses more than three, or a hero twice, in words: the
    # wider limit here only keeps out nonsense.
    champion_ids: Annotated[list[PkId], Field(max_length=12)]


class ChatArgs(MatchArgs):
    # The service trims it and refuses it, in words, if it's empty or too long once trimmed.
    body: Annotated[str, Field(max_length=4000)]


# --- Scope: only the web's own server ----------------------------------------------------------


def _actor(player_id: int, community_id: int) -> Actor:
    player = Player.objects.filter(pk=player_id, is_active=True).first()
    if player is None:
        raise NotAllowed(SIGNED_OUT)
    return Actor(player, community_id)


def _match_here(who: Actor, match_id: int) -> int:
    if not Match.objects.filter(pk=match_id, community_id=who.community_id).exists():
        raise StaleAction("That match no longer exists.")
    return match_id


def _request_match(who: Actor, request_id: int) -> int:
    match_id = (
        SubRequest.objects.filter(pk=request_id, match__community_id=who.community_id)
        .values_list("match_id", flat=True)
        .first()
    )
    if match_id is None:
        raise StaleAction("That sub request no longer exists.")
    return match_id


def _offer_match(who: Actor, offer_id: int) -> int:
    match_id = (
        SubOffer.objects.filter(pk=offer_id, request__match__community_id=who.community_id)
        .values_list("request__match_id", flat=True)
        .first()
    )
    if match_id is None:
        raise StaleAction("That offer no longer exists.")
    return match_id


def _read_match(who: Actor, read_id: int) -> int:
    match_id = (
        ScoreboardRead.objects.filter(pk=read_id, match__community_id=who.community_id)
        .values_list("match_id", flat=True)
        .first()
    )
    if match_id is None:
        raise StaleAction("That scoreboard read no longer exists.")
    return match_id


def _match_done(match_id: int, result: s.ActionResult | None = None) -> Done:
    return Done((live.match_topic(match_id),), result)


# --- Queue ------------------------------------------------------------------------------------


@_action("queue.join", NoArgs)
def _queue_join(who: Actor, args: NoArgs) -> Done:
    # A cooldown refuses with `penalties.refusal_text`, which comes back through `plain`.
    queue.join(who.community_id, who.player)
    return Done((live.queue_topic(who.community_id),))


@_action("queue.leave", NoArgs)
def _queue_leave(who: Actor, args: NoArgs) -> Done:
    queue.leave(who.community_id, who.player)
    return Done((live.queue_topic(who.community_id),))


# --- Lobby ------------------------------------------------------------------------------------


@_action("lobby.ready", MatchArgs)
def _ready(who: Actor, args: MatchArgs) -> Done:
    lobby.mark_ready(_match_here(who, args.match_id), who.player)
    return _match_done(args.match_id)


@_action("lobby.vote", VoteArgs)
def _vote(who: Actor, args: VoteArgs) -> Done:
    lobby.cast_captain_votes(_match_here(who, args.match_id), who.player, args.candidate_ids)
    return _match_done(args.match_id)


@_action("lobby.checkin", MatchArgs)
def _checkin(who: Actor, args: MatchArgs) -> Done:
    lobby.check_in(_match_here(who, args.match_id), who.player)
    return _match_done(args.match_id)


# --- Drafts -----------------------------------------------------------------------------------


@_action("draft.pick_player", PickPlayerArgs)
def _pick_player(who: Actor, args: PickPlayerArgs) -> Done:
    match_id = _match_here(who, args.match_id)
    draft.pick_player(match_id, who.player, args.step_index, args.player_id, interaction_id=None)
    return _match_done(match_id)


@_action("draft.coinflip", CoinflipArgs)
def _coinflip(who: Actor, args: CoinflipArgs) -> Done:
    draft.choose_coinflip(_match_here(who, args.match_id), who.player, args.choice)
    return _match_done(args.match_id)


@_action("draft.champion", ChampionArgs)
def _champion(who: Actor, args: ChampionArgs) -> Done:
    match_id = _match_here(who, args.match_id)
    draft.choose_champion(
        match_id, who.player, args.step_index, args.champion_id, interaction_id=None
    )
    return _match_done(match_id)


@_action("draft.random_champion", StepArgs)
def _random_champion(who: Actor, args: StepArgs) -> Done:
    match_id = _match_here(who, args.match_id)
    champion_id = draft.choose_random_champion(
        match_id, who.player, args.step_index, interaction_id=None
    )
    return _match_done(match_id, s.RandomChampion(champion_id=str(champion_id)))


@_action("draft.lobby_code", LobbyCodeArgs)
def _lobby_code(who: Actor, args: LobbyCodeArgs) -> Done:
    match_id = _match_here(who, args.match_id)
    draft.check_lobby_host(match_id, who.player)
    draft.submit_lobby_code(match_id, who.player, args.code.strip())
    return _match_done(match_id)


def _api_check(player_id: int, community_id: int, match_id: int) -> str:
    who = _actor(player_id, community_id)
    return draft.check_can_start_api(_match_here(who, match_id), who.player)


def _api_started(player_id: int, community_id: int, match_id: int) -> None:
    draft.mark_api_started(match_id, _actor(player_id, community_id).player)


async def _api_start(player_id: int, community_id: int, args: MatchArgs) -> Done:
    """As the Discord button does: check, ask deadlock-api to start the lobby (off the database
    threads, since it can take a while), then record it."""
    party_id = await web_db(_api_check, player_id, community_id, args.match_id)
    try:
        await asyncio.to_thread(deadlock_api.start_custom_match, party_id)
    except deadlock_api.ApiError as exc:
        hint = "Try again in a moment." if exc.rate_limited else "Start it from the game instead."
        raise InvalidAction(f"The match couldn't be started. {hint}") from exc
    await web_db(_api_started, player_id, community_id, args.match_id)
    return _match_done(args.match_id)


REGISTRY["draft.api_start"] = Action("draft.api_start", MatchArgs, run_async=_api_start)


# --- Swaps ------------------------------------------------------------------------------------


@_action("swap.propose", SwapProposeArgs)
def _swap_propose(who: Actor, args: SwapProposeArgs) -> Done:
    match_id = _match_here(who, args.match_id)
    swap = swaps.propose(match_id, who.player, args.give_id, args.take_id)
    return _match_done(match_id, s.SwapProposed(swap_id=str(swap.pk)))


@_action("swap.answer", SwapAnswerArgs)
def _swap_answer(who: Actor, args: SwapAnswerArgs) -> Done:
    match_id = _match_here(who, args.match_id)
    swaps.answer(match_id, who.player, args.swap_id, args.accept)
    return _match_done(match_id)


# --- Wishes and chat ---------------------------------------------------------------------------


@_action("wish.set", WishArgs)
def _wish_set(who: Actor, args: WishArgs) -> Done:
    match_id = _match_here(who, args.match_id)
    wishes.set_wishes(match_id, who.player, args.champion_ids)
    return _match_done(match_id)


@_action("chat.send", ChatArgs)
def _chat_send(who: Actor, args: ChatArgs) -> Done:
    match_id = _match_here(who, args.match_id)
    chat.send(match_id, who.player, args.body)
    return _match_done(match_id)


# --- Results ----------------------------------------------------------------------------------


@_action("results.confirm", MatchArgs)
def _confirm(who: Actor, args: MatchArgs) -> Done:
    results.confirm(_match_here(who, args.match_id), who.player)
    return _match_done(args.match_id)


@_action("results.dispute", DisputeArgs)
def _dispute(who: Actor, args: DisputeArgs) -> Done:
    results.dispute(_match_here(who, args.match_id), who.player, args.note.strip())
    return _match_done(args.match_id)


@_action("ocr.map_row", MapRowArgs)
def _map_row(who: Actor, args: MapRowArgs) -> Done:
    match_id = _read_match(who, args.read_id)
    ocr.map_row(args.read_id, args.row, args.player_id, who.player, is_staff=False)
    return _match_done(match_id)


@_action("early_leave.report", PlayerInMatchArgs)
def _early_leave_report(who: Actor, args: PlayerInMatchArgs) -> Done:
    early_leave.report(_match_here(who, args.match_id), who.player, args.player_id)
    return _match_done(args.match_id)


@_action("early_leave.answer", AnswerArgs)
def _early_leave_answer(who: Actor, args: AnswerArgs) -> Done:
    early_leave.answer(_match_here(who, args.match_id), who.player, args.agree)
    return _match_done(args.match_id)


# --- Subs -------------------------------------------------------------------------------------


@_action("subs.options", MatchArgs)
def _sub_options(who: Actor, args: MatchArgs) -> Done:
    options = subs.sub_out_options(_match_here(who, args.match_id), who.player)
    result = s.SubOutOptions(
        choices=[
            s.SubOutChoice(
                player_id=str(choice.player_id), name=choice.name, is_self=choice.is_self
            )
            for choice in options.choices
        ],
        game_on=options.game_on,
        dodge=options.dodge,
        strikes=_self_sub_strikes(who, options),
    )
    return Done((), result)  # Only a question: nothing changes.


def _self_sub_strikes(who: Actor, options: subs.SubOutOptions) -> int:
    """What subbing yourself out now costs, as `subs._offence` will count it once filled."""
    kind = PenaltyKind.LEAVER if options.game_on else PenaltyKind.DODGE if options.dodge else None
    if kind is None:
        return 0
    policy = standing.strike_policy(Community.objects.get(pk=who.community_id))
    return policy.points_for(kind)


@_action("subs.request", PlayerInMatchArgs)
def _sub_request(who: Actor, args: PlayerInMatchArgs) -> Done:
    request = subs.request_sub_out(_match_here(who, args.match_id), who.player, args.player_id)
    return _match_done(args.match_id, s.SubRequested(request_id=str(request.pk)))


@_action("subs.answer_request", AnswerRequestArgs)
def _sub_answer_request(who: Actor, args: AnswerRequestArgs) -> Done:
    match_id = _request_match(who, args.request_id)
    subs.answer_sub_out(args.request_id, who.player, args.approve)
    return _match_done(match_id)


@_action("subs.cancel", RequestArgs)
def _sub_cancel(who: Actor, args: RequestArgs) -> Done:
    match_id = _request_match(who, args.request_id)
    subs.cancel_sub(args.request_id, who.player)
    return _match_done(match_id)


@_action("subs.invite", InviteArgs)
def _sub_invite(who: Actor, args: InviteArgs) -> Done:
    match_id = _request_match(who, args.request_id)
    subs.check_can_invite(args.request_id, who.player)
    target = Player.objects.filter(pk=args.player_id).first()
    if target is None:
        raise InvalidAction("That player couldn't be found.")
    subs.invite_sub(args.request_id, who.player, target.discord_user_id, target.display_name)
    return Done((live.match_topic(match_id), live.player_topic(target.pk)))


@_action("subs.offer_queue", RequestArgs)
def _sub_offer_queue(who: Actor, args: RequestArgs) -> Done:
    match_id = _request_match(who, args.request_id)
    subs.offer_to_queue(args.request_id, who.player)
    return _match_done(match_id)


@_action("subs.answer_offer", AnswerOfferArgs)
def _sub_answer_offer(who: Actor, args: AnswerOfferArgs) -> Done:
    match_id = _offer_match(who, args.offer_id)
    subs.answer_offer(args.offer_id, who.player, args.accept)
    return Done((live.match_topic(match_id), live.player_topic(who.player.pk)))


# --- Scrims -----------------------------------------------------------------------------------


@_action("scrims.claim", ClaimArgs)
def _scrim_claim(who: Actor, args: ClaimArgs) -> Done:
    scrims.claim_captain(_match_here(who, args.match_id), who.player, args.side)
    return _match_done(args.match_id)


@_action("scrims.start", MatchArgs)
def _scrim_start(who: Actor, args: MatchArgs) -> Done:
    scrims.start_draft(_match_here(who, args.match_id), who.player)
    return _match_done(args.match_id)


# --- The protocol's view of them ----------------------------------------------------------------


def _field_name(action: str) -> str:
    return action.replace(".", "__")


# Every action's arguments, by action name: the frontend's typed `act` comes from this, through
# the JSON Schema (`manage.py export_ws_schema`). Only ever turned into a schema.
ActionArgs: type[BaseModel] = create_model(  # type: ignore[call-overload]
    "ActionArgs",
    __config__=ConfigDict(populate_by_name=True),
    **{
        _field_name(name): (action.args, Field(alias=name))
        for name, action in sorted(REGISTRY.items())
    },
)


# --- Running them -----------------------------------------------------------------------------


def _parse(name: str, raw: dict[str, Any]) -> tuple[Action, BaseModel] | Reply:
    action = REGISTRY.get(name)
    if action is None:
        logger.debug("Refused the unknown web action %r.", name)
        return Reply(False, BAD_REQUEST)
    try:
        return action, action.args.model_validate(raw)
    except ValidationError as error:
        logger.debug("Refused the web action %s: %s", name, error)
        return Reply(False, BAD_REQUEST)


def _ids(args: BaseModel) -> dict[str, Any]:
    """The ids in an action's arguments, for the log. Free text stays out of it."""
    return {key: value for key, value in args.model_dump().items() if key.endswith("_id")}


def _refused(error: DomainError) -> Reply:
    return Reply(False, plain(error.message) or BAD_REQUEST)


def _failed(name: str, args: BaseModel) -> Reply:
    logger.exception("The web action %s failed (%s).", name, _ids(args))
    return Reply(False, FAILED)


def perform(who: Actor, name: str, raw: dict[str, Any]) -> Reply:
    """Run one action on this thread. The socket runs it on a database thread; tests call it
    directly. An action with its own steps (`run_async`) goes through `dispatch` instead."""
    parsed = _parse(name, raw)
    if isinstance(parsed, Reply):
        return parsed
    action, args = parsed
    if action.run is None:
        raise TypeError(f"{name} runs through dispatch().")
    try:
        done = action.run(who, args)
    except DomainError as error:
        return _refused(error)
    except Exception:
        return _failed(name, args)
    return Reply(True, result=done.result, topics=done.topics)


def _perform_as(player_id: int, community_id: int, name: str, raw: dict[str, Any]) -> Reply:
    try:
        who = _actor(player_id, community_id)
    except DomainError as error:
        return _refused(error)
    return perform(who, name, raw)


async def dispatch(player_id: int, community_id: int, name: str, raw: dict[str, Any]) -> Reply:
    """Run one action for the socket. Never raises for anything the action does."""
    parsed = _parse(name, raw)
    if isinstance(parsed, Reply):
        return parsed
    action, args = parsed
    try:
        if action.run is not None:
            return await web_db(_perform_as, player_id, community_id, name, raw)
        assert action.run_async is not None
        done = await action.run_async(player_id, community_id, args)
    except DomainError as error:
        return _refused(error)
    except Exception:
        return _failed(name, args)
    return Reply(True, result=done.result, topics=done.topics)
