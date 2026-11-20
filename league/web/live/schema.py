"""Every websocket message, both ways, and every snapshot the server sends.

These models are the protocol. `manage.py export_ws_schema` writes them out as JSON Schema, and
the frontend's TypeScript types are generated from that (`npm run gen`), so a change here is a
change there.

Every ID is a string, since a browser can't hold a 64-bit integer exactly. Players are named by
their player ID, never their Discord ID. Times are ISO 8601 in UTC, ending in "Z".

A snapshot grows by adding a field with a default, so builders that don't know it still work: a
list defaulting to `[]`, or a value defaulting to None. The match's hero wishes and team chat slot
in that way (`MatchSnap`), filled per team by `snapshots.MatchBody.by_team`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, RootModel, WithJsonSchema
from pydantic.json_schema import GenerateJsonSchema, models_json_schema
from pydantic_core import CoreSchema


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


UtcTime = Annotated[
    datetime,
    PlainSerializer(_iso, return_type=str, when_used="json"),
    WithJsonSchema({"type": "string", "format": "date-time"}),
]
type Id = str

# Every value of `league.domain.engine.Status`, scrims' included. A test keeps them in step.
type MatchStatus = Literal[
    "ready_check",
    "captain_phase",
    "captain_checkin",
    "player_draft",
    "coinflip",
    "champion_draft",
    "lobby_code",
    "in_progress",
    "awaiting_confirmation",
    "disputed",
    "completed",
    "voided",
    "captain_claim",
    "ready_to_draft",
    "drafted",
]
type MatchKind = Literal["ranked", "scrim"]
type Team = Literal["A", "B"]
type Side = Literal["hk", "am"]
# Ranked: the winner picks a side (The Hidden King bans and picks first). Scrims: Bebot's order
# and side choices, the winner's then the loser's.
type CoinflipChoice = Literal["first_pick", "last_pick", "hidden_king", "archmother"]
type DraftActionKind = Literal["player_pick", "ban", "pick"]
type ChampionAction = Literal["ban", "pick"]
type SubStatus = Literal["approval", "open"]
type SubReason = Literal["sub_out", "missed_ready", "restart"]
type OfferSource = Literal["invite", "prio", "queue"]
# How an offer ended. "failed": the bot couldn't DM them, so it moved on.
type OfferEndStatus = Literal["accepted", "declined", "expired", "failed", "withdrawn"]
# How a sub request ended: someone took the spot, whoever asked took it back, the other captain
# said no (or didn't answer), or nobody came in time.
type SubDoneStatus = Literal["filled", "cancelled", "rejected", "expired"]
type PenaltyKind = Literal["missed_ready", "dodge", "leaver", "false_report", "manual"]
type ScoreOcr = Literal["off", "shadow", "on"]
type Verdict = Literal["report", "confirm", "dispute"]
# Where the match's Deadlock lobby stands. "making": the bot is asking deadlock-api for one.
# "failed": it couldn't, so the host makes one and enters its code. "ready": the bot's lobby is
# up and a captain can start it. "started": a captain started it. "none": not yet, or a lobby
# entered by hand.
type LobbyState = Literal["none", "making", "failed", "ready", "started"]
# The lobby chat is everyone's, while the teams are made; a team chat is that team's own.
type ChatScope = Literal["lobby", "team"]
type WishRank = Literal[1, 2, 3]
Topic = Annotated[str, Field(pattern=r"^(me|queue|live|match:[1-9][0-9]{0,18})$")]
MatchTopic = Annotated[str, Field(pattern=r"^match:[1-9][0-9]{0,18}$")]


class _Wire(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, json_schema_serialization_defaults_required=True
    )


# --- Shared pieces ----------------------------------------------------------------------------


class PlayerRef(_Wire):
    id: Id
    name: str
    avatar_url: str | None  # None: show initials.


class ByTeam(_Wire):
    A: str | None
    B: str | None


class Sides(_Wire):
    A: Side | None
    B: Side | None


# --- me ---------------------------------------------------------------------------------------


class SteamLink(_Wire):
    """One of the player's own Steam accounts. Only ever sent to that player."""

    account_id: str
    name: str
    proven: bool  # Signed in through Steam, so it's theirs.
    verified: bool  # Seen on their team in one of their matches.


