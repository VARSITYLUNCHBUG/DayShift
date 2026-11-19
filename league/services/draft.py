"""The player draft, champion draft and lobby code. One step per plan entry, one row per step."""

from __future__ import annotations

import logging
import re

from django.db import IntegrityError, transaction

from league.domain import copy
from league.domain.draft_plan import PlanStep, build_plan, player_draft_length, team_for_role
from league.domain.engine import (
    DraftablePlayer,
    Status,
    apply_coinflip,
    apply_ranked_coinflip,
    auto_champion,
    auto_coinflip_choice,
    auto_player_pick,
    coin_flip_team,
    coinflip_options,
    seeded_rng,
)
from league.domain.errors import InvalidAction, NotAllowed, StaleAction
from league.domain.mode_schema import DraftMode
from league.models import Champion, DraftAction, Match, Player
from league.models.matches import MatchKind, Source
from league.services.common import (
    add_effect,
    clear_notices,
    now,
    render_board,
    seconds_from_now,
    transition,
)

logger = logging.getLogger(__name__)

LOBBY_CODE_PATTERN = re.compile(r"^[A-Za-z0-9-]{3,32}$")


def _current_step(match: Match, mode: DraftMode, step_index: int | None) -> PlanStep:
    plan = build_plan(mode)
    if step_index is not None and step_index != match.step_index:
        raise StaleAction(copy.STEP_TAKEN)
    if match.step_index >= len(plan):
        raise StaleAction("The draft has finished.")
    return plan[match.step_index]


def _acting_team(match: Match, step: PlanStep) -> str:
    first = match.player_first_pick if step.action == "player_pick" else match.champion_first_pick
    return team_for_role(step.role, first)


def _record(
    match: Match,
    step: PlanStep,
    team: str,
    *,
    actor: Player | None,
    source: str,
    target_player_id: int | None = None,
    target_champion_id: int | None = None,
    interaction_id: int | None = None,
    random_choice: bool = False,
) -> None:
    try:
        with transaction.atomic():
            DraftAction.objects.create(
                match=match,
                step_index=step.index,
                action=step.action,
                team=team,
                actor=actor,
                target_player_id=target_player_id,
                target_champion_id=target_champion_id,
                source=source,
                random_choice=random_choice,
                interaction_id=interaction_id,
                created_at=now(),
            )
    except IntegrityError as exc:
        raise StaleAction(copy.STEP_TAKEN) from exc


def _undrafted(match: Match) -> list[DraftablePlayer]:
    players = []
    for participant in match.participants.active().filter(team=""):
        strength = match.season.strength_of(participant.player_id)
        players.append(DraftablePlayer(participant.player_id, strength))
    return players


def _assign_player(match: Match, step: PlanStep, team: str, player_id: int) -> None:
    participant = match.participants.active().filter(player_id=player_id, team="").first()
    if participant is None:
        raise InvalidAction(copy.PLAYER_TAKEN)
    participant.team = team
    participant.draft_pick_number = step.index + 1
    participant.save(update_fields=["team", "draft_pick_number"])


def _require_acting_captain(match: Match, step: PlanStep, team: str, player: Player) -> None:
    if match.captain_of(team).player_id != player.pk:
        raise NotAllowed(copy.not_your_turn(step.action))


# --- Player draft ----------------------------------------------------------------------------


@transaction.atomic
def pick_player(
    match_id: int,
    captain: Player,
    step_index: int,
    target_player_id: int,
    interaction_id: int | None = None,
) -> None:
    match = Match.objects.lock(match_id)
    if match.status != Status.PLAYER_DRAFT:
        raise StaleAction("The player draft has finished.")
    match.require_not_on_hold()
    mode = match.mode
    step = _current_step(match, mode, step_index)
    team = _acting_team(match, step)
    _require_acting_captain(match, step, team, captain)
    _assign_player(match, step, team, target_player_id)
    _record(
        match,
        step,
        team,
        actor=captain,
        source=Source.USER,
        target_player_id=target_player_id,
        interaction_id=interaction_id,
    )
    _advance_player_draft(match, mode)


