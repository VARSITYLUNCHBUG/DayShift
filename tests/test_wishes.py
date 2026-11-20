"""Hero wishes: who may set them and when, and who sees them."""

from __future__ import annotations

import pytest

from league.domain.engine import Status
from league.domain.errors import InvalidAction, NotAllowed, StaleAction
from league.models import Champion, HeroWish, Match, MatchParticipant, Player
from league.services import draft, subs, swaps, wishes
from league.web.live import schema, snapshots
from tests.conftest import make_player
from tests.helpers import (
    acting_captain,
    finish,
    fresh,
    ready_all,
    run_champion_draft,
    run_player_draft,
    to_champion_draft,
    to_in_progress,
    vote_captains,
)

pytestmark = pytest.mark.django_db


def _seat(match: Match, team: str, captain: bool = False) -> MatchParticipant:
    row = (
        match.participants.filter(removed_reason="", team=team, is_captain=captain)
        .select_related("player")
        .order_by("id")
        .first()
    )
    assert row is not None
    return row


def _player(match: Match, team: str, captain: bool = False) -> Player:
    return _seat(match, team, captain).player


def _heroes(match: Match, count: int = 3) -> list[int]:
    return sorted(fresh(match).champion_pool)[:count]


def _seen(match: Match, viewer: Player | None) -> schema.MatchSnap:
    body = snapshots.build_match(match.pk)
    assert body is not None
    return snapshots.project_match(body, viewer.pk if viewer else None)


def _wished(match: Match, player: Player) -> list[int]:
    return list(
        HeroWish.objects.filter(match=match, player=player)
        .order_by("rank")
        .values_list("champion_id", flat=True)
    )


def _coinflip(popped: Match) -> Match:
    match = run_player_draft(vote_captains(ready_all(popped)))
    assert match.status == Status.COINFLIP
    return match


# --- Setting them -----------------------------------------------------------------------------


def test_a_player_sets_replaces_and_clears_their_wishes(popped: Match) -> None:
    match = _coinflip(popped)
    player = _player(match, "A")
    one, two, three = _heroes(match)
    version = fresh(match).version
    wishes.set_wishes(match.pk, player, [two, one])
    assert _wished(match, player) == [two, one]
    assert fresh(match).version == version + 1  # Published: the team's pages refresh.
    wishes.set_wishes(match.pk, player, [three, two, one])
    assert _wished(match, player) == [three, two, one]
    wishes.set_wishes(match.pk, player, [three, two, one])
    assert fresh(match).version == version + 2  # The same again changes nothing.
    wishes.set_wishes(match.pk, player, [])
    assert _wished(match, player) == []


def test_captains_wish_too_and_in_the_hero_draft(popped: Match) -> None:
    match = to_champion_draft(popped)
    captain = _player(match, "B", captain=True)
    wishes.set_wishes(match.pk, captain, _heroes(match, 1))
    assert _wished(match, captain) == _heroes(match, 1)


def test_banned_and_taken_heroes_may_be_wished_for(popped: Match) -> None:
    match = to_champion_draft(popped)
    banned = draft.available_champions(match)[0]
    draft.choose_champion(match.pk, acting_captain(match), match.step_index, banned)
    player = _player(match, "A")
    wishes.set_wishes(match.pk, player, [banned])
    assert _wished(match, player) == [banned]
    seen = _seen(match, player)
    assert next(choice for choice in seen.champions if choice.id == str(banned)).taken


@pytest.mark.parametrize(
    ("pick", "message"),
    [
        (lambda heroes: heroes[:4], "Wish for up to 3 heroes."),
        (lambda heroes: [heroes[0], heroes[0]], "Wish for each hero only once."),
        (lambda heroes: [999_999], "That hero isn't in this draft."),
    ],
    ids=["more than three", "a duplicate", "an unknown hero"],
)
def test_bad_wishes_are_refused_in_words(popped: Match, pick: object, message: str) -> None:
    match = _coinflip(popped)
    player = _player(match, "A")
    with pytest.raises(InvalidAction) as refused:
        wishes.set_wishes(match.pk, player, pick(_heroes(match, 4)))  # type: ignore[operator]
    assert refused.value.message == message
    assert _wished(match, player) == []


def test_a_disabled_hero_is_refused(popped: Match) -> None:
    match = _coinflip(popped)
    hero = _heroes(match, 1)[0]
    Champion.objects.filter(pk=hero).update(is_enabled=False)
    with pytest.raises(InvalidAction):
        wishes.set_wishes(match.pk, _player(match, "A"), [hero])


