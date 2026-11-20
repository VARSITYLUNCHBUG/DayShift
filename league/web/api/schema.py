"""Every response body the HTTP API (`/api/...`) sends.

`manage.py export_ws_schema` writes these out with the websocket protocol, under `http` (the
`HttpApi` model, one field per body), so the frontend's generated types cover them too. The
socket's rules hold: IDs are strings, players are named by player ID, and times are ISO 8601 in
UTC ending in "Z".

A player's profile is private to them: only `/api/me/` carries ratings history, strikes or
accounts, and only the viewer's own. The ladder names players without addressing them, and
player search carries no stats. A match is the shared record, so its page is the same for every
signed-in viewer.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from league.services.postgame import Postgame
from league.web.live.schema import (
    ByTeam,
    ChampionAction,
    ChampionRef,
    Id,
    MatchKind,
    MatchStatus,
    PlayerRef,
    Side,
    Sides,
    Team,
    UtcTime,
)

type ErrorCode = Literal["signed-out", "not-found", "bad-request", "not-set-up"]
# The league's own awards, MVP and key player. The postgame's six are its own (`Postgame.awards`).
type LeagueAward = Literal["mvp", "key"]
type Outcome = Literal["win", "loss", "void"]
# Why a match has no postgame yet. "later": its deadlock-api data hasn't arrived and may still.
# "no-match-id": nobody gave its Deadlock match ID. "unavailable": the checks gave up, are off,
# or the data couldn't be turned into a postgame.
type PendingReason = Literal["later", "no-match-id", "unavailable"]
type StrikeEntryKind = Literal["offence", "adjustment"]


class _Http(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, json_schema_serialization_defaults_required=True
    )


class ApiError(_Http):
    """Any refusal that isn't a sentence. `not-set-up`: the web's server has no league or no
    open season yet."""

    error: ErrorCode


class Refusal(_Http):
    """The request wasn't taken. A plain sentence for the player, as the Discord bot says it."""

    refusal: str


# --- GET /api/matches/ ------------------------------------------------------------------------


class MatchRow(_Http):
    id: Id
    status: MatchStatus
    kind: MatchKind
    mode_name: str
    draft_name: str  # "Iron Moth": the match's nickname, from its seed.
    captains: ByTeam
    team_names: ByTeam  # "<captain>'s Team".
    sides: Sides  # Set once the coinflip is settled.
    winner: Team | None
    started_at: UtcTime | None  # When the game itself started.
    ended_at: UtcTime | None
    your_team: Team | None  # The viewer's team, when they're on its roster.


class MatchList(_Http):
    matches: list[MatchRow]  # Newest first. With `mine=1`, only the viewer's own.
    next_cursor: str | None  # Send back as `cursor` for the next page. None on the last page.


# --- GET /api/matches/{id}/ -------------------------------------------------------------------


class ResultPlayer(_Http):
    id: Id
    name: str
    avatar_url: str | None
    is_captain: bool
    # The rating (or interim points: `MatchDetail.rating_label`) before and after the match,
    # with any later corrections such as awards. Equal for a match that wasn't rated.
    rating_before: int
    rating_after: int
    delta: int
    award: LeagueAward | None
    hero: ChampionRef | None  # The hero they played, when the draft or the stats say.
    stat_line: str | None  # "Mirage 12/8/13, 38k damage", from the scoreboard or deadlock-api.


class TeamResult(_Http):
    team: Team
    name: str | None  # "<captain>'s Team".
    side: Side | None
    average_rating: float | None  # Before the match, once rated.
    players: list[ResultPlayer]  # Highest rated first.
    picks: list[ChampionRef]  # In draft order.
    bans: list[ChampionRef]


class DraftPick(_Http):
    action: ChampionAction
    team: Team
    champion: ChampionRef


