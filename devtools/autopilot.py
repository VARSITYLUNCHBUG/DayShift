"""Playing a match as its players: one action (`act`), or whole phases (`advance`).

Each action is a `Move`: who does what. What to choose comes from the match's script, then the
players' champion picks, then a default (highest skill, or a random champion seeded by the match).
A move is made either through `league.services` or by pressing the real component in the Discord
simulator as that player, so the bot's own handlers run (see README, `via`).
"""

from __future__ import annotations

import hashlib
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from django.utils import timezone

from devtools import control, lookup, sim_client, timers
from devtools.control import LOBBY_CODE, script_of
from devtools.errors import BadRequest, BotOffline, BotTimeout, Conflict, SimError
from devtools.models import DevProfile
from league.domain.draft_plan import build_plan, player_draft_length, team_for_role
from league.domain.engine import HIDDEN_KING, LIVE, TERMINAL, Status
from league.models import (
    CaptainVote,
    Community,
    Match,
    MatchParticipant,
    MatchResource,
    Player,
    PlayerRating,
    PlayerSwap,
    PrioEntry,
    QueueEntry,
    ResultSubmission,
    SubOffer,
    SubRequest,
)
from league.models.matches import MatchKind, ResourceKind
from league.models.subs import UNRESOLVED, OfferStatus, SubStatus
from league.services import draft, lobby, results, standing, subs, swaps
from league.services.results import ImageRef

# The main path of a ranked match, in order. `advance` can stop at any of these.
ORDER = (
    Status.READY_CHECK,
    Status.CAPTAIN_PHASE,
    Status.CAPTAIN_CHECKIN,
    Status.PLAYER_DRAFT,
    Status.COINFLIP,
    Status.CHAMPION_DRAFT,
    Status.LOBBY_CODE,
    Status.IN_PROGRESS,
    Status.AWAITING_CONFIRMATION,
    Status.COMPLETED,
)
SERVICE = "service"
DISCORD = "discord"
# How long the bot gets to post a component, and to act on a press.
BOT_WAIT_SECONDS = 10.0
POLL_SECONDS = 0.1
# How often a wait also asks the simulator whether the bot answered with a refusal.
ANSWER_POLL_SECONDS = 0.5
MAX_MOVES = 400
# Every `action` act takes, in the order a match needs them. The control panel keeps the same
# list (services/control-panel/src/api/control.ts); tests/test_devtools_panel_contract.py
# checks the two agree.
ACTIONS = (
    "ready",
    "vote",
    "checkin",
    "pick",
    "ban",
    "coinflip",
    "swap",
    "accept_swap",
    "decline_swap",
    "api_lobby",
    "lobby_code",
    "start_match",
    "report",
    "confirm",
    "dispute",
    "resolve",
    "void",
    "request_sub",
    "approve_sub",
    "cancel_sub",
    "invite_sub",
    "offer_queue",
    "accept_sub",
    "decline_sub",
)
# Done by nobody in the match: staff, or deadlock-api's lobby bot.
NO_PLAYER = frozenset({"resolve", "void", "api_lobby"})
# Discord component types.
BUTTON = 2
TEXT_INPUT = 4
FILE_UPLOAD = 19
# The simulator's answers to a press on a message that has just been replaced, or a component
# that has just been disabled: the bot moved on in between, so look again. No bot on the gateway
# is a 503 (BotOffline): waited out too, as the bot reconnects after a reset, but reported as such.
MOVED_ON = frozenset({404, 409})


@dataclass(slots=True)
class Move:
    player: Player | None
    action: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Done:
    player_id: int | None
    action: str
    args: dict[str, Any]
    via: str
    seconds: float

    def as_json(self) -> dict[str, Any]:
        return {
            "player_id": self.player_id,
            "action": self.action,
            "args": self.args,
            "via": self.via,
            "seconds": round(self.seconds, 3),
        }


def default_via() -> str:
    return DISCORD if sim_client.reachable() else SERVICE


def _fresh(match: Match) -> Match:
    return lookup.match(match.pk)


# --- Choices ---------------------------------------------------------------------------------


def _by_strength(match: Match, player_ids: list[int]) -> list[int]:
    """Strongest first, as the league compares them (mu), then lowest id."""
    rated = PlayerRating.objects.filter(season=match.season, player_id__in=player_ids)
    mus = {pk: int(mu * 1000) for pk, mu in rated.values_list("player_id", "mu")}
    strength = {pk: mus[pk] if pk in mus else match.season.strength_of(pk) for pk in player_ids}
    return sorted(player_ids, key=lambda pk: (-strength[pk], pk))


def default_votes(match: Match) -> list[int]:
    ids = list(match.participants.active().values_list("player_id", flat=True))
    rows = standing.eligibility(match.community, match.mode, ids)
    eligible = [pk for pk in ids if rows[pk].eligibility.ok]
    return _by_strength(match, eligible)[:2]


