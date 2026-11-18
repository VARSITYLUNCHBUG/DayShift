"""Random sequences of clicks, double clicks, timeouts, restarts and voids.

Whatever order these arrive in, a match must never break its invariants or get stuck.
"""

from __future__ import annotations

import json
import os
from datetime import timedelta

import pytest
from django.db import transaction
from django.utils import timezone
from hypothesis import HealthCheck, seed, settings
from hypothesis.stateful import (
    RuleBasedStateMachine,
    initialize,
    invariant,
    rule,
    run_state_machine_as_test,
)
from hypothesis.strategies import integers, sampled_from

from league.domain.draft_plan import build_plan, team_for_role
from league.domain.engine import (
    LIVE,
    RANKED_COINFLIP_CHOICES,
    Status,
    apply_coinflip,
    apply_ranked_coinflip,
)
from league.domain.errors import DomainError
from league.models import DraftAction, Match, Player, QueueEntry
from league.services import (
    corrections,
    deadlines,
    draft,
    integrity,
    lobby,
    queue,
    results,
    subs,
    swaps,
)
from tests.conftest import Clock, make_player
from tests.helpers import (
    check_in_captains,
    image,
    run_champion_draft,
    run_player_draft,
    settle_coinflip_for,
    vote_captains,
)


class MatchMachine(RuleBasedStateMachine):
    """Runs inside a savepoint per example, so each example starts clean and fast."""

    # Set per chunk by `chunk_machine`, so chunks sharing a worker never share them.
    community_id: int
    clock: Clock
    statuses_seen: set[str]

    def __init__(self) -> None:
        super().__init__()
        self.savepoint = transaction.savepoint()
        self.players = [make_player(n) for n in range(1, 16)]
        for player in self.players[:12]:
            queue.join(self.community_id, player)
        self.match = Match.objects.order_by("-id").first()
        self.image_number = 0

    @initialize(everyone_ready=sampled_from([True, True, True, True, False]))
    def start(self, everyone_ready: bool) -> None:
        # Twelve separate random clicks almost never line up before a timeout, so most runs
        # start past the ready check. Otherwise the later phases would barely get tested.
        if everyone_ready:
            for player in self.players[:12]:
                self._try(lobby.mark_ready, self.match.pk, player)

    def teardown(self) -> None:
        transaction.savepoint_rollback(self.savepoint)

    def _fresh(self) -> Match:
        return Match.objects.select_related("mode_version", "season", "community").get(
            pk=self.match.pk
        )

    def _try(self, call, *args) -> None:
        try:
            with transaction.atomic():
                call(*args)
        except DomainError:
            pass  # A refused action is a legitimate outcome. Invariants decide if it was right.

    @rule(index=integers(0, 14))
    def ready(self, index: int) -> None:
        self._try(lobby.mark_ready, self.match.pk, self.players[index])

    @rule(voter=integers(0, 14), first=integers(0, 14), second=integers(0, 14))
    def vote(self, voter: int, first: int, second: int) -> None:
        chosen = [self.players[first].pk, self.players[second].pk]
        self._try(lobby.cast_captain_votes, self.match.pk, self.players[voter], chosen)

    @rule(
        index=integers(0, 14),
        choice=sampled_from(["hidden_king", "archmother", "first_pick"]),
    )
    def coin_choice(self, index: int, choice: str) -> None:
        self._try(draft.choose_coinflip, self.match.pk, self.players[index], choice)

    @rule(index=integers(0, 14))
    def check_in(self, index: int) -> None:
        self._try(lobby.check_in, self.match.pk, self.players[index])

    @rule(give=integers(0, 11), take=integers(0, 11), accept=sampled_from([True, False]))
    def swap(self, give: int, take: int, accept: bool) -> None:
        match = self._fresh()
        if match.status not in swaps.SWAPPABLE:
            return
        a = match.participants.filter(is_active=True, is_captain=True, team="A").first()
        b = match.participants.filter(is_active=True, is_captain=True, team="B").first()
        if a is None or b is None:
            return
        offer = (self.players[give].pk, self.players[take].pk)
        try:
            with transaction.atomic():
                made = swaps.propose(match.pk, a.player, *offer)
        except DomainError:
            return
        self._try(swaps.answer, match.pk, b.player, made.pk, accept)

    @rule(works=sampled_from([True, False]))
    def api_answers(self, works: bool) -> None:
        match = self._fresh()
        if match.status != Status.LOBBY_CODE:
            return
        if works:
            self._try(draft.accept_api_lobby, match.pk, "party", "API123")
        else:
            self._try(draft.api_lobby_failed, match.pk, "down")

    def _acting(self, match: Match, status: str) -> Player | None:
        if match.status != status:
            return None
        step = build_plan(match.mode)[match.step_index]
        first = (
            match.player_first_pick if status == Status.PLAYER_DRAFT else match.champion_first_pick
        )
        return match.captain_of(team_for_role(step.role, first)).player

    @rule(pick=integers(0, 11), double_click=sampled_from([False, True]))
    def pick_player(self, pick: int, double_click: bool) -> None:
        match = self._fresh()
        captain = self._acting(match, Status.PLAYER_DRAFT)
        if captain is None:
            return
        step = match.step_index
        undrafted = list(match.participants.filter(is_active=True, team=""))
        if not undrafted:
            return
        target = undrafted[pick % len(undrafted)].player_id
        self._try(draft.pick_player, match.pk, captain, step, target)
        if double_click:
            self._try(draft.pick_player, match.pk, captain, step, target)

    @rule(pick=integers(0, 43), double_click=sampled_from([False, True]))
    def pick_champion(self, pick: int, double_click: bool) -> None:
        match = self._fresh()
        captain = self._acting(match, Status.CHAMPION_DRAFT)
        if captain is None:
            return
        step = match.step_index
        champion = match.champion_pool[pick % len(match.champion_pool)]
        self._try(draft.choose_champion, match.pk, captain, step, champion)
        if double_click:
            self._try(draft.choose_champion, match.pk, captain, step, champion)

    @rule(double_click=sampled_from([False, True]))
    def press_random(self, double_click: bool) -> None:
        match = self._fresh()
        captain = self._acting(match, Status.CHAMPION_DRAFT)
        if captain is None:
            return
        step = match.step_index
        self._try(draft.choose_random_champion, match.pk, captain, step)
        if double_click:
            self._try(draft.choose_random_champion, match.pk, captain, step)

    @rule()
    def submit_code(self) -> None:
        match = self._fresh()
        if match.status == Status.LOBBY_CODE:
            self._try(draft.submit_lobby_code, match.pk, match.lobby_code_host, "ABC123")

    @rule(team=sampled_from(["A", "B"]), winner=sampled_from(["A", "B"]))
    def report(self, team: str, winner: str) -> None:
        match = self._fresh()
        if match.status not in {Status.IN_PROGRESS, Status.AWAITING_CONFIRMATION}:
            return
        self.image_number += 1
        self._try(
            results.submit_report,
            match.pk,
            match.captain_of(team).player,
            winner,
            image(self.image_number),
        )

    @rule(team=sampled_from(["A", "B"]))
    def confirm(self, team: str) -> None:
        match = self._fresh()
        if match.status == Status.AWAITING_CONFIRMATION:
            self._try(results.confirm, match.pk, match.captain_of(team).player)

    @rule(team=sampled_from(["A", "B"]))
    def dispute(self, team: str) -> None:
        match = self._fresh()
        if match.status == Status.AWAITING_CONFIRMATION:
            self._try(results.dispute, match.pk, match.captain_of(team).player, "No")

    @rule(accept=sampled_from([True, True, False]))
    def answer_offers(self, accept: bool) -> None:
        """Whoever was offered an open spot answers, as a waiting player would."""
        from league.models import SubOffer

        for offer in SubOffer.objects.filter(request__match=self.match, status="pending"):
            self._try(subs.answer_offer, offer.pk, offer.player, accept)

    @rule(outcome=sampled_from(["A", "B", "void"]))
    def staff_resolves(self, outcome: str) -> None:
        self._try(results.resolve_dispute, self.match.pk, outcome, None, "Staff")

    @rule(agree=sampled_from([True, True, False]))
    def play_through_current_phase(self, agree: bool) -> None:
        # Random clicks alone rarely finish a 10-pick draft inside one run, so this rule walks
        # a whole phase. The other rules still land at any point before and after it.
        match = self._fresh()
        if match.status == Status.CAPTAIN_PHASE:
            self._try(vote_captains, match)
        elif match.status == Status.CAPTAIN_CHECKIN:
            # On through the player draft and coinflip too: check-in is one more phase to walk.
            self._try(
                lambda: settle_coinflip_for(
                    run_player_draft(check_in_captains(match)), "A" if agree else "B"
                )
            )
        elif match.status == Status.PLAYER_DRAFT:
            # Straight on through the coinflip. The coin_choice rule covers it on its own.
            self._try(lambda: settle_coinflip_for(run_player_draft(match), "A" if agree else "B"))
        elif match.status == Status.COINFLIP:
            self._try(settle_coinflip_for, match, "A" if agree else "B")
        elif match.status == Status.CHAMPION_DRAFT:
            self._try(run_champion_draft, match)
            if agree:  # And the bot makes the lobby, as it usually does.
                self._try(draft.accept_api_lobby, match.pk, "party", "API123")
        elif match.status == Status.LOBBY_CODE:
            if agree:
                self._try(draft.accept_api_lobby, match.pk, "party", "API123")
            else:
                self._try(draft.api_lobby_failed, match.pk, "down")
                self._try(draft.submit_lobby_code, match.pk, match.lobby_code_host, "ABC123")
        elif match.status == Status.IN_PROGRESS:
            self.image_number += 1
            captain = match.captain_of("A").player
            self._try(results.submit_report, match.pk, captain, "A", image(self.image_number))
        elif match.status == Status.AWAITING_CONFIRMATION:
            captain = match.captain_of("B").player
            if agree:
                self._try(results.confirm, match.pk, captain)
            else:
                self._try(results.dispute, match.pk, captain, "No")

    @rule(seconds=sampled_from([1, 31, 46, 181, 901, 11000]))
    def time_passes(self, seconds: int) -> None:
        self.clock.advance(seconds)
        deadlines.tick()

    @rule()
    def restart(self) -> None:
        deadlines.extend_past_due()

    @rule(roll=integers(0, 9))
    def staff_voids_live(self, roll: int) -> None:
        # Uncommon, or it would end most runs before they reach anything interesting.
        if roll == 0:
            self._try(lobby.staff_void, self.match.pk, None, "Called off")

    @rule(outcome=sampled_from(["A", "B", "void"]))
    def correct_finished(self, outcome: str) -> None:
        self._try(corrections.apply_outcome_correction, self.match.pk, outcome, None, "Fix")

    @rule(index=integers(12, 14))
    def late_joiner(self, index: int) -> None:
        self._try(queue.join, self.community_id, self.players[index])

    @invariant()
    def ledger_is_consistent(self) -> None:
        match = self._fresh()
        # Every phase the match went through, including ones a single rule passed straight over.
        self.statuses_seen.update(match.transitions.values_list("to_status", flat=True))
        assert integrity.check_all() == []

    @invariant()
    def draft_rows_match_step_index(self) -> None:
        match = self._fresh()
        if match.status in {Status.PLAYER_DRAFT, Status.COINFLIP, Status.CHAMPION_DRAFT}:
            assert DraftAction.objects.filter(match=match).count() == match.step_index

    @invariant()
    def live_match_always_has_a_way_forward(self) -> None:
        match = self._fresh()
        if match.status not in LIVE:
            return
        if match.held_seconds is not None:  # On hold: an open spot's own deadline stands in.
            assert match.sub_requests.filter(
                status__in=("approval", "open"), deadline_at__isnull=False
            ).exists(), f"{match.status} is on hold with nothing to end it"
        else:
            assert match.deadline_at is not None, f"{match.status} has no deadline: it could hang"

    @invariant()
    def captains_are_consistent(self) -> None:
        match = self._fresh()
        if match.status == Status.CAPTAIN_PHASE:  # Nobody is captain until the vote closes.
            assert not match.participants.filter(is_captain=True, is_active=True).exists()
        elif match.status not in {Status.READY_CHECK, Status.VOIDED}:
            for team in ("A", "B"):
                assert match.participants.filter(is_captain=True, team=team).count() == 1

    @invariant()
    def sides_follow_the_coinflip(self) -> None:
        """Once the coinflip is settled, the sides and first pick are what was chosen."""
        match = self._fresh()
        if match.coinflip_winner_choice in RANKED_COINFLIP_CHOICES:
            assert (match.hidden_king_team, match.champion_first_pick) == apply_ranked_coinflip(
                match.coinflip_winner, match.coinflip_winner_choice
            )
        elif match.coinflip_loser_choice:
            assert (match.hidden_king_team, match.champion_first_pick) == apply_coinflip(
                match.coinflip_winner, match.coinflip_winner_choice, match.coinflip_loser_choice
            )
        elif match.champion_first_pick:
            raise AssertionError("First pick was set without a finished coinflip.")

    @invariant()
    def teams_never_exceed_their_size(self) -> None:
        match = self._fresh()
        for team in ("A", "B"):
            assert match.participants.filter(team=team, removed_reason="").count() <= 6

    @invariant()
    def no_player_is_both_queued_and_live(self) -> None:
        for entry in QueueEntry.objects.select_related("player"):
            assert not entry.player.matches.filter(is_active=True).exists()

    @invariant()
    def no_champion_is_used_twice(self) -> None:
        match = self._fresh()
        used = list(
            match.draft_actions.exclude(target_champion=None).values_list(
                "target_champion_id", flat=True
            )
        )
        assert len(used) == len(set(used))