class MePlayer(_Wire):
    id: Id
    name: str
    avatar_url: str | None
    steam: list[SteamLink]  # Oldest link first.


class QueuePlace(_Wire):
    """The player's own place on the priority list. Nobody else's is ever sent."""

    position: int
    total: int
    held_until: UtcTime | None  # Set while their place is held after leaving the queue.


class MeQueue(_Wire):
    in_queue: bool
    position: int | None  # In the queue itself, which everyone can see.
    joined_at: UtcTime | None
    place: QueuePlace | None


class Cooldown(_Wire):
    until: UtcTime
    text: str
    kind: PenaltyKind
    strikes: int
    games_to_next: int | None  # Clean matches until a strike comes off.
    # How long this kind of offence keeps you out, in minutes by rung: rung N is for N strikes
    # already carried, the last for that many or more. Empty when this cooldown didn't come
    # from the ladder (staff set it, or gave it its own length).
    ladder: list[int]
    rung: int | None  # The rung this cooldown came from.


class MeMatch(_Wire):
    id: Id
    status: MatchStatus
    kind: MatchKind
    team: Team | None
    is_captain: bool


class Offer(_Wire):
    """A spot in someone else's match, offered to this player."""

    id: Id
    match_id: Id
    deadline_at: UtcTime
    source: OfferSource
    team: Team | None
    team_name: str | None
    leaving_name: str
    invited_by_name: str | None  # Who named them, for an invite.
    match_status: MatchStatus
    started_at: UtcTime | None  # When the match's game started, if it has.


class OfferEnd(_Wire):
    """The player's most recent offer that has ended, so the page can say how."""

    id: Id
    match_id: Id
    status: OfferEndStatus
    team_name: str | None


class Flags(_Wire):
    auto_captain: bool  # The captain vote is skipped: the bot picks captains.
    api_results: bool  # Results are checked against deadlock-api.
    score_ocr: ScoreOcr
    rating_label: str  # "Rating", or "Points" while the server shows interim points.


class MeSnap(_Wire):
    player: MePlayer
    queue: MeQueue
    cooldown: Cooldown | None
    # Their match in this server: live, or awaiting its result after they reported or were
    # reported for. Subbed out, it's no longer theirs.
    match: MeMatch | None
    # A live scrim they captain. Scrim captains aren't active players, so it's apart from `match`:
    # they can be in both.
    scrim: MeMatch | None
    offers: list[Offer]
    last_offer: OfferEnd | None
    strikes: int  # Their strikes now, with or without a cooldown.
    flags: Flags


# --- queue and live ---------------------------------------------------------------------------


class QueueSnap(_Wire):
    size: int  # Players a lobby needs.
    count: int
    players: list[PlayerRef]  # In queue order.
    mode_name: str
    max_concurrent: int
    live_matches: int
    open: bool  # False while the server runs as many matches as it allows: the queue waits.


class LiveMatch(_Wire):
    id: Id
    status: MatchStatus
    kind: MatchKind
    mode_name: str
    draft_name: str  # "Iron Moth": the match's nickname, from its seed.
    captains: ByTeam
    sides: Sides  # Set once the coinflip is settled.
    started_at: UtcTime | None  # When the game itself started.


class LiveSnap(_Wire):
    matches: list[LiveMatch]  # Newest first.


# --- match:{id} -------------------------------------------------------------------------------


class MatchPlayer(_Wire):
    id: Id
    name: str
    avatar_url: str | None
    rating: int  # Or interim points: `MatchSnap.rating_label` says which.
    team: Team | None
    is_captain: bool
    is_ready: bool
    has_voted: bool  # In the captain vote.
    captain_ok: bool  # Can be voted captain under the mode's rule.
    captain_note: str  # Why not, such as "2/5 matches".
    checked_in: bool  # A captain who pressed I'm here, in the captain check-in.


class ChampionRef(_Wire):
    id: Id
    name: str
    slug: str
    icon_url: str | None  # None: show initials.


class ChampionChoice(_Wire):
    id: Id
    name: str
    slug: str
    icon_url: str | None
    taken: bool  # Banned or picked. It stays on the grid.