def _advance_player_draft(match: Match, mode: DraftMode) -> None:
    match.step_index += 1
    if match.step_index >= player_draft_length(mode):
        begin_coinflip(match, mode)
        return
    remaining = _undrafted(match)
    if len(remaining) == 1:
        # Only one player left, so there is nothing to choose.
        step = build_plan(mode)[match.step_index]
        team = _acting_team(match, step)
        _assign_player(match, step, team, remaining[0].player_id)
        _record(
            match,
            step,
            team,
            actor=None,
            source=Source.SYSTEM,
            target_player_id=remaining[0].player_id,
        )
        _advance_player_draft(match, mode)
        return
    match.deadline_at = seconds_from_now(mode.player_draft.seconds)
    match.bump("step_index", "deadline_at")
    render_board(match)


def on_player_draft_timeout(match: Match) -> None:
    mode = match.mode
    step = _current_step(match, mode, None)
    team = _acting_team(match, step)
    target = auto_player_pick(
        _undrafted(match), mode.player_draft.on_timeout, match.rng_seed, step.index
    )
    _assign_player(match, step, team, target)
    _record(match, step, team, actor=None, source=Source.TIMEOUT, target_player_id=target)
    _advance_player_draft(match, mode)


# --- Champion draft --------------------------------------------------------------------------


# --- Captain coinflip ------------------------------------------------------------------------


def begin_coinflip(match: Match, mode: DraftMode) -> None:
    """The player draft is over: make team voice channels and flip a coin between the captains.
    The winner chooses a side. The Hidden King always bans and picks first."""
    match.coinflip_winner = coin_flip_team(match.rng_seed, "coinflip")
    match.coinflip_winner_choice = ""
    match.coinflip_loser_choice = ""
    transition(
        match,
        Status.COINFLIP,
        source=Source.SYSTEM,
        deadline_at=seconds_from_now(mode.champion_draft.coinflip_seconds),
    )
    match.save_transition(
        "step_index", "coinflip_winner", "coinflip_winner_choice", "coinflip_loser_choice"
    )
    add_effect(
        match.community, "create_team_voice", match=match, dedupe_key=f"team_voice:{match.pk}"
    )
    winner = match.captain_of(match.coinflip_winner).player
    add_effect(
        match.community,
        "ping",
        {
            "user_ids": [winner.discord_user_id],
            "text": "teams are set and you won the coinflip! Choose your side on the board. "
            "The Hidden King bans and picks first.",
        },
        match=match,
    )
    render_board(match)


def coinflip_turn(match: Match) -> tuple[str, str]:
    """(team choosing now, "winner" or "loser")."""
    if not match.coinflip_winner_choice:
        return match.coinflip_winner, "winner"
    return ("B" if match.coinflip_winner == "A" else "A"), "loser"


@transaction.atomic
def choose_coinflip(match_id: int, captain: Player, choice: str) -> None:
    match = Match.objects.lock(match_id)
    if match.status != Status.COINFLIP:
        raise StaleAction("The coinflip choices are already made.")
    match.require_not_on_hold()
    team, who = coinflip_turn(match)
    if match.captain_of(team).player_id != captain.pk:
        raise NotAllowed(copy.coinflip_only(who))
    ranked = match.kind != MatchKind.SCRIM
    if choice not in coinflip_options(match.coinflip_winner_choice, ranked=ranked):
        raise InvalidAction("That choice isn't available.")
    _record_coinflip(match, choice, source=Source.USER, actor=captain)


def on_coinflip_timeout(match: Match) -> None:
    """Whoever's turn it is gets a random choice, as a timed-out ban or pick does."""
    ranked = match.kind != MatchKind.SCRIM
    choice = auto_coinflip_choice(match.rng_seed, match.coinflip_winner_choice, ranked=ranked)
    _record_coinflip(match, choice, source=Source.TIMEOUT, actor=None)


