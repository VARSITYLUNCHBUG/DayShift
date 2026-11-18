"""Component walking, numbering, label matching and Discord's limits."""

from __future__ import annotations

from typing import Any

import pytest

from discord_sim import components
from discord_sim.errors import DiscordError


def button(custom_id: str, label: str = "Go", **extra: object) -> dict[str, object]:
    return {"type": 2, "style": 1, "label": label, "custom_id": custom_id, **extra}


LAYOUT = [
    {
        "type": 17,
        "components": [
            {"type": 10, "content": "## Draft"},
            {"type": 1, "components": [button("a", "✅ Ready"), button("b", "Leave")]},
            {
                "type": 1,
                "components": [
                    {
                        "type": 3,
                        "custom_id": "pick",
                        "placeholder": "Pick a hero",
                        "options": [{"label": "Haze", "value": "haze"}],
                    }
                ],
            },
        ],
    }
]


def test_assign_ids_numbers_depth_first_and_keeps_given_ids() -> None:
    given: list[dict[str, Any]] = [
        {"type": 17, "id": 2, "components": [{"type": 10, "content": "x"}]}
    ]
    numbered = components.assign_ids(given)
    assert [c["id"] for _, c in components.walk(numbered)] == [2, 1]
    assert "id" not in given[0]["components"][0]  # The input isn't touched.


def test_interactive_flattens_buttons_and_selects() -> None:
    flat = components.interactive(LAYOUT)
    assert [(c["custom_id"], c["label"]) for c in flat] == [
        ("a", "✅ Ready"),
        ("b", "Leave"),
        ("pick", "Pick a hero"),
    ]
    assert flat[2]["options"][0]["value"] == "haze"
    assert components.text_of(LAYOUT) == ["## Draft"]


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("✅ Ready", "ready"),
        ("<:dl:123> Pick  Player", "pick player"),
        ("Haze ▸", "haze"),
        (None, ""),
    ],
)
def test_normalize_label(label: str | None, expected: str) -> None:
    assert components.normalize_label(label) == expected


def test_valid_layout_passes() -> None:
    components.validate(LAYOUT, v2=True)


def test_duplicate_custom_ids_are_rejected() -> None:
    rows = [{"type": 1, "components": [button("same"), button("same")]}]
    with pytest.raises(DiscordError) as caught:
        components.validate(rows, v2=False)
    assert caught.value.code == 50035
    assert "COMPONENT_CUSTOM_ID_DUPLICATED" in str(caught.value.errors)


def test_limits() -> None:
    long_label = [{"type": 1, "components": [button("x", "x" * 81)]}]
    with pytest.raises(DiscordError):
        components.validate(long_label, v2=False)
    too_many_rows = [{"type": 1, "components": [button(f"b{i}")]} for i in range(6)]
    with pytest.raises(DiscordError):
        components.validate(too_many_rows, v2=False)
    loose_button = [button("x")]
    with pytest.raises(DiscordError):
        components.validate(loose_button, v2=False)  # Legacy messages need action rows.
    components.validate([{"type": 10, "content": "fine"}], v2=True)
    too_many = [{"type": 10, "content": str(i)} for i in range(41)]
    with pytest.raises(DiscordError):
        components.validate(too_many, v2=True)


def test_link_buttons_need_a_url_and_no_custom_id() -> None:
    rows = [{"type": 1, "components": [{"type": 2, "style": 5, "label": "Join", "custom_id": "x"}]}]
    with pytest.raises(DiscordError) as caught:
        components.validate(rows, v2=False)
    assert caught.value.errors is not None