class DraftEntry(_Wire):
    action: DraftActionKind
    team: Team | None
    label: str
    auto: bool  # The timer chose.
    random: bool  # The captain pressed Random.
    player_id: Id | None
    champion: ChampionRef | None


class Turn(_Wire):
    team: Team
    captain_id: Id | None
    captain_name: str
    action: DraftActionKind
    position: int  # Within this captain's run of player picks, or among all bans or picks.
    total: int
    next_captain_name: str | None  # Who goes next, when it isn't more of the same.
    next_action: DraftActionKind | None


class ChampionStep(_Wire):
    action: ChampionAction
    side: Side


class PlayerDraftStep(_Wire):
    step_index: int  # The `step_index` a `draft.pick_player` for this pick sends.
    team: Team


class Coinflip(_Wire):
    winner: Team | None
    winner_choice: CoinflipChoice | None
    loser_choice: CoinflipChoice | None
    options: list[CoinflipChoice]  # What the chooser on turn can press.
    chooser_team: Team | None
    chooser_id: Id | None


class Host(_Wire):
    id: Id
    name: str


class ResultResponse(_Wire):
    """One captain's answer: a report, or a confirm or dispute of the other captain's."""

    player_id: Id
    name: str
    verdict: Verdict
    winner: Team | None  # Who they say won. None for a dispute with no report of its own.


class Result(_Wire):
    winner: Team | None
    reported_winner: Team | None
    reported_by_id: Id | None
    reported_by_name: str | None
    deltas: dict[Id, int]  # Rating (or points) change by player ID, once completed.
    responses: list[ResultResponse]  # In order. Dispute notes are for staff, so never sent.
    void_reason: str | None  # Why a cancelled match was cancelled.


class SubOfferRef(_Wire):
    player_id: Id
    name: str
    source: OfferSource
    deadline_at: UtcTime | None


class SubEntry(_Wire):
    id: Id
    status: SubStatus
    reason: SubReason
    leaving_id: Id | None
    leaving_name: str
    team: Team | None
    requested_by_id: Id | None  # None for a spot the bot opened.
    requested_by_name: str | None
    is_self: bool
    deadline_at: UtcTime  # Approval deadline, or when the match is cancelled if unfilled.
    name_until: UtcTime | None  # Until then, whoever opened it can name a sub.
    offer: SubOfferRef | None


class SubDone(_Wire):
    """A sub request that has ended."""

    id: Id
    status: SubDoneStatus
    reason: SubReason
    leaving_id: Id
    leaving_name: str
    team: Team | None
    joined_id: Id | None  # Who took the spot, once filled.
    joined_name: str | None


class SwapOffer(_Wire):
    """A captain's offer of one of their players for one of the other team's."""

    id: Id
    requested_by_id: Id | None
    requested_by_name: str
    give_id: Id | None  # From the asking captain's team.
    give_name: str
    take_id: Id | None  # From the other team.
    take_name: str
    deadline_at: UtcTime


class Swap(_Wire):
    open: bool  # Captains can offer a swap now (from the coinflip until the game starts).
    pending: SwapOffer | None  # Waiting for the other captain. One at a time.


class SwapChoice(_Wire):
    player_id: Id
    name: str


class EarlyLeaveClaim(_Wire):
    leaver_id: Id | None
    leaver_name: str
    by_id: Id | None
    by_name: str
    deadline_at: UtcTime  # After this the other captain's silence sends it to staff.


class EarlyLeave(_Wire):
    open: bool  # A captain can report one now.
    minutes: int  # A leave within this many minutes voids the match.
    pending: EarlyLeaveClaim | None


class Lobby(_Wire):
    state: LobbyState
    api_lobby: bool  # deadlock-api made the lobby, and its bot hosts it.
    api_started: bool
    api_leaves_at: UtcTime | None  # When the bot leaves its lobby.


class ScoreboardRow(_Wire):
    row: int  # What `ocr.map_row` sends back.
    name: str  # As the scoreboard shows it: an in-game name, not a Discord one.
    team: Team
    hero: ChampionRef | None
    hero_name: str  # As read, for a hero the league doesn't know.


class ScoreboardPlayer(_Wire):
    id: Id
    name: str
    team: Team


class Scoreboard(_Wire):
    """Names on the latest scoreboard read that nobody has matched to a player yet. Only ever
    sent to the match's captains, who can match them."""

    read_id: Id
    rows: list[ScoreboardRow]
    players: list[ScoreboardPlayer]  # Not matched yet. A row takes a player from its own team.


