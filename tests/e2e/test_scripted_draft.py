"""Champion plans and a match script set in the panel, and the match played to follow them.

The two weakest fixture players get champion plans on the Players screen; the match's Script…
makes them captains, sets the draft order (weakest first, the opposite of the default), the
first champion step, the coinflip side and the winner. One Advance to Completed through the
bot's buttons must then do exactly that.
"""

from __future__ import annotations

from support.api import JSON, ControlApi, SimApi, text_of
from support.boards import result_post
from support.pages import ControlPanel

# Disjoint, so neither captain's plan can take the other's champion.
PLANS = {
    "Kit": {
        "prefer": ["haze", "wraith", "lash", "mirage", "pocket", "vyper"],
        "ban": ["seven", "vindicta", "abrams"],
    },
    "Lux": {
        "prefer": ["infernus", "dynamo", "kelvin", "bebop", "calico", "shiv"],
        "ban": ["ivy", "warden", "yamato"],
    },
}
FIRST_STEP = "paradox"


def expected_champions(match: JSON) -> list[str]:
    """The champion each step of the draft should have taken: the script's for step 0, then the
    first unused one of the acting team's captain's plan for that action."""
    captain = {
        team: next(p["name"] for p in match["players"] if p["id"] == pk)
        for team, pk in match["captains"].items()
    }
    steps = sorted(
        (p for p in match["picks"] if p["action"] != "player_pick"), key=lambda p: p["step"]
    )
    used: set[str] = set()
    expected = []
    for index, step in enumerate(steps):
        if index == 0:
            slug = FIRST_STEP
        else:
            wanted = PLANS[captain[step["team"]]]["ban" if step["action"] == "ban" else "prefer"]
            slug = next(s for s in wanted if s not in used)
        used.add(slug)
        expected.append(slug)
    return expected


def test_the_draft_follows_the_plans_and_the_script(
    panel: ControlPanel, control: ControlApi, sim: SimApi
) -> None:
    joined = control.call("POST", "queue/join", {"count": 12, "via": "service"})
    match = control.match(joined["match_id"])
    ids = {p["name"]: p["id"] for p in match["players"]}
    captains = [ids["Kit"], ids["Lux"]]
    # The fixture's ratings fall with the id, so the weakest first is the highest id first.
    order = sorted((pk for pk in ids.values() if pk not in captains), reverse=True)

    players = panel.players()
    for name, plan in PLANS.items():
        players.set_plan(name, plan["prefer"], plan["ban"])
    matches = panel.matches()
    card = matches.card(match["id"])
    (
        card.script()
        .captain_votes(f'{{"*": [{captains[0]}, {captains[1]}]}}')
        .draft_order(order)
        .champion_steps({0: FIRST_STEP})
        .coinflip("archmother")
        .winner("B")
        .save()
    )
    script = control.match(match["id"])["script"]
    assert (script["draft"], script["coinflip"], script["winner"]) == (order, "archmother", "B")

    matches.act_via("Act via Discord clicks")
    card.advance_to("ready_check", "completed")

    done = control.match(match["id"])
    assert done["status"] == "completed"
    assert sorted(done["captains"].values()) == sorted(captains)
    drafted = [
        p["player_id"]
        for p in sorted(done["picks"], key=lambda p: p["step"])
        if p["action"] == "player_pick"
    ]
    assert drafted == order
    champions = [
        p for p in sorted(done["picks"], key=lambda p: p["step"]) if p["action"] != "player_pick"
    ]
    assert [p["champion"]["slug"] for p in champions] == expected_champions(done)
    assert all(p["source"] == "user" for p in champions)
    assert done["coinflip_winner"] in {"A", "B"}
    assert done["hidden_king_team"] != done["coinflip_winner"], "the winner took the Archmother"
    assert done["winner"] == "B"

    results = control.state()["community"]["channels"]["results"]
    post = text_of(result_post(sim, results, done["id"]))
    captain_b = next(p["name"] for p in done["players"] if p["id"] == done["captains"]["B"])
    assert post.startswith(f"## Match #{done['id']}: {captain_b}'s Team won")
    for pick in champions:
        assert pick["champion"]["name"] in post