def _record_coinflip(match: Match, choice: str, *, source: str, actor: Player | None) -> None:
    mode = match.mode
    if match.kind != MatchKind.SCRIM:
        # Ranked: the winner's side sets the sides, and the Hidden King bans and picks first.
        match.coinflip_winner_choice = choice
        match.hidden_king_team, match.champion_first_pick = apply_ranked_coinflip(
            match.coinflip_winner, choice
        )
        begin_champion_draft(match, mode, source=source, actor=actor)
        return
    if not match.coinflip_winner_choice:
        # As in Bebot: no turn timer, only the scrim's idle one.
        match.coinflip_winner_choice = choice
        match.bump("coinflip_winner_choice")
        render_board(match)
        return
    match.coinflip_loser_choice = choice
    match.hidden_king_team, match.champion_first_pick = apply_coinflip(
        match.coinflip_winner, match.coinflip_winner_choice, choice
    )
    # Bebot's "Ready to start the draft!": a captain presses Start Draft.
    from league.services.scrims import IDLE_SECONDS

    transition(
        match,
        Status.READY_TO_DRAFT,
        source=source,
        actor=actor,
        deadline_at=seconds_from_now(IDLE_SECONDS),
    )
    match.save_transition("champion_first_pick", "hidden_king_team", "coinflip_loser_choice")
    render_board(match)


def begin_champion_draft(
    match: Match, mode: DraftMode, *, source: str, actor: Player | None = None
) -> None:
    """The coinflip has set the sides and which team bans and picks first."""
    step = build_plan(mode)[match.step_index]
    transition(
        match,
        Status.CHAMPION_DRAFT,
        source=source,
        actor=actor,
        deadline_at=seconds_from_now(step.seconds),
    )
    match.save_transition(
        "champion_first_pick",
        "hidden_king_team",
        "coinflip_winner_choice",
        "coinflip_loser_choice",
        "step_index",
    )
    if match.kind == MatchKind.RANKED:  # A scrim's channel is public: no notices there.
        first = match.captain_of(match.champion_first_pick).player
        add_effect(
            match.community,
            "ping",
            {
                "user_ids": [first.discord_user_id],
                "text": "you ban first.",
            },
            match=match,
        )
    render_board(match)


def _used_champions(match: Match) -> set[int]:
    return set(
        match.draft_actions.filter(target_champion__isnull=False).values_list(
            "target_champion_id", flat=True
        )
    )


def available_champions(match: Match) -> list[int]:
    used = _used_champions(match)
    return [champion for champion in match.champion_pool if champion not in used]


@transaction.atomic
def choose_champion(
    match_id: int,
    captain: Player,
    step_index: int,
    champion_id: int,
    interaction_id: int | None = None,
) -> None:
    match = Match.objects.lock(match_id)
    if match.status != Status.CHAMPION_DRAFT:
        raise StaleAction("The champion draft has finished.")
    match.require_not_on_hold()
    mode = match.mode
    step = _current_step(match, mode, step_index)
    team = _acting_team(match, step)
    _require_acting_captain(match, step, team, captain)
    if champion_id not in available_champions(match):
        name = Champion.objects.filter(pk=champion_id).values_list("name", flat=True).first()
        raise InvalidAction(copy.hero_taken(name) if name else "That hero isn't available.")
    _record(
        match,
        step,
        team,
        actor=captain,
        source=Source.USER,
        target_champion_id=champion_id,
        interaction_id=interaction_id,
    )
    _advance_champion_draft(match, mode)


@transaction.atomic
def choose_random_champion(
    match_id: int,
    captain: Player,
    step_index: int,
    interaction_id: int | None = None,
) -> int:
    """The Random button: the acting captain takes a random available champion. Returns it."""
    match = Match.objects.lock(match_id)
    if match.status != Status.CHAMPION_DRAFT:
        raise StaleAction("The champion draft has finished.")
    match.require_not_on_hold()
    mode = match.mode
    step = _current_step(match, mode, step_index)
    team = _acting_team(match, step)
    _require_acting_captain(match, step, team, captain)
    champion = auto_champion(available_champions(match), match.rng_seed, step.index)
    _record(
        match,
        step,
        team,
        actor=captain,
        source=Source.USER,
        target_champion_id=champion,
        interaction_id=interaction_id,
        random_choice=True,
    )
    _advance_champion_draft(match, mode)
    return champion


def on_champion_draft_timeout(match: Match) -> None:
    mode = match.mode
    step = _current_step(match, mode, None)
    team = _acting_team(match, step)
    champion = auto_champion(available_champions(match), match.rng_seed, step.index)
    _record(match, step, team, actor=None, source=Source.TIMEOUT, target_champion_id=champion)
    _advance_champion_draft(match, mode)