class Wish(_Wire):
    """A hero one of the viewer's team (or the viewer) wants to play."""

    player_id: Id
    champion_id: Id
    rank: WishRank  # 1: most wanted.


class ChatLine(_Wire):
    """A player's message."""

    kind: Literal["message"]
    id: Id
    player_id: Id
    name: str
    team: Team | None  # The sender's team, for colouring the lobby chat.
    body: str  # Plain text: render it as text, never as HTML.
    at: UtcTime


class SystemLine(_Wire):
    """Something that happened, shown between the messages, such as "Rook picked Mothball"."""

    kind: Literal["system"]
    id: str  # Unique within the chat, and never a message's.
    body: str  # Plain text.
    at: UtcTime


class ChatView(_Wire):
    """The one chat the viewer can see now."""

    scope: ChatScope
    open: bool  # False: read-only, and `closed_reason` says why.
    closed_reason: str | None
    # Oldest first, the last 100 of each: messages and system lines, in time order.
    messages: list[Annotated[ChatLine | SystemLine, Field(discriminator="kind")]]


class Viewer(_Wire):
    """What the page needs to know about whoever is looking."""

    is_player: bool
    team: Team | None
    is_captain: bool
    is_acting: bool  # The match waits on them now.
    has_voted: bool
    votes: list[Id]  # Who they voted captain. Only their own, and only during the vote.
    checked_in: bool  # A captain who has pressed I'm here.
    can_request_sub: bool
    # A captain, while swaps are open and none is waiting: whom they could offer, and whom they
    # could ask for. Empty for everyone else.
    swap_give: list[SwapChoice]
    swap_take: list[SwapChoice]
    can_wish: bool = False  # `wish.set` is allowed now.


class MatchSnap(_Wire):
    id: Id
    status: MatchStatus
    kind: MatchKind
    mode_name: str
    rating_label: str  # What `MatchPlayer.rating` and the deltas count: "Rating" or "Points".
    # Who a captain gets when a player pick runs out of time: the mode's rule.
    player_timeout: Literal["highest_rating", "random"] = "highest_rating"
    deadline_at: UtcTime | None
    closes_at: UtcTime | None  # When the match channel closes, once it has ended.
    started_at: UtcTime | None  # When the game itself started.
    players: list[MatchPlayer]
    captains: ByTeam
    team_names: ByTeam
    sides: Sides
    draft: list[DraftEntry]
    turn: Turn | None
    step_index: int  # The draft step on turn: what a pick, ban or random sends.
    player_draft_order: list[PlayerDraftStep]  # Every player pick, once the captains are set.
    champion_steps: list[ChampionStep]
    champion_step: int | None  # Index into champion_steps while the hero draft runs.
    champions: list[ChampionChoice]
    coinflip: Coinflip | None
    host: Host | None
    lobby_code: str | None  # Only ever sent to the match's own players.
    lobby: Lobby
    swap: Swap
    result: Result
    subs: list[SubEntry]
    subs_done: list[SubDone]  # Oldest first.
    on_hold: bool
    hold_until: UtcTime | None
    early_leave: EarlyLeave
    win_chance_a: float | None
    captain_min_games: int
    votes_per_player: int  # Captain votes each player may cast.
    draft_name: str
    gif_url: str | None
    restarted_from: Id | None
    scoreboard: Scoreboard | None  # Captains only, while names are unmatched.
    viewer: Viewer
    # The viewer's own team's hero wishes, by player then rank. Empty for anyone else.
    wishes: list[Wish] = Field(default_factory=list)
    # The chat the viewer can see now: none for spectators, or once the match is over.
    chat: ChatView | None = None


# --- Client to server -------------------------------------------------------------------------


class Subscribe(_Wire):
    t: Literal["sub"]
    topics: list[Topic]


class Unsubscribe(_Wire):
    t: Literal["unsub"]
    topics: list[Topic]


class Ping(_Wire):
    t: Literal["ping"]


