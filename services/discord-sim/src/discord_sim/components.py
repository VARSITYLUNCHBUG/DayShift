"""Message components: walking, ID assignment, Discord's limits, and a flat view for /_sim."""

from __future__ import annotations

import copy
import re
import unicodedata
from collections.abc import Callable, Iterator
from typing import Any

from discord_sim.errors import invalid_form

Component = dict[str, Any]

ACTION_ROW = 1
BUTTON = 2
STRING_SELECT = 3
TEXT_INPUT = 4
USER_SELECT = 5
ROLE_SELECT = 6
MENTIONABLE_SELECT = 7
CHANNEL_SELECT = 8
TEXT_DISPLAY = 10
MEDIA_GALLERY = 12
LABEL = 18
FILE_UPLOAD = 19

SELECTS = {STRING_SELECT, USER_SELECT, ROLE_SELECT, MENTIONABLE_SELECT, CHANNEL_SELECT}
INTERACTIVE = {BUTTON, *SELECTS}
LINK_STYLE = 5
PREMIUM_STYLE = 6

EPHEMERAL = 1 << 6
LOADING = 1 << 7
IS_COMPONENTS_V2 = 1 << 15

_CUSTOM_EMOJI = re.compile(r"<a?:\w+:\d+>")


def walk(components: list[Component]) -> Iterator[tuple[str, Component]]:
    """Every component, depth first, with its dotted path (`0.components.1`)."""
    for index, component in enumerate(components):
        yield from _walk(component, str(index))


def _walk(component: Component, path: str) -> Iterator[tuple[str, Component]]:
    yield path, component
    for index, child in enumerate(component.get("components") or []):
        yield from _walk(child, f"{path}.components.{index}")
    for key in ("component", "accessory"):
        child = component.get(key)
        if isinstance(child, dict):
            yield from _walk(child, f"{path}.{key}")


def assign_ids(components: list[Component]) -> list[Component]:
    """A copy with every component numbered, as Discord numbers the ones sent without an `id`."""
    result = copy.deepcopy(components)
    taken = {c["id"] for _, c in walk(result) if isinstance(c.get("id"), int)}
    next_id = 1
    for _, component in walk(result):
        if isinstance(component.get("id"), int):
            continue
        while next_id in taken:
            next_id += 1
        component["id"] = next_id
        taken.add(next_id)
    return result


def map_media_urls(components: list[Component], resolve: Callable[[str], Component | None]) -> None:
    """Replace `attachment://name` media references in place with what `resolve` returns."""
    for _, component in walk(components):
        for holder in _media_holders(component):
            url = holder.get("url", "")
            if isinstance(url, str) and url.startswith("attachment://"):
                resolved = resolve(url.removeprefix("attachment://"))
                if resolved is not None:
                    holder.clear()
                    holder.update(resolved)


def media_references(components: list[Component]) -> list[tuple[str, str]]:
    """(path, filename) for every `attachment://` media reference."""
    found = []
    for path, component in walk(components):
        for key, holder in _media_holders_with_keys(component):
            url = holder.get("url", "")
            if isinstance(url, str) and url.startswith("attachment://"):
                found.append((f"{path}.{key}", url.removeprefix("attachment://")))
    return found


def _media_holders(component: Component) -> list[Component]:
    return [holder for _, holder in _media_holders_with_keys(component)]


def _media_holders_with_keys(component: Component) -> list[tuple[str, Component]]:
    holders: list[tuple[str, Component]] = []
    for key in ("media", "file"):
        value = component.get(key)
        if isinstance(value, dict):
            holders.append((key, value))
    for index, item in enumerate(component.get("items") or []):
        media = item.get("media") if isinstance(item, dict) else None
        if isinstance(media, dict):
            holders.append((f"items.{index}.media", media))
    return holders


def text_of(components: list[Component]) -> list[str]:
    """The text of every TextDisplay, in order."""
    return [
        c["content"]
        for _, c in walk(components)
        if c.get("type") == TEXT_DISPLAY and isinstance(c.get("content"), str)
    ]


def find_custom_id(components: list[Component], custom_id: str) -> Component | None:
    for _, component in walk(components):
        if component.get("custom_id") == custom_id:
            return component
    return None


def interactive(components: list[Component]) -> list[Component]:
    """Buttons and selects in a flat list: what someone could click."""
    flat = []
    for _, c in walk(components):
        kind = c.get("type")
        if kind not in INTERACTIVE:
            continue
        flat.append(
            {
                "type": kind,
                "custom_id": c.get("custom_id"),
                "label": c.get("label") if kind == BUTTON else c.get("placeholder"),
                "emoji": c.get("emoji"),
                "style": c.get("style"),
                "url": c.get("url"),
                "disabled": bool(c.get("disabled", False)),
                "options": [
                    {
                        "label": o.get("label"),
                        "value": o.get("value"),
                        "description": o.get("description"),
                        "emoji": o.get("emoji"),
                        "default": bool(o.get("default", False)),
                    }
                    for o in c.get("options") or []
                ],
                "min_values": c.get("min_values"),
                "max_values": c.get("max_values"),
            }
        )
    return flat


def normalize_label(text: str | None) -> str:
    """Lower case, emoji and symbols gone, spaces collapsed: what `click` matches labels on."""
    if not text:
        return ""
    text = _CUSTOM_EMOJI.sub(" ", text)
    kept = []
    for char in text:
        category = unicodedata.category(char)
        if category.startswith(("L", "N", "P")) or char == " ":
            kept.append(char)
        elif category in {"Zs"}:
            kept.append(" ")
    return " ".join("".join(kept).casefold().split())