class MatchDetail(_Http):
    """A match's public record. The same for every signed-in viewer."""

    id: Id
    status: MatchStatus
    kind: MatchKind
    mode_name: str
    draft_name: str
    gif_url: str | None
    rating_label: str  # "Rating", or "Points" while the server shows interim points.
    rated: bool  # Ratings (or points) changed: a completed ranked match.
    winner: Team | None
    started_at: UtcTime | None
    ended_at: UtcTime | None
    duration_s: int | None
    teams: list[TeamResult]  # A, then B.
    draft: list[DraftPick]  # Every ban and pick, in draft order.
    win_chance_a: float | None  # The forecast before the match, once rated.
    deadlock_match_id: Id | None
    has_postgame: bool  # `/api/matches/{id}/postgame/` is ready.


# --- GET /api/matches/{id}/postgame/ ----------------------------------------------------------


class YourNight(_Http):
    """The viewer's own part in the match. Only for a player on its roster."""

    team: Team | None
    side: Side | None
    slot: int | None  # Their line in `data.players`, when deadlock-api's data placed them.
    result: Outcome | None  # None while the result is unsettled.
    rating_label: str
    rating_before: int | None  # None for a match that wasn't rated.
    rating_after: int | None
    delta: int | None
    award: LeagueAward | None


class PostgameReady(_Http):
    status: Literal["ready"]
    data: Postgame
    you: YourNight | None


class PostgamePending(_Http):
    status: Literal["pending"]
    reason: PendingReason


# --- POST /api/matches/{id}/report/ -----------------------------------------------------------


class ReportDone(_Http):
    status: MatchStatus  # The match's status after the report.


# --- GET /api/ladder/ -------------------------------------------------------------------------


class LadderRow(_Http):
    """One line of the table. No player ID: profiles are private, so there's nothing to open."""

    rank: int
    name: str
    avatar_url: str | None
    rating: int  # Or interim points: `Ladder.rating_label` says which.
    tier: str | None  # None while the server shows interim points.
    wins: int
    losses: int
    is_you: bool


class Ladder(_Http):
    season: str
    season_id: Id
    rating_label: str
    tiers: list[str]  # Lowest first. Empty while the server shows interim points.
    total: int  # Players on the table.
    rows: list[LadderRow]
    me: LadderRow | None  # The viewer's own row, on this page or not. None if not on the table.
    # Send back as `offset` for the next page of `rows`. None on the last page.
    next_offset: int | None


# --- GET /api/seasons/ ------------------------------------------------------------------------


class SeasonRef(_Http):
    id: Id
    name: str
    is_open: bool  # The season being played now.


class SeasonList(_Http):
    seasons: list[SeasonRef]  # Newest first.


# --- GET /api/me/ -----------------------------------------------------------------------------


class Placement(_Http):
    played: int
    total: int


class StrikeEntry(_Http):
    """An offence that gave strikes, or a staff adjustment. Clean matches aren't listed."""

    at: UtcTime
    kind: StrikeEntryKind
    label: str  # "Dodge", "Missed ready check", "Staff adjustment".
    strikes: int  # Added, or for an adjustment the signed change.
    reason: str
    match_id: Id | None
    waived: bool  # Staff lifted it as a mistake, so it doesn't count.


class Strikes(_Http):
    count: int
    progress: int  # Clean matches played towards removing the next strike.
    games_per_strike: int
    games_to_next: int | None  # Clean matches until one comes off. None with no strikes.
    next_decay_at: UtcTime | None  # Or when time takes one off.
    log: list[StrikeEntry]  # Newest first.


class CaptainStatus(_Http):
    """Whether they can be a captain now, under the mode's rule."""

    eligible: bool
    reason: str  # Why not, such as "2/5 matches" or "barred by staff". Empty when eligible.


class RatingPoint(_Http):
    at: UtcTime | None
    match_id: Id | None  # None for a change with no match, such as a staff adjustment.
    delta: int
    rating_after: int


class RecentMatch(_Http):
    match_id: Id
    draft_name: str
    status: MatchStatus
    ended_at: UtcTime | None
    team: Team | None
    side: Side | None
    result: Outcome | None  # None while the match is unsettled.
    hero: ChampionRef | None  # From the postgame or the scoreboard, when either had it.
    delta: int | None  # None for a match that changed no rating.
    rating_after: int | None
    award: LeagueAward | None
    has_postgame: bool