# The run is split into seeded chunks so pytest-xdist can spread it over workers. Each chunk also
# runs Hypothesis's simplest example first, so it gets one more than its share of the total.
CHUNKS = 10
EXAMPLES = 60
EXPLORE_EXAMPLES = 150

# Guards against the machine passing only because it never got anywhere interesting.
MUST_REACH = frozenset(
    {
        Status.CAPTAIN_PHASE,
        Status.CAPTAIN_CHECKIN,
        Status.PLAYER_DRAFT,
        Status.COINFLIP,
        Status.CHAMPION_DRAFT,
        Status.LOBBY_CODE,
        Status.IN_PROGRESS,
        Status.AWAITING_CONFIRMATION,
        Status.DISPUTED,
        Status.COMPLETED,
        Status.VOIDED,
    }
)


def chunk_machine(chunk: int, community_id: int, clock: Clock, explore: bool) -> type[MatchMachine]:
    """A fresh subclass per chunk. Unless exploring, its seed fixes the examples it runs."""
    machine: type[MatchMachine] = type(
        f"MatchMachine{chunk}",
        (MatchMachine,),
        {"community_id": community_id, "clock": clock, "statuses_seen": set()},
    )
    return machine if explore else seed(chunk)(machine)


def statuses_of_every_chunk(
    tmp_path_factory: pytest.TempPathFactory, chunk: int, seen: set[str]
) -> set[str] | None:
    """Saves what this chunk reached. Once every chunk has, returns what they reached together.

    The files go in the run's temp folder, which holds each xdist worker's own folder.
    """
    base = tmp_path_factory.getbasetemp()
    if os.environ.get("PYTEST_XDIST_WORKER"):
        base = base.parent
    folder = base / "match-machine"
    folder.mkdir(exist_ok=True)
    partial = folder / f"{chunk}.part"
    partial.write_text(json.dumps(sorted(seen)), encoding="utf-8")
    partial.replace(folder / f"{chunk}.json")  # Atomic, so a reader never sees half a file.
    saved = list(folder.glob("*.json"))
    if len(saved) < CHUNKS:
        return None
    return {status for path in saved for status in json.loads(path.read_text(encoding="utf-8"))}


@pytest.mark.slow
@pytest.mark.django_db
@pytest.mark.parametrize("chunk", range(CHUNKS))
def test_match_machine(
    chunk: int, league, clock: Clock, tmp_path_factory: pytest.TempPathFactory
) -> None:
    # Fixed by default, so a failure means something changed rather than bad luck. Set EXPLORE=1
    # for a longer hunt through sequences this run hasn't tried.
    explore = bool(os.environ.get("EXPLORE"))
    assert clock.now() >= timezone.now() - timedelta(seconds=5)
    machine = chunk_machine(chunk, league.pk, clock, explore)
    run_state_machine_as_test(
        machine,
        settings=settings(
            database=None,  # The same examples in every checkout, not ones saved locally.
            max_examples=1 + (EXPLORE_EXAMPLES if explore else EXAMPLES) // CHUNKS,
            stateful_step_count=56,  # The 18-step champion draft takes a few more.
            deadline=None,
            suppress_health_check=list(HealthCheck),
        ),
    )
    # The chunks share the job, so whichever finishes last checks what they reached together.
    reached = statuses_of_every_chunk(tmp_path_factory, chunk, machine.statuses_seen)
    if reached is not None:
        assert reached >= MUST_REACH, sorted(MUST_REACH - reached)