def choose_votes(match: Match, voter: Player, default: list[int] | None = None) -> list[int]:
    votes = script_of(match).get("captain_votes", {})
    if str(voter.pk) in votes:
        return list(votes[str(voter.pk)])
    if "*" in votes:
        return list(votes["*"])
    return default if default is not None else default_votes(match)


def choose_player_pick(match: Match) -> int:
    undrafted = list(
        match.participants.active().filter(team="").values_list("player_id", flat=True)
    )
    if not undrafted:
        raise Conflict("Nobody is left to draft.")
    for pk in script_of(match).get("draft", []):
        if pk in undrafted:
            return int(pk)
    return _by_strength(match, undrafted)[0]


def _step(match: Match) -> tuple[str, str]:
    """(ban, pick or player_pick; acting team) for the current draft step."""
    step = build_plan(match.mode)[match.step_index]
    first = match.player_first_pick if step.action == "player_pick" else match.champion_first_pick
    return step.action, team_for_role(step.role, first)


def choose_champion(match: Match) -> int:
    action, team = _step(match)
    available = draft.available_champions(match)
    if not available:
        raise Conflict("No champions are left.")
    champion_step = match.step_index - player_draft_length(match.mode)
    for entry in script_of(match).get("champions", []):
        wanted = entry["step"] == champion_step and entry.get("team") in {None, team}
        if wanted and entry["champion"] in available:
            return int(entry["champion"])
    roster = match.participants.filter(team=team, removed_reason="").order_by(
        "-is_captain", "draft_pick_number", "pk"
    )
    profiles = {
        p.player_id: p for p in DevProfile.objects.filter(player_id__in=roster.values("player_id"))
    }
    player_ids = list(roster.values_list("player_id", flat=True))
    for player_id in player_ids:
        profile = profiles.get(player_id)
        wanted = (profile.ban if action == "ban" else profile.prefer) if profile else []
        for champion_id in wanted:
            if champion_id in available:
                return int(champion_id)
    pool = set(available)
    if action == "ban":
        # A team out of bans takes a random one, but never a champion it wants to pick.
        own = {c for p in player_ids if (profile := profiles.get(p)) for c in profile.prefer}
        pool = pool - own or pool
    rng = random.Random(f"{match.rng_seed}:dev-champion:{match.step_index}")
    return rng.choice(sorted(pool))


def winner_of(match: Match) -> str:
    return str(script_of(match).get("winner", "A"))


def lobby_code_of(match: Match) -> str:
    return str(script_of(match).get("lobby_code", f"DEV{match.pk}"))


def placeholder_image(match: Match, player: Player) -> ImageRef:
    """A report's screenshot, for a match nobody really played."""
    count = match.submissions.count()
    digest = hashlib.sha256(f"dev:{match.pk}:{player.pk}:{count}".encode()).hexdigest()
    number = int(digest[:12], 16)
    return ImageRef(
        sha256=digest,
        archive_channel_id=match.community.archive_channel_id or 1,
        archive_message_id=number,
        attachment_id=number + 1,
        extension="png",
    )


def _first_of_team(match: Match, team: str) -> int:
    row = match.participants.active().filter(team=team, is_captain=False).order_by("pk").first()
    if row is None:
        raise Conflict(f"Team {team} has nobody to swap but its captain.")
    return row.player_id


def _team_of(match: Match, player: Player) -> str:
    row = match.participants.active().filter(player=player).first()
    if row is None or not row.team:
        raise Conflict(f"{player.display_name} isn't on a team in match #{match.pk}.")
    return row.team


def pending_swap(match: Match) -> PlayerSwap:
    swap = swaps.pending(match)
    if swap is None:
        raise Conflict(f"No swap is waiting for an answer in match #{match.pk}.")
    return swap


# --- The moves a phase needs ----------------------------------------------------------------


def next_moves(match: Match) -> list[Move]:
    """Who still has to act in the current phase, and what each does. Draft phases give one
    step at a time, since each step changes whose turn it is."""
    status = match.status
    if match.held_seconds is not None:
        raise Conflict(f"Match #{match.pk} is on hold for a sub. Settle the sub first.")
    active = match.participants.active()
    if status == Status.READY_CHECK:
        return [Move(p.player, "ready") for p in active.filter(ready_at__isnull=True)]
    if status == Status.CAPTAIN_PHASE:
        voted = set(match.captain_votes.values_list("voter_id", flat=True))
        default = default_votes(match)
        return [
            Move(p.player, "vote", {"candidates": choose_votes(match, p.player, default)})
            for p in active
            if p.player_id not in voted
        ]
    if status == Status.CAPTAIN_CHECKIN:
        waiting = active.filter(is_captain=True, checked_in_at__isnull=True).order_by("team")
        return [Move(p.player, "checkin") for p in waiting]
    if status == Status.PLAYER_DRAFT:
        return [
            Move(lookup.acting_captain(match), "pick", {"player_id": choose_player_pick(match)})
        ]
    if status == Status.COINFLIP:
        team, _ = draft.coinflip_turn(match)
        choice = str(script_of(match).get("coinflip", HIDDEN_KING))
        return [Move(match.captain_of(team).player, "coinflip", {"choice": choice})]
    if status == Status.CHAMPION_DRAFT:
        action, _ = _step(match)
        return [Move(lookup.acting_captain(match), action, {"champion": choose_champion(match)})]
    if status == Status.LOBBY_CODE:
        if not match.api_lobby_failed:
            return [Move(None, "api_lobby", {"create": control.lobbies() == control.CREATE})]
        return [Move(match.lobby_code_host, "lobby_code", {"code": lobby_code_of(match)})]
    if status == Status.IN_PROGRESS:
        captain = match.captain_of("A").player
        if match.api_party_id and match.api_started_at is None:
            return [Move(captain, "start_match")]
        return [Move(captain, "report", {"winner": winner_of(match)})]
    if status == Status.AWAITING_CONFIRMATION:
        return [Move(lookup.select_player(match, "other_captain"), "confirm")]
    if status == Status.DISPUTED:
        return [Move(None, "resolve", {"outcome": winner_of(match)})]
    raise Conflict(f"Match #{match.pk} is {status}: there is nothing left to play.")