class Act(_Wire):
    """An action (`league.web.live.actions`): `name` is one of `ActionName`, and `args` that
    action's arguments, as `ActionArgs` lists them. The ack carries the same `id`."""

    t: Literal["act"]
    id: Annotated[str, Field(min_length=1, max_length=64)]
    name: Annotated[str, Field(min_length=1, max_length=64)]
    args: dict[str, Any] = Field(default_factory=dict)


class ClientMessage(
    RootModel[Annotated[Subscribe | Unsubscribe | Ping | Act, Field(discriminator="t")]]
):
    pass


# --- Server to client -------------------------------------------------------------------------


class Hello(_Wire):
    t: Literal["hello"]
    server_time: UtcTime
    player_id: Id


class MeSnapMessage(_Wire):
    t: Literal["snap"]
    topic: Literal["me"]
    rev: int
    data: MeSnap


class QueueSnapMessage(_Wire):
    t: Literal["snap"]
    topic: Literal["queue"]
    rev: int
    data: QueueSnap


class LiveSnapMessage(_Wire):
    t: Literal["snap"]
    topic: Literal["live"]
    rev: int
    data: LiveSnap


class MatchSnapMessage(_Wire):
    t: Literal["snap"]
    topic: MatchTopic
    rev: int  # The match's version: a lower one than last applied is stale.
    data: MatchSnap


class Gone(_Wire):
    t: Literal["gone"]
    topic: str
    reason: Literal["not_found"]


class Pong(_Wire):
    t: Literal["pong"]
    server_time: UtcTime


class RandomChampion(_Wire):
    """`draft.random_champion`: the hero it took."""

    champion_id: Id


class SubRequested(_Wire):
    """`subs.request`: the request it opened."""

    request_id: Id


class SubOutChoice(_Wire):
    player_id: Id
    name: str
    is_self: bool


class SubOutOptions(_Wire):
    """`subs.options`: who this player may ask to sub out, and what it would cost them."""

    choices: list[SubOutChoice]
    game_on: bool  # Leaving now gives a queue cooldown.
    dodge: bool  # Taking yourself out now counts as a dodge.
    strikes: int  # What taking yourself out now adds.


class SwapProposed(_Wire):
    """`swap.propose`: the offer it made."""

    swap_id: Id


type ActionResult = RandomChampion | SubRequested | SubOutOptions | SwapProposed


class Ack(_Wire):
    t: Literal["ack"]
    id: str
    ok: bool
    error: str | None = None  # A plain sentence for the player, when not ok.
    result: ActionResult | None = None  # Only from the actions that return something.


class ServerMessage(
    RootModel[
        Hello
        | MeSnapMessage
        | QueueSnapMessage
        | LiveSnapMessage
        | MatchSnapMessage
        | Gone
        | Pong
        | Ack
    ]
):
    pass


class _Generator(GenerateJsonSchema):
    """No per-field titles: the TypeScript generator would turn each into a type of its own."""

    def field_title_should_be_set(self, schema: CoreSchema) -> bool:
        return False


def protocol_schema(
    http: type[BaseModel] | None = None, actions: type[BaseModel] | None = None
) -> dict[str, Any]:
    """One JSON Schema document for the whole protocol, with every model under `$defs` by name.

    `http`, a model whose fields are the HTTP API's response bodies, adds those under `http`.
    `actions`, a model with a field per action name holding its arguments, adds them under
    `actions` (`league.web.live.actions.ActionArgs`).
    """
    models: list[tuple[type[BaseModel], Literal["validation", "serialization"]]] = [
        (ClientMessage, "validation"),
        (ServerMessage, "serialization"),
    ]
    properties = {
        "client": {"$ref": "#/$defs/ClientMessage"},
        "server": {"$ref": "#/$defs/ServerMessage"},
    }
    if actions is not None:
        models.append((actions, "validation"))
        properties["actions"] = {"$ref": f"#/$defs/{actions.__name__}"}
    if http is not None:
        models.append((http, "serialization"))
        properties["http"] = {"$ref": f"#/$defs/{http.__name__}"}
    _, top = models_json_schema(models, ref_template="#/$defs/{model}", schema_generator=_Generator)
    defs = top["$defs"]
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "LiveProtocol",
        "description": "Messages on the player web UI's websocket, /ws/, and the HTTP API's "
        "responses, /api/.",
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
        "$defs": {name: defs[name] for name in sorted(defs)},
    }