@pytest.mark.parametrize("stage", ["player_draft", "lobby_code", "in_progress"])
def test_wishes_can_only_change_from_the_coinflip_to_the_hero_draft(
    popped: Match, stage: str
) -> None:
    match = vote_captains(ready_all(popped))
    if stage == "lobby_code":
        match = run_champion_draft(to_champion_draft(match))
    elif stage == "in_progress":
        match = to_in_progress(match)
    assert match.status == stage
    with pytest.raises(StaleAction):
        wishes.set_wishes(match.pk, _player(match, "A", captain=True), _heroes(match, 1))


def test_only_the_teams_players_may_wish(popped: Match) -> None:
    match = _coinflip(popped)
    with pytest.raises(NotAllowed):
        wishes.set_wishes(match.pk, make_player(50), _heroes(match, 1))


# --- Who sees them ----------------------------------------------------------------------------


def _both_wish(match: Match) -> tuple[Player, Player, list[int]]:
    a, b = _player(match, "A"), _player(match, "B")
    heroes = _heroes(match)
    wishes.set_wishes(match.pk, a, heroes[:2])
    wishes.set_wishes(match.pk, b, heroes[2:])
    return a, b, heroes


def _wish_ids(snap: schema.MatchSnap) -> list[tuple[str, str, int]]:
    return [(wish.player_id, wish.champion_id, wish.rank) for wish in snap.wishes]


def test_each_team_sees_only_its_own_wishes(popped: Match) -> None:
    match = _coinflip(popped)
    a, b, heroes = _both_wish(match)
    own_a = [(str(a.pk), str(heroes[0]), 1), (str(a.pk), str(heroes[1]), 2)]
    own_b = [(str(b.pk), str(heroes[2]), 1)]
    for viewer in (a, _player(match, "A", captain=True)):
        assert _wish_ids(_seen(match, viewer)) == own_a
    for viewer in (b, _player(match, "B", captain=True)):
        assert _wish_ids(_seen(match, viewer)) == own_b
    for outsider in (make_player(50), None):
        seen = _seen(match, outsider)
        assert seen.wishes == [] and not seen.viewer.can_wish
    # Nothing of the other team's in the wire text, either.
    text = _seen(match, b).model_dump_json()
    assert f'"player_id":"{a.pk}","champion_id"' not in text


def test_the_coinflip_carries_the_heroes_to_wish_from(popped: Match) -> None:
    match = _coinflip(popped)
    seen = _seen(match, _player(match, "A"))
    assert seen.viewer.can_wish
    assert {choice.id for choice in seen.champions} == {str(pk) for pk in match.champion_pool}
    assert not any(choice.taken for choice in seen.champions)


def test_wishes_are_read_only_after_the_hero_draft_and_gone_once_over(popped: Match) -> None:
    match = to_champion_draft(popped)
    a, _, heroes = _both_wish(match)
    match = run_champion_draft(match)
    assert match.status == Status.LOBBY_CODE
    seen = _seen(match, a)
    assert not seen.viewer.can_wish
    assert [wish.champion_id for wish in seen.wishes] == [str(pk) for pk in heroes[:2]]
    assert {str(pk) for pk in heroes} <= {choice.id for choice in seen.champions}
    match = finish(to_in_progress(match))
    assert match.status == Status.COMPLETED
    assert _seen(match, a).wishes == []


def test_a_swapped_player_takes_their_wishes_along(popped: Match) -> None:
    match = to_champion_draft(popped)
    a, b, _ = _both_wish(match)
    swap = swaps.propose(match.pk, _player(match, "A", captain=True), a.pk, b.pk)
    swaps.answer(match.pk, _player(match, "B", captain=True), swap.pk, accept=True)
    on_b = _seen(match, _player(match, "B", captain=True))
    assert {wish.player_id for wish in on_b.wishes} == {str(a.pk)}
    on_a = _seen(match, _player(match, "A", captain=True))
    assert {wish.player_id for wish in on_a.wishes} == {str(b.pk)}


def test_a_sub_starts_with_none_and_the_leaver_sees_none(popped: Match) -> None:
    match = to_champion_draft(popped)
    a, _, _ = _both_wish(match)
    request = subs.request_sub_out(match.pk, a, a.pk)
    newcomer = make_player(40)
    offer = subs.invite_sub(request.pk, a, newcomer.discord_user_id, "P40")
    subs.answer_offer(offer.pk, newcomer, accept=True)
    assert fresh(match).participants.get(player=newcomer).team == "A"
    left = _seen(match, a)
    assert left.wishes == [] and not left.viewer.can_wish and not left.viewer.is_player
    joined = _seen(match, newcomer)
    assert joined.viewer.can_wish
    assert all(wish.player_id != str(a.pk) for wish in joined.wishes)
    with pytest.raises(NotAllowed):
        wishes.set_wishes(match.pk, a, [])
    wishes.set_wishes(match.pk, newcomer, _heroes(match, 1))
    assert [wish.player_id for wish in _seen(match, newcomer).wishes] == [str(newcomer.pk)]