# --- Making a move through the services ----------------------------------------------------


def _request_id(match: Match, args: dict[str, Any]) -> int:
    if "request_id" in args:
        return int(args["request_id"])
    request = match.sub_requests.filter(status__in=UNRESOLVED).order_by("-pk").first()
    if request is None:
        raise Conflict("No sub request is open for this match.")
    return request.pk


def _offer_id(match: Match, player: Player, args: dict[str, Any]) -> int:
    if "offer_id" in args:
        return int(args["offer_id"])
    offer = SubOffer.objects.filter(
        request__match=match, player=player, status=OfferStatus.PENDING
    ).first()
    if offer is None:
        raise Conflict(f"{player.display_name} has no pending sub offer for this match.")
    return offer.pk


def _need(player: Player | None, action: str) -> Player:
    if player is None:
        raise BadRequest(f"Say which player does {action}.")
    return player


def by_service(match: Match, move: Move) -> None:
    mid, args, action = match.pk, move.args, move.action
    if action == "resolve":
        results.resolve_dispute(
            mid, str(args["outcome"]), None, "Resolved from the dev control API"
        )
        return
    if action == "void":
        lobby.staff_void(mid, None, str(args.get("reason") or "Voided from the dev control API"))
        return
    if action == "api_lobby":
        # What the bot does with deadlock-api's answer.
        if args.get("create", True):
            draft.accept_api_lobby(mid, f"dev-{mid}", lobby_code_of(match))
        else:
            draft.api_lobby_failed(mid, "deadlock-api refused the lobby (dev control API)")
        return
    player = _need(move.player, action)
    if action == "ready":
        lobby.mark_ready(mid, player)
    elif action == "vote":
        lobby.cast_captain_votes(mid, player, [int(pk) for pk in args["candidates"]])
    elif action == "checkin":
        lobby.check_in(mid, player)
    elif action == "pick" and match.status == Status.PLAYER_DRAFT:
        draft.pick_player(mid, player, match.step_index, int(args["player_id"]))
    elif action in {"pick", "ban"}:
        draft.choose_champion(mid, player, match.step_index, int(args["champion"]))
    elif action == "coinflip":
        draft.choose_coinflip(mid, player, str(args["choice"]))
    elif action == "lobby_code":
        draft.submit_lobby_code(mid, player, str(args["code"]))
    elif action == "start_match":
        draft.check_can_start_api(mid, player)
        draft.mark_api_started(mid, player)
    elif action == "report":
        results.submit_report(mid, player, str(args["winner"]), placeholder_image(match, player))
    elif action == "confirm":
        results.confirm(mid, player)
    elif action == "dispute":
        results.dispute(mid, player, str(args.get("note") or "Disputed from the dev control API"))
    elif action == "swap":
        swaps.propose(mid, player, int(args["give"]), int(args["take"]))
    elif action in {"accept_swap", "decline_swap"}:
        swaps.answer(mid, player, int(args["swap_id"]), action == "accept_swap")
    elif action == "request_sub":
        subs.request_sub_out(mid, player, int(args["leaving"]))
    elif action == "approve_sub":
        subs.answer_sub_out(_request_id(match, args), player, bool(args.get("approve", True)))
    elif action == "cancel_sub":
        subs.cancel_sub(_request_id(match, args), player)
    elif action == "invite_sub":
        invitee = lookup.player(args["invitee"])
        subs.invite_sub(
            _request_id(match, args), player, invitee.discord_user_id, invitee.display_name
        )
    elif action == "offer_queue":
        subs.offer_to_queue(_request_id(match, args), player)
    elif action in {"accept_sub", "decline_sub"}:
        subs.answer_offer(_offer_id(match, player, args), player, action == "accept_sub")
    else:
        raise BadRequest(f"Unknown action {action!r}.")