def _advance_champion_draft(match: Match, mode: DraftMode) -> None:
    plan = build_plan(mode)
    match.step_index += 1
    if match.step_index >= len(plan):
        if match.kind == MatchKind.SCRIM:
            from league.services.scrims import finish

            finish(match)  # GLHF: a scrim ends at the draft.
            return
        begin_lobby_code(match, mode)
        return
    match.deadline_at = seconds_from_now(plan[match.step_index].seconds)
    match.bump("step_index", "deadline_at")
    render_board(match)


# --- Lobby code ------------------------------------------------------------------------------


def begin_lobby_code(match: Match, mode: DraftMode) -> None:
    team = seeded_rng(match.rng_seed, "lobby-host").choice(["A", "B"])
    host = match.captain_of(team)
    match.lobby_code_host = host.player
    match.lobby_code_attempts = 1
    transition(
        match,
        Status.LOBBY_CODE,
        source=Source.SYSTEM,
        deadline_at=seconds_from_now(mode.lobby_code.seconds),
    )
    match.save_transition("lobby_code_host", "lobby_code_attempts", "step_index")
    # deadlock-api's bot always makes the lobby. Only if that fails is the host asked for a code.
    add_effect(
        match.community,
        "create_api_lobby",
        match=match,
        dedupe_key=f"create_api_lobby:{match.pk}",
    )
    render_board(match)


def _ping_host(match: Match, host: Player, prefix: str = "") -> None:
    add_effect(
        match.community,
        "ping",
        {
            "user_ids": [host.discord_user_id],
            "text": f"{prefix}create the custom lobby, then press Enter lobby code on the board.",
        },
        match=match,
    )


# API lobbies: deadlock-api's bot hosts, and leaves this long after creating the lobby.
API_LOBBY_MINUTES = 15


@transaction.atomic
def accept_api_lobby(match_id: int, party_id: str, party_code: str) -> bool:
    """deadlock-api made the lobby: post its code and start the game. False if a captain got
    there first, or the match moved on."""
    match = Match.objects.lock(match_id)
    if match.status != Status.LOBBY_CODE or match.held_seconds is not None:
        return False
    if match.api_lobby_failed:
        return False  # Too late: the host has been asked to make one, and theirs is the lobby.
    match.api_party_id = party_id[:32]
    match.api_lobby_created_at = now()
    _start_game(match, party_code, source=Source.SYSTEM, actor=None)
    return True


@transaction.atomic
def api_lobby_failed(match_id: int, reason: str) -> None:
    """Lobby creation didn't work: the host makes one by hand."""
    match = Match.objects.lock(match_id)
    if match.status != Status.LOBBY_CODE or match.api_lobby_failed:
        return
    logger.warning("API lobby failed", extra={"match": match.pk, "reason": reason[:200]})
    _fall_back_to_code(match)


def _fall_back_to_code(match: Match) -> None:
    """The host now needs a code, and gets the full time to make the lobby and enter it."""
    seconds = match.mode.lobby_code.seconds
    match.api_lobby_failed = True
    if match.held_seconds is not None:  # Paused for a sub: the time waits with the match.
        match.held_seconds = seconds
        match.bump("api_lobby_failed", "held_seconds")
    else:
        match.deadline_at = seconds_from_now(seconds)
        match.bump("api_lobby_failed", "deadline_at")
    if match.lobby_code_host is not None:
        _ping_host(match, match.lobby_code_host, "the bot couldn't make the lobby, so please ")
    render_board(match)


def check_can_start_api(match_id: int, player: Player) -> str:
    """The lobby's party ID, if this captain may start the API lobby now."""
    match = Match.objects.filter(pk=match_id).first()
    if match is None or match.status != Status.IN_PROGRESS or not match.api_party_id:
        raise StaleAction("There's no bot lobby to start.")
    if match.api_started_at is not None:
        raise StaleAction("The match has already started.")
    if not match.participants.filter(player=player, is_captain=True, is_active=True).exists():
        raise NotAllowed("Only a captain can start the match.")
    return match.api_party_id


@transaction.atomic
def mark_api_started(match_id: int, player: Player) -> None:
    match = Match.objects.lock(match_id)
    if match.api_started_at is not None:
        return
    match.api_started_at = now()
    match.bump("api_started_at")
    add_effect(
        match.community,
        "fetch_api_match_id",
        {"attempt": 1},
        match=match,
        dedupe_key=f"fetch_api_match_id:{match.pk}:1",
        run_after=seconds_from_now(60),
    )
    add_effect(
        match.community,
        "ping_lobby",
        {"text": f"**{player.display_name}** started the match. GLHF!"},
        match=match,
    )
    render_board(match)