class HeroGames(_Http):
    hero: ChampionRef
    games: int


class Awards(_Http):
    mvps: int  # This season.
    keys: int


class SteamRow(_Http):
    """One of the viewer's own Steam accounts. `id` is the link's own handle, for unlinking;
    never the Steam ID."""

    id: Id
    name: str
    proven: bool  # Signed in through Steam, so it's theirs.
    verified: bool  # Seen on their team in one of their matches.
    linked_at: UtcTime


class Accounts(_Http):
    discord_name: str
    avatar_url: str | None
    steam: list[SteamRow]  # Oldest link first.


class MyProfile(_Http):
    """The signed-in player's own profile. Nobody else's is ever sent."""

    player: PlayerRef
    season: str
    season_id: Id
    rating_label: str
    rating: int
    tier: str | None  # None while the server shows interim points.
    tiers: list[str]  # Lowest first; empty with interim points.
    rank: int | None  # Their place on the ladder; None if not on it.
    ranked: int  # Players on the ladder.
    games: int
    wins: int
    losses: int
    placement: Placement | None  # None once placed, or with interim points.
    strikes: Strikes  # Now, not per season.
    captain: CaptainStatus
    history: list[RatingPoint]  # This season, oldest first.
    recent: list[RecentMatch]  # Newest first.
    heroes: list[HeroGames]  # Most played first.
    awards: Awards
    accounts: Accounts


# --- POST /api/me/steam/{id}/unlink/ ----------------------------------------------------------


class SteamUnlinked(_Http):
    steam: list[SteamRow]  # The accounts still linked.


# --- GET /api/players/search/ -----------------------------------------------------------------


class SearchPlayer(_Http):
    """Someone to name as a sub. No stats: profiles are private."""

    id: Id
    name: str
    avatar_url: str | None
    in_match: bool  # Playing in a live match: can't be named as a sub.


class PlayerSearch(_Http):
    players: list[SearchPlayer]


# --- POST /api/tools/random-draft/ ------------------------------------------------------------


class DraftSide(_Http):
    bans: list[ChampionRef]
    picks: list[ChampionRef]


class RandomDraft(_Http):
    """Every ban and pick in the mode's order, chosen at random. Nothing is recorded."""

    hk: DraftSide
    am: DraftSide


class Advert(_Http):
    """The landing page's message of the day or advert. Exactly the field its `kind` needs is
    set: `html` (cleaned on the server: insert it as it is), `src` (a file on this site) or
    `youtube_id` (embed it from youtube-nocookie.com)."""

    kind: Literal["image", "html", "video", "youtube"]
    alt: str  # What the image or video shows. Empty for HTML.
    link_url: str | None  # Where pressing it goes.
    html: str | None
    src: str | None
    youtube_id: str | None


class Landing(_Http):
    """The sign-in page's call to action, as staff set it in the admin. When any of it is set it
    takes the whole of the page's hero, beside the sign-in card; with none, the page has its own
    words. Anyone may read it, signed in or not."""

    # The tagline: its headline takes the place of the page's own, in its biggest type. Cleaned
    # HTML: the headline inline (emphasis, code, links, line breaks), the lead in paragraphs.
    headline_html: str | None
    lead_html: str | None
    advert: Advert | None


class HttpApi(_Http):
    """Each endpoint's response body, for the generated types. Never sent itself.
    `/api/session/` is `league.web.auth.views.session_view`'s own, and the share card is a PNG."""

    error: ApiError
    refusal: Refusal
    matches: MatchList
    match: MatchDetail
    postgame: PostgameReady | PostgamePending
    report: ReportDone
    ladder: Ladder
    seasons: SeasonList
    me: MyProfile
    steam_unlinked: SteamUnlinked
    player_search: PlayerSearch
    random_draft: RandomDraft
    landing: Landing