# --- Making a move by pressing it in the simulator -----------------------------------------


def _wait(check: Callable[[], Any], what: str) -> Any:
    deadline = time.monotonic() + BOT_WAIT_SECONDS
    while True:
        result = check()
        if result:
            return result
        if time.monotonic() >= deadline:
            raise BotTimeout(what)
        time.sleep(POLL_SECONDS)


def _text_channel(match: Match) -> int:
    def find() -> int | None:
        return (
            MatchResource.objects.filter(
                match=match, kind=ResourceKind.TEXT, deleted_at__isnull=True
            )
            .values_list("discord_id", flat=True)
            .first()
        )

    return int(_wait(find, f"The bot hasn't created match #{match.pk}'s channel."))


def _walk(components: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every component in a (possibly nested) component tree, depth first."""
    found = []
    for component in components:
        found.append(component)
        children = list(component.get("components") or [])
        if isinstance(component.get("component"), dict):
            children.append(component["component"])
        found.extend(_walk(children))
    return found


def fingerprint(match_id: int) -> tuple[Any, ...]:
    """Everything a press can change, so a wait can tell when the bot's handler has run."""
    match = Match.objects.filter(pk=match_id).values_list(
        "version", "status", "held_seconds", "api_lobby_failed", "api_started_at"
    )
    participants = MatchParticipant.objects.filter(match_id=match_id, is_active=True)
    votes = CaptainVote.objects.filter(match_id=match_id)
    return (
        tuple(match.first() or ()),
        tuple(
            participants.order_by("player_id").values_list(
                "player_id", "ready_at", "checked_in_at", "team", "is_captain"
            )
        ),
        tuple(votes.order_by("pk").values_list("voter_id", "candidate_id")),
        tuple(SubRequest.objects.filter(match_id=match_id).values_list("pk", "status")),
        tuple(SubOffer.objects.filter(request__match_id=match_id).values_list("pk", "status")),
        tuple(PlayerSwap.objects.filter(match_id=match_id).values_list("pk", "status")),
        ResultSubmission.objects.filter(match_id=match_id).count(),
    )


@dataclass(frozen=True, slots=True)
class Actor:
    """Who presses: a player, or the guild owner for staff buttons."""

    discord_user_id: int
    name: str


def _actor(player: Player) -> Actor:
    return Actor(player.discord_user_id, player.display_name)


def _answer_text(result: dict[str, Any]) -> str | None:
    """What the bot said in reply to an interaction: plain text, as every refusal is. A picker
    it opened has components, and doesn't count."""
    for message in [result.get("message"), *(result.get("followups") or [])]:
        if isinstance(message, dict) and not message.get("components"):
            text = str(message.get("content") or "").strip()
            if text:
                return text
    return None


def _label(component: dict[str, Any]) -> str:
    return str(component.get("label") or component.get("placeholder") or component["custom_id"])


def queue_fingerprint(league: Community) -> tuple[Any, ...]:
    """Everything a queue press can change: who is queued, and who is in a match."""
    queued = QueueEntry.objects.filter(community=league).order_by("pk")
    playing = MatchParticipant.objects.filter(match__community=league, is_active=True)
    return (
        tuple(queued.values_list("player_id", flat=True)),
        tuple(playing.order_by("pk").values_list("player_id", flat=True)),
    )


class Clicker:
    """Presses components as fake users through the simulator, then waits for the bot to act:
    in a match's channel (`of_match`), or on the queue panel (`of_queue`)."""

    CHANNEL = "channel"
    DM = "dm"
    STAFF = "staff"

    def __init__(
        self,
        sim: sim_client.SimClient,
        community: Community,
        channel_id: int,
        match: Match | None = None,
    ) -> None:
        self.sim = sim
        self.community = community
        self.channel_id = channel_id
        self.match = match
        self.mid = match.pk if match is not None else 0

    @classmethod
    def of_match(cls, sim: sim_client.SimClient, match: Match) -> Clicker:
        return cls(sim, match.community, _text_channel(match), match)

    @classmethod
    def of_queue(cls, sim: sim_client.SimClient, league: Community) -> Clicker:
        if not league.queue_channel_id:
            raise Conflict("The community has no queue channel: run dev_seed.")
        return cls(sim, league, league.queue_channel_id)

    def snapshot(self) -> tuple[Any, ...]:
        return fingerprint(self.mid) if self.match else queue_fingerprint(self.community)

    # --- Finding and pressing --------------------------------------------------------------

    def _phase(self) -> str:
        return f"match #{self.mid} ({self.match.status})" if self.match else "the queue"

    def _messages(self, actor: Actor, where: str) -> list[dict[str, Any]]:
        if where == self.DM:
            return self.sim.dms(actor.discord_user_id)
        channel = self.channel_id
        if where == self.STAFF:
            channel = int(self.community.staff_channel_id or 0)
            if not channel:
                raise Conflict("The community has no staff channel: run dev_seed.")
        viewer = str(actor.discord_user_id)
        messages = sorted(self.sim.messages(channel), key=lambda m: int(m["id"]), reverse=True)
        return [m for m in messages if not m.get("ephemeral") or m.get("ephemeral_for") == viewer]

    def _usable(self, messages: list[dict[str, Any]]) -> list[tuple[int, dict[str, Any]]]:
        """Each enabled, pressable component, newest message first."""
        return [
            (int(message["id"]), component)
            for message in messages
            for component in _walk(list(message.get("components") or []))
            if component.get("custom_id") and not component.get("disabled")
        ]

    def _refused(self, interaction: dict[str, Any] | None, before: tuple[Any, ...]) -> str | None:
        """The bot's answer to the interaction, if it answered without changing anything."""
        if interaction is None or not interaction.get("interaction_id"):
            return None
        text = _answer_text(self.sim.interaction(str(interaction["interaction_id"])))
        if text is None or self.snapshot() != before:
            return None
        return text

    def press(
        self,
        actor: Actor,
        custom_id: str,
        what: str,
        *,
        where: str = CHANNEL,
        values: list[str] | None = None,
        after: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Press the component with this custom_id once the bot has posted it. `after` is the
        interaction that should post it: a refusal there ends the wait at once. A press on a
        message the bot replaces at that moment is retried."""
        deadline = time.monotonic() + BOT_WAIT_SECONDS
        before = self.snapshot()
        next_answer_check = time.monotonic() + ANSWER_POLL_SECONDS
        while True:
            offline: BotOffline | None = None  # This round's press found no bot to answer it.
            usable = self._usable(self._messages(actor, where))
            for message_id, component in usable:
                if component["custom_id"] != custom_id:
                    continue
                try:
                    return self.sim.component(actor.discord_user_id, message_id, custom_id, values)
                except BotOffline as exc:
                    offline = exc
                except SimError as exc:
                    if exc.sim_status not in MOVED_ON:
                        raise SimError(
                            f"{self._phase()}: pressing {what} as {actor.name}: {exc.message}",
                            exc.sim_status,
                        ) from exc
                break
            now = time.monotonic()
            if after is not None and now >= next_answer_check:
                next_answer_check = now + ANSWER_POLL_SECONDS
                refusal = self._refused(after, before)
                if refusal is not None:
                    raise Conflict(f"{self._phase()}: the bot told {actor.name}: {refusal}")
            if now >= deadline and offline is not None:
                raise BotOffline(
                    f"{self._phase()}: pressing {what} as {actor.name}: no bot is connected to "
                    f"the simulator's gateway (waited {BOT_WAIT_SECONDS:g} s). Is the bot "
                    "running? It reconnects by itself a few seconds after a reset.",
                    offline.sim_status,
                ) from offline
            if now >= deadline:
                labels = sorted({_label(component) for _, component in usable[:40]})
                there = (
                    f" Enabled there: {', '.join(labels)}."
                    if labels
                    else " Nothing there is enabled."
                )
                raise BotTimeout(
                    f"{self._phase()}: the bot hasn't posted {what} for {actor.name} in "
                    f"{BOT_WAIT_SECONDS:g} s.{there}"
                )
            time.sleep(POLL_SECONDS)

    def landed(self, actor: Actor, interaction: dict[str, Any], what: str) -> None:
        """Wait for the press to change the match, or for the bot to refuse it."""
        before = interaction["before"]
        deadline = time.monotonic() + BOT_WAIT_SECONDS
        next_answer_check = time.monotonic() + ANSWER_POLL_SECONDS
        while self.snapshot() == before:
            now = time.monotonic()
            if now >= next_answer_check:
                next_answer_check = now + ANSWER_POLL_SECONDS
                refusal = self._refused(interaction, before)
                if refusal is not None:
                    raise Conflict(f"{self._phase()}: the bot told {actor.name}: {refusal}")
            if now >= deadline:
                raise BotTimeout(
                    f"{self._phase()}: the bot didn't act on {what} by {actor.name} in "
                    f"{BOT_WAIT_SECONDS:g} s."
                )
            time.sleep(POLL_SECONDS)

    def act(
        self,
        actor: Actor,
        custom_id: str,
        what: str,
        *,
        where: str = CHANNEL,
        values: list[str] | None = None,
        after: dict[str, Any] | None = None,
    ) -> None:
        """Press, then wait for it to land."""
        before = self.snapshot()
        result = self.press(actor, custom_id, what, where=where, values=values, after=after)
        self.landed(actor, result | {"before": before}, what)

    def submit_modal(self, actor: Actor, opened: dict[str, Any], what: str, text: str = "") -> None:
        """Fill in the form a press opened, send it, and wait for it to land: `text` in each
        required text field, a placeholder screenshot in each file upload, optional fields
        left empty."""
        modal = opened.get("modal")
        if not modal:
            reply = _answer_text(opened) or "no form"
            raise Conflict(f"{self._phase()}: the bot told {actor.name}: {reply}")
        values: dict[str, Any] = {}
        uploads: list[str] = []
        for component in _walk(list(modal.get("components") or [])):
            custom_id = component.get("custom_id")
            if not custom_id:
                continue
            if component.get("type") == TEXT_INPUT:
                values[custom_id] = text if component.get("required", True) else ""
            elif component.get("type") == FILE_UPLOAD:
                uploads.append(custom_id)
        before = self.snapshot()
        try:
            result = self.sim.modal(actor.discord_user_id, values, attachments=uploads)
        except SimError as exc:
            # The same class: no bot on the gateway stays a 503, anything else a 502.
            raise type(exc)(
                f"{self._phase()}: sending {what} as {actor.name}: {exc.message}", exc.sim_status
            ) from exc
        self.landed(actor, result | {"before": before}, what)

    # --- Moves -----------------------------------------------------------------------------

    def _id(self, action: str, arg: object = "") -> str:
        return f"dl:v1:{action}:{self.mid}:{arg}"

    def make(self, move: Move) -> None:
        match, mid, args, action = self.match, self.mid, move.args, move.action
        assert match is not None
        if action == "api_lobby":
            # Nobody presses anything: deadlock-api answers the bot, which moves the match on.
            lobbies = control.lobbies()
            waiting = Match.objects.filter(pk=mid, status=Status.LOBBY_CODE, api_lobby_failed=False)
            _wait(
                lambda: not waiting.exists(),
                f"{self._phase()}: the bot hasn't settled the lobby with deadlock-api in "
                f"{BOT_WAIT_SECONDS:g} s (its stand-in is set to {lobbies}).",
            )
            return
        if action == "resolve":
            owner = Actor(int(self.sim.state()["guild"]["owner_id"]), "the server owner")
            outcome = str(args["outcome"])
            button = {"A": "resolve_a", "B": "resolve_b", "void": "resolve_void"}[outcome]
            self.act(owner, self._id(button), "the dispute card", where=self.STAFF)
            return
        player = _need(move.player, action)
        user = _actor(player)
        step = match.step_index
        if action == "ready":
            self.act(user, self._id("ready"), "the Ready button")
        elif action == "vote":
            candidates = [str(pk) for pk in args["candidates"]]
            vote = f"dl:v1s:captain_vote:{mid}:"
            self.act(user, vote, "the captain vote", values=candidates)
        elif action == "checkin":
            self.act(user, self._id("checkin"), "the I'm here button")
        elif action == "pick" and match.status == Status.PLAYER_DRAFT:
            self.act(user, self._id("pick_player", f"{step}.{args['player_id']}"), "the picks")
        elif action in {"pick", "ban"}:
            self._champion(user, step, int(args["champion"]))
        elif action == "coinflip":
            self.act(user, self._id("coin_choice", args["choice"]), "the coinflip buttons")
        elif action == "lobby_code":
            opened = self.press(user, self._id("code_open"), "the Enter lobby code button")
            self.submit_modal(user, opened, "the lobby code", str(args["code"]))
        elif action == "start_match":
            self.act(user, self._id("api_start"), "the Start match button")
        elif action == "report":
            opened = self.press(user, self._id("report_open", args["winner"]), "the report")
            self.submit_modal(user, opened, "the report")
        elif action == "confirm":
            self.act(user, self._id("confirm"), "the Confirm button")
        elif action == "dispute":
            opened = self.press(user, self._id("dispute_open"), "the Dispute button")
            self.submit_modal(user, opened, "the dispute", str(args.get("note") or "Disputed"))
        elif action == "swap":
            opened = self.press(user, self._id("swap_open"), "the Swap players button")
            offer = self.press(
                user, self._id("swap_give", args["give"]), "your players", after=opened
            )
            take = self._id("swap_take", f"{args['give']}.{args['take']}")
            self.act(user, take, "their players", after=offer)
        elif action in {"accept_swap", "decline_swap"}:
            button = "swap_yes" if action == "accept_swap" else "swap_no"
            self.act(user, self._id(button, args["swap_id"]), "the swap offer")
        elif action == "request_sub":
            opened = self.press(user, self._id("sub_open"), "the Request a sub button")
            self.act(user, self._id("sub_out", args["leaving"]), "who comes out", after=opened)
        elif action == "approve_sub":
            button = "sub_approve" if args.get("approve", True) else "sub_reject"
            self.act(user, self._id(button, _request_id(match, args)), "the sub request")
        elif action == "cancel_sub":
            self.act(user, self._id("sub_cancel", _request_id(match, args)), "Cancel sub")
        elif action == "offer_queue":
            self.act(user, self._id("sub_queue", _request_id(match, args)), "Ask the queue")
        elif action == "invite_sub":
            request_id = _request_id(match, args)
            opened = self.press(user, self._id("sub_invite_open", request_id), "Name a sub")
            invitee = str(lookup.player(args["invitee"]).discord_user_id)
            picker = f"dl:v1u:sub_invite:{mid}:{request_id}"
            self.act(user, picker, "the sub picker", values=[invitee], after=opened)
        elif action in {"accept_sub", "decline_sub"}:
            button = "sub_accept" if action == "accept_sub" else "sub_decline"
            offer_id = _offer_id(match, player, args)
            self.act(user, self._id(button, offer_id), "the sub offer DM", where=self.DM)
        else:
            raise BadRequest(f"{action} has no component to press.")

    def _champion(self, user: Actor, step: int, champion: int) -> None:
        """The champion grid's button, or its dropdown when the roster is too big for buttons."""
        button = self._id("choose_champion", f"{step}.{champion}")
        deadline = time.monotonic() + BOT_WAIT_SECONDS
        while True:
            usable = self._usable(self._messages(user, self.CHANNEL))
            for _, component in usable:
                custom_id = str(component["custom_id"])
                if custom_id == button:
                    self.act(user, button, "the champion grid")
                    return
                options = [str(option.get("value")) for option in component.get("options") or []]
                if f":pick_champion:{self.mid}:{step}." in custom_id and str(champion) in options:
                    self.act(user, custom_id, "the champion dropdown", values=[str(champion)])
                    return
            if time.monotonic() >= deadline:
                labels = sorted({_label(component) for _, component in usable[:40]})
                there = f" Enabled there: {', '.join(labels)}." if labels else ""
                raise BotTimeout(
                    f"{self._phase()}: the bot hasn't posted the champion grid (step {step}) "
                    f"for {user.name} in {BOT_WAIT_SECONDS:g} s.{there}"
                )
            time.sleep(POLL_SECONDS)


# Actions that have no player component: always through the services.
SERVICE_ONLY = frozenset({"void"})


def make(match: Match, move: Move, via: str) -> Done:
    """Make one move, then keep a frozen match frozen."""
    if via not in {SERVICE, DISCORD}:
        raise BadRequest('via is "service" or "discord".')
    used = SERVICE if move.action in SERVICE_ONLY else via
    started = time.monotonic()
    if used == DISCORD:
        with sim_client.client() as sim:
            Clicker.of_match(sim, match).make(move)
    else:
        by_service(match, move)
    timers.refreeze(match.pk)
    player_id = move.player.pk if move.player else None
    return Done(player_id, move.action, move.args, used, time.monotonic() - started)


def press_queue(league: Community, players: list[Player], action: str) -> None:
    """Press Join or Leave on the queue panel as each player, in order, through the bot."""
    with sim_client.client() as sim:
        clicker = Clicker.of_queue(sim, league)
        for player in players:
            clicker.act(
                _actor(player), f"dl:v1:{action}:0:", f"the queue's {action.title()} button"
            )


# --- act and advance -------------------------------------------------------------------------


def _player_arg(match: Match, args: dict[str, Any], key: str, default: Callable[[], int]) -> int:
    ref = args.get(key)
    return lookup.select_player(match, ref).pk if ref is not None else default()


def _default_args(
    match: Match, player: Player | None, action: str, args: dict[str, Any]
) -> dict[str, Any]:
    args = dict(args)
    if action == "vote" and "candidates" not in args and player is not None:
        args["candidates"] = choose_votes(match, player)
    elif action == "pick" and match.status == Status.PLAYER_DRAFT:
        args["player_id"] = _player_arg(match, args, "player_id", lambda: choose_player_pick(match))
    elif action in {"pick", "ban"}:
        step_action, _ = _step(match) if match.status == Status.CHAMPION_DRAFT else ("", "")
        if step_action and step_action != action:
            raise BadRequest(f"This step is a {step_action}, not a {action}.")
        champion = args.get("champion")
        args["champion"] = (
            lookup.champion(champion).pk if champion is not None else choose_champion(match)
        )
    elif action == "coinflip":
        args.setdefault("choice", script_of(match).get("coinflip", HIDDEN_KING))
    elif action == "lobby_code":
        args.setdefault("code", lobby_code_of(match))
        if not LOBBY_CODE.match(str(args["code"])):
            raise BadRequest("A lobby code is 3 to 32 letters, digits or dashes.")
    elif action == "api_lobby":
        args["create"] = bool(args.get("create", control.lobbies() == control.CREATE))
    elif action == "report":
        args.setdefault("winner", winner_of(match))
    elif action == "resolve":
        args.setdefault("outcome", winner_of(match))
        if args["outcome"] not in {"A", "B", "void"}:
            raise BadRequest('A dispute is resolved as "A", "B" or "void".')
    elif action == "swap" and player is not None:
        own = _team_of(match, player)
        other = "B" if own == "A" else "A"
        args["give"] = _player_arg(match, args, "give", lambda: _first_of_team(match, own))
        args["take"] = _player_arg(match, args, "take", lambda: _first_of_team(match, other))
    elif action in {"accept_swap", "decline_swap"}:
        args.setdefault("swap_id", pending_swap(match).pk)
    elif action == "request_sub":
        leaving = args.get("leaving")
        if leaving is not None:
            args["leaving"] = lookup.select_player(match, leaving).pk
        elif player is not None:
            args["leaving"] = player.pk
    elif action == "invite_sub":
        if "invitee" not in args:
            raise BadRequest("invite_sub needs an invitee.")
        args["invitee"] = lookup.player(args["invitee"]).pk
    return args


def _default_player(match: Match, action: str) -> Player:
    """Who does an action nobody is due to: a captain, for the captains' own buttons."""
    if action in {"swap", "start_match"}:
        return match.captain_of("A").player
    if action in {"accept_swap", "decline_swap"}:
        swap = pending_swap(match)
        team = "B" if _team_of(match, swap.requested_by) == "A" else "A"
        return match.captain_of(team).player
    waiting = [move.player for move in _safe_moves(match) if move.action == action and move.player]
    if not waiting:
        raise BadRequest(f"Nobody is due to {action} now: say which player does it.")
    return waiting[0]


def act(
    match_ref: str | int,
    player_ref: int | str | None,
    action: str,
    args: dict[str, Any],
    via: str | None,
) -> list[Done]:
    if action not in ACTIONS:
        raise BadRequest(f"Unknown action {action!r}. act takes {', '.join(ACTIONS)}.")
    match = lookup.match(match_ref)
    player: Player | None = None
    if player_ref == "offered":
        _offer_open_seats(match)
    if player_ref is not None:
        player = lookup.select_player(match, player_ref)
    elif action not in NO_PLAYER:
        player = _default_player(match, action)
    move = Move(player, action, _default_args(match, player, action, args))
    return [make(match, move, via or default_via())]


def _offer_open_seats(match: Match) -> None:
    """Before acting as `offered`: an open seat nobody has been asked for yet, with someone
    waiting in the queue, is offered to them on the deadline loop's next pass (`subs.tick`, every
    second). Run that pass now, as `fire` does, so the offer is there whichever comes first: the
    league locks the request and checks again, so the loop's own pass can't offer twice."""
    if SubOffer.objects.filter(request__match=match, status=OfferStatus.PENDING).exists():
        return
    unasked = (
        SubRequest.objects.filter(match=match, status=SubStatus.OPEN)
        .exclude(offers__status=OfferStatus.PENDING)
        .exists()
    )
    community = match.community_id
    waiting = (
        QueueEntry.objects.filter(community_id=community).exists()
        or PrioEntry.objects.filter(community_id=community, grace_until__isnull=True).exists()
    )
    if unasked and waiting:
        subs.tick(timezone.now())


def _safe_moves(match: Match) -> list[Move]:
    try:
        return next_moves(match)
    except Conflict:
        return []


def _rank(status: str) -> int:
    if status == Status.DISPUTED:
        return ORDER.index(Status.AWAITING_CONFIRMATION)
    return ORDER.index(status)


def complete_phase(match: Match, via: str) -> list[Done]:
    """Act as every player who still has to, until the match leaves its current status."""
    done: list[Done] = []
    status = match.status
    while match.status == status:
        moves = next_moves(match)
        if not moves:
            raise Conflict(f"Match #{match.pk} is waiting on nobody in {status}.")
        for move in moves:
            if len(done) >= MAX_MOVES:
                raise Conflict(f"Match #{match.pk} didn't finish {status} in {MAX_MOVES} moves.")
            done.append(make(match, move, via))
            match = _fresh(match)
            if match.status != status:
                break
    return done


@dataclass(frozen=True, slots=True)
class Phase:
    status: str
    seconds: float
    actions: int

    def as_json(self) -> dict[str, Any]:
        return {"status": self.status, "seconds": round(self.seconds, 3), "actions": self.actions}


def advance(
    match_ref: str | int, until: str | None, via: str | None
) -> tuple[Match, str, list[Done], list[Phase]]:
    """Complete the current phase, or every phase until the match reaches `until`. A match
    already at or past `until` is left as it is: the bot can move on by itself, as when
    deadlock-api's lobby takes the match straight past lobby_code."""
    match = lookup.match(match_ref)
    start = match.status
    if match.kind == MatchKind.SCRIM:
        raise Conflict("advance plays ranked matches only.")
    if until is not None and until not in ORDER[1:]:
        raise BadRequest(f"until is one of {', '.join(ORDER[1:])}.")
    if via is not None and via not in {SERVICE, DISCORD}:
        raise BadRequest('via is "service" or "discord".')
    if until is not None and (start in TERMINAL or _rank(until) <= _rank(start)):
        return match, start, [], []
    if start not in LIVE:
        raise Conflict(f"Match #{match.pk} is {start}: it's over.")
    mode = via or default_via()
    done: list[Done] = []
    phases: list[Phase] = []
    while True:
        started, status = time.monotonic(), match.status
        moves = complete_phase(match, mode)
        done.extend(moves)
        phases.append(Phase(status, time.monotonic() - started, len(moves)))
        match = _fresh(match)
        if until is None or match.status in TERMINAL or _rank(match.status) >= _rank(until):
            return match, start, done, phases