MATCH_ID_RETRY_SECONDS = (60, 120, 300, 600, 900)


@transaction.atomic
def record_api_match_id(match_id: int, deadlock_match_id: int | None, attempt: int) -> None:
    """The Deadlock match ID of a started API lobby, or another try later."""
    from league.services import api_results

    match = Match.objects.lock(match_id)
    if deadlock_match_id is not None:
        api_results.set_deadlock_match_id(match, deadlock_match_id)
        return
    if attempt >= len(MATCH_ID_RETRY_SECONDS):
        return
    add_effect(
        match.community,
        "fetch_api_match_id",
        {"attempt": attempt + 1},
        match=match,
        dedupe_key=f"fetch_api_match_id:{match.pk}:{attempt + 1}",
        run_after=seconds_from_now(MATCH_ID_RETRY_SECONDS[attempt]),
    )


def on_lobby_code_timeout(match: Match) -> None:
    from league.services.lobby import void_live  # Avoids a cycle: lobby calls into the draft flow.

    mode = match.mode
    if not match.api_lobby_failed:
        # deadlock-api never answered in time: treat it as a failure, and ask the host.
        logger.warning("API lobby timed out", extra={"match": match.pk})
        _fall_back_to_code(match)
        return
    if match.lobby_code_attempts >= 2:
        void_live(match, source=Source.TIMEOUT, reason="No lobby code was provided")
        return
    current_team = match.participants.get(player=match.lobby_code_host).team
    other = match.captain_of("B" if current_team == "A" else "A")
    match.lobby_code_host = other.player
    match.lobby_code_attempts = 2
    match.deadline_at = seconds_from_now(mode.lobby_code.seconds)
    match.bump("lobby_code_host", "lobby_code_attempts", "deadline_at")
    clear_notices(match)  # The first host's prompt no longer applies.
    _ping_host(match, other.player)
    render_board(match)


def check_lobby_host(match_id: int, player: Player) -> None:
    """Fast check before opening the modal. The submission checks again under the lock."""
    match = Match.objects.filter(pk=match_id).first()
    if match is None or match.status != Status.LOBBY_CODE:
        raise StaleAction("The lobby code step has finished.")
    match.require_not_on_hold()
    _require_code_wanted(match, player)


def _require_code_wanted(match: Match, player: Player) -> None:
    if not match.api_lobby_failed:
        raise StaleAction(API_LOBBY_PENDING)
    if match.lobby_code_host_id != player.pk:
        raise NotAllowed("Only the chosen host can enter the lobby code.")


API_LOBBY_PENDING = "The bot is creating the lobby. If it can't, the host is asked for a code."


@transaction.atomic
def submit_lobby_code(match_id: int, player: Player, code: str) -> None:
    match = Match.objects.lock(match_id)
    if match.status != Status.LOBBY_CODE:
        raise StaleAction("The lobby code step has finished.")
    match.require_not_on_hold()
    _require_code_wanted(match, player)
    cleaned = code.strip()
    if not LOBBY_CODE_PATTERN.match(cleaned):
        raise InvalidAction("That doesn't look like a lobby code: use letters, numbers or dashes.")
    _start_game(match, cleaned, source=Source.USER, actor=player)


def _start_game(match: Match, code: str, *, source: str, actor: Player | None) -> None:
    """The lobby exists: post its code and start the result clock."""
    mode = match.mode
    match.lobby_code = code
    match.started_at = now()
    transition(
        match,
        Status.IN_PROGRESS,
        source=source,
        actor=actor,
        deadline_at=seconds_from_now(mode.results.staff_escalation_minutes * 60),
    )
    match.save_transition("lobby_code", "started_at", "api_party_id", "api_lobby_created_at")
    add_effect(match.community, "announce_lobby_code", match=match)
    add_effect(
        match.community,
        "report_reminder",
        match=match,
        dedupe_key=f"reminder:{match.pk}",
        run_after=seconds_from_now(mode.results.reminder_minutes * 60),
    )
    render_board(match)