def validate(components: list[Component], *, v2: bool, modal: bool = False) -> None:
    """Discord's component limits. Raises 50035 with every problem it finds."""
    problems: dict[str, tuple[str, str]] = {}
    total = 0
    seen: dict[str, str] = {}
    if not v2 and not modal:
        if len(components) > 5:
            problems["components"] = ("BASE_TYPE_MAX_LENGTH", "Must be 5 or fewer in length.")
        for index, row in enumerate(components):
            if row.get("type") != ACTION_ROW:
                problems[f"components.{index}.type"] = (
                    "COMPONENT_LAYOUT_INVALID",
                    "Only action rows are allowed at the top level without IS_COMPONENTS_V2.",
                )
    for path, component in walk(components):
        total += 1
        where = f"components.{path}"
        _check_component(component, where, problems)
        custom_id = component.get("custom_id")
        if isinstance(custom_id, str):
            if custom_id in seen:
                problems[f"{where}.custom_id"] = (
                    "COMPONENT_CUSTOM_ID_DUPLICATED",
                    "Component custom id cannot be duplicated",
                )
            seen[custom_id] = where
    if v2 and total > 40:
        problems["components"] = (
            "COMPONENT_MAX_TOTAL_COMPONENTS_EXCEEDED",
            "The specified component exceeds the maximum number of components (40).",
        )
    if problems:
        raise invalid_form(problems)


def _check_component(
    component: Component, where: str, problems: dict[str, tuple[str, str]]
) -> None:
    kind = component.get("type")
    custom_id = component.get("custom_id")
    if kind == ACTION_ROW:
        children = component.get("components") or []
        if not children or len(children) > 5:
            problems[f"{where}.components"] = (
                "BASE_TYPE_BAD_LENGTH",
                "Must be between 1 and 5 in length.",
            )
        elif any(c.get("type") in SELECTS | {TEXT_INPUT} for c in children) and len(children) > 1:
            problems[f"{where}.components"] = (
                "COMPONENT_LAYOUT_WIDTH_EXCEEDED",
                "The specified component exceeds the maximum width",
            )
    if kind == BUTTON:
        style = component.get("style")
        label = component.get("label")
        if style == LINK_STYLE:
            if not component.get("url"):
                problems[f"{where}.url"] = ("BASE_TYPE_REQUIRED", "This field is required")
            if custom_id is not None:
                problems[f"{where}.custom_id"] = (
                    "COMPONENT_INVALID_FIELD",
                    "Link buttons cannot have a custom id",
                )
        elif style != PREMIUM_STYLE and not custom_id:
            problems[f"{where}.custom_id"] = ("BASE_TYPE_REQUIRED", "This field is required")
        if isinstance(label, str) and len(label) > 80:
            problems[f"{where}.label"] = ("BASE_TYPE_MAX_LENGTH", "Must be 80 or fewer in length.")
        if not label and not component.get("emoji") and style != PREMIUM_STYLE:
            problems[f"{where}.label"] = (
                "BUTTON_COMPONENT_LABEL_OR_EMOJI_REQUIRED",
                "A label or emoji is required",
            )
    if kind in SELECTS | {TEXT_INPUT, FILE_UPLOAD} and not custom_id:
        problems[f"{where}.custom_id"] = ("BASE_TYPE_REQUIRED", "This field is required")
    if isinstance(custom_id, str) and len(custom_id) > 100:
        problems[f"{where}.custom_id"] = ("BASE_TYPE_MAX_LENGTH", "Must be 100 or fewer in length.")
    if kind == STRING_SELECT:
        options = component.get("options") or []
        if not 1 <= len(options) <= 25:
            problems[f"{where}.options"] = (
                "BASE_TYPE_BAD_LENGTH",
                "Must be between 1 and 25 in length.",
            )
        values = [o.get("value") for o in options]
        if len(set(values)) != len(values):
            problems[f"{where}.options"] = (
                "SELECT_COMPONENT_OPTION_VALUE_DUPLICATED",
                "Select component option values must be unique",
            )
        for index, option in enumerate(options):
            for key in ("label", "value"):
                text = option.get(key)
                if not isinstance(text, str) or not 1 <= len(text) <= 100:
                    problems[f"{where}.options.{index}.{key}"] = (
                        "BASE_TYPE_BAD_LENGTH",
                        "Must be between 1 and 100 in length.",
                    )
    if kind in SELECTS:
        placeholder = component.get("placeholder")
        if isinstance(placeholder, str) and len(placeholder) > 150:
            problems[f"{where}.placeholder"] = (
                "BASE_TYPE_MAX_LENGTH",
                "Must be 150 or fewer in length.",
            )
        low = component.get("min_values", 1)
        high = component.get("max_values", 1)
        if not (0 <= low <= 25 and 1 <= high <= 25 and low <= high):
            problems[f"{where}.max_values"] = (
                "BASE_TYPE_BAD_RANGE",
                "min_values and max_values must be between 0 and 25, min <= max.",
            )
    if kind == TEXT_DISPLAY:
        content = component.get("content")
        if not isinstance(content, str) or not content:
            problems[f"{where}.content"] = ("BASE_TYPE_REQUIRED", "This field is required")
        elif len(content) > 4000:
            problems[f"{where}.content"] = (
                "BASE_TYPE_MAX_LENGTH",
                "Must be 4000 or fewer in length.",
            )
    if kind == MEDIA_GALLERY:
        items = component.get("items") or []
        if not 1 <= len(items) <= 10:
            problems[f"{where}.items"] = (
                "BASE_TYPE_BAD_LENGTH",
                "Must be between 1 and 10 in length.",
            )
